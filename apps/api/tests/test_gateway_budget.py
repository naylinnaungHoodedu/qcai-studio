"""Phase 5 daily budget (plan Phase 5 task 5.10 "daily budget hard stop"; plan I "alert at 80% of budget"; AC-5-9; A-15,
hold H9; PD-26; Phase 5 spec 4.4): the per-process DailyBudget a test passes, and the shared DatabaseBudget every
instance of a registry spends from."""

from __future__ import annotations

from datetime import date
import json
import logging

import pytest

from app.core.config import Settings
from app.gateway.budget import DailyBudget
from v2_fakes import fake_spec, fresh_gateway


class Today:
    def __init__(self) -> None:
        self.value = date(2026, 11, 21)

    def __call__(self) -> date:
        return self.value


def _alerts(caplog) -> list[dict]:
    return [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.budget_alert"]


def test_reserve_alerts_once_at_four_fifths_and_refuses_beyond_the_budget(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    budget = DailyBudget(10)
    assert [budget.reserve(1) for _ in range(7)] == [True] * 7 and _alerts(caplog) == []
    assert budget.reserve(1) and _alerts(caplog) == [{"event": "gateway.budget_alert", "share": "4/5", "daily_units": 10, "spent": 8}]
    assert budget.reserve(2) and budget.remaining() == 0
    assert not budget.reserve(1) and budget.spent == 10
    assert len(_alerts(caplog)) == 1
    assert json.dumps(budget.snapshot()) and budget.snapshot() == {"daily_units": 10, "spent_today": 10, "alerted": True}


def test_the_budget_resets_at_the_utc_day(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    today = Today()
    budget = DailyBudget(5, today=today)
    assert all(budget.reserve(1) for _ in range(5)) and not budget.reserve(1)
    today.value = date(2026, 11, 22)
    assert budget.remaining() == 5 and budget.reserve(4) and budget.alerted
    assert len(_alerts(caplog)) == 2


def test_the_shared_budget_is_one_budget_for_every_instance_with_one_alert_a_day(caplog):
    # Two DatabaseBudget objects over one registry are two instances: they spend from one row, so the hard stop holds
    # however many instances run (task 5.10), and the 4/5 alert is logged once a day across them.
    from app.gateway.controls import DatabaseBudget

    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    today = Today()
    first, second = DatabaseBudget("development", 10, today=today), DatabaseBudget("development", 10, today=today)
    assert [first.reserve(1) for _ in range(4)] + [second.reserve(1) for _ in range(3)] == [True] * 7 and _alerts(caplog) == []
    assert second.reserve(1) and _alerts(caplog) == [{"event": "gateway.budget_alert", "share": "4/5", "daily_units": 10, "spent": 8}]
    assert first.reserve(2) and first.remaining() == second.remaining() == 0
    assert not second.reserve(1) and not first.reserve(1) and not first.reserve(11)
    assert len(_alerts(caplog)) == 1
    assert first.snapshot() == second.snapshot() == {"daily_units": 10, "spent_today": 10, "alerted": True}
    assert DatabaseBudget("staging", 10, today=today).remaining() == 10  # each registry spends from its own row
    today.value = date(2026, 11, 22)
    assert first.remaining() == 10 and second.reserve(8) and len(_alerts(caplog)) == 2
    zero = DatabaseBudget("default", 0, today=today)  # a budget of 0 (every registry outside development) refuses any cost
    assert zero.reserve(0) and not zero.reserve(1) and zero.remaining() == 0


def test_the_process_gateway_spends_from_the_shared_budget_and_keeps_the_shared_stop():
    from app.gateway.controls import DatabaseBudget, DatabaseStopStore
    from app.gateway.gateway import get_gateway, reset_process_gateway

    gateway = get_gateway()
    assert isinstance(gateway.budget, DatabaseBudget) and isinstance(gateway.stop_store, DatabaseStopStore)
    assert (gateway.budget.registry, gateway.budget.daily_units, gateway.stop_store.registry) == ("development", 100000, "development")
    assert gateway.budget.reserve(3)
    reset_process_gateway()  # a new process: the spend stays
    assert get_gateway().budget.snapshot()["spent_today"] == 3


def test_a_zero_budget_makes_every_adapter_ineligible_and_a_low_one_drops_a_costly_adapter():
    settings = Settings()
    specs = [fake_spec("fake-alpha"), fake_spec("fake-beta", cost=0)]
    assert fresh_gateway(0).eligible(specs, settings=settings) == []
    gateway = fresh_gateway(3)
    assert [spec.adapter_id for spec in gateway.eligible([fake_spec("fake-alpha", cost=4), fake_spec("fake-beta", cost=3)], settings=settings)] == ["fake-beta-v1"]
    assert gateway.ineligible_reason(fake_spec("fake-alpha", cost=4), settings=settings) == "budget"


def test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged(caplog, monkeypatch):
    # Task 5.10 "daily budget hard stop", R-47: the budget reserves each call's cost_units_per_call, so a provider that
    # reports more than the reservation breaches it (budget_breach), and every later call is refused and logged.
    import httpx
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.db_models import SecurityEvent
    from app.gateway import policy
    from app.gateway.adapters import HttpJsonAdapter
    from app.gateway.contracts import VerdictInstructions, VerdictRequest, VerdictSpan
    from app.gateway.gateway import GatewayStopped
    from app.gateway.metrics import GATEWAY_METRICS
    from app.services.v2_panel.rules import verifier_prompt_hash
    from v2_fakes import FakeSecretStore

    caplog.set_level(logging.INFO, logger="qcai.gateway")
    monkeypatch.setattr(policy.PayloadPolicy, "check", lambda self, request, context: None)
    spec = fake_spec("test-family", provider="test-provider", endpoint="https://verifier.invalid/v1", auth_header="x-api-key",
                     secret_ref="TEST_PROVIDER_KEY", cost=1)
    reply = httpx.Response(200, json={"output": {"verdict": "SUPPORTED", "ehmf_type": None, "span_id": "span-" + "a" * 64},
                                      "usage": {"cost_units": 7}})
    adapter = HttpJsonAdapter(spec, secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": "test-key-0123456789"}),
                              transport=httpx.MockTransport(lambda http_request: reply), sleep=lambda seconds: None)
    gateway = fresh_gateway(10, adapters={spec.adapter_id: adapter})
    item = VerdictRequest(claim_text="A claim.", span=VerdictSpan(span_id="span-" + "a" * 64, text="A claim."),
                          instructions=VerdictInstructions(prompt_hash=verifier_prompt_hash(), tool_contract_version="mcp-tools-v1"))
    with SessionLocal() as db:
        start = int(db.scalar(select(func.max(SecurityEvent.seq))) or 0)
    GATEWAY_METRICS.reset()
    with pytest.raises(GatewayStopped):
        gateway.verify(spec, item, context=None)
    assert (gateway.state, gateway.stop_reason) == ("stopped", "budget_breach")
    with SessionLocal() as db:
        events = list(db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == "gateway.stopped")
                                 .order_by(SecurityEvent.seq)))
    assert [event.details.get("reason") for event in events] == ["budget_breach"]
    with pytest.raises(GatewayStopped):
        gateway.verify(spec, item, context=None)
    calls = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.call"]
    assert [(line["outcome"], line["cost_units"]) for line in calls] == [("error", 1), ("refused", 0)]
    snapshot = GATEWAY_METRICS.snapshot()
    assert snapshot["calls"] == {f"{spec.adapter_id}:error": 1, f"{spec.adapter_id}:refused": 1}
    assert len(GATEWAY_METRICS.latency[spec.adapter_id]) == 1  # a refused call adds no latency sample


def _http_member(cost: int = 1):
    import httpx

    from app.gateway.adapters import HttpJsonAdapter
    from v2_fakes import FakeSecretStore

    spec = fake_spec("test-family", provider="test-provider", endpoint="https://verifier.invalid/v1", auth_header="x-api-key",
                     secret_ref="TEST_PROVIDER_KEY", cost=cost, max_retries=2)
    seen: list = []
    replies: list = []

    def handler(http_request):
        seen.append(http_request)
        return replies.pop(0) if replies else httpx.Response(500)

    adapter = HttpJsonAdapter(spec, secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": "test-key-0123456789"}),
                              transport=httpx.MockTransport(handler), sleep=lambda seconds: None)
    return spec, adapter, seen, replies


def _claim_item():
    from app.gateway.contracts import VerdictInstructions, VerdictRequest, VerdictSpan
    from app.services.v2_panel.rules import verifier_prompt_hash

    return VerdictRequest(claim_text="A claim.", span=VerdictSpan(span_id="span-" + "a" * 64, text="A claim."),
                          instructions=VerdictInstructions(prompt_hash=verifier_prompt_hash(), tool_contract_version="mcp-tools-v1"))


def test_every_retry_an_adapter_sends_is_reserved_and_a_refused_retry_stops_the_gateway(caplog, monkeypatch):
    # Plan 5.10 "daily budget hard stop": the call's reservation covers its first attempt, and each retry reserves one
    # more call's cost before it is sent (the reserve_retry hook), so the budget counts every request a provider may bill.
    import httpx

    from app.gateway import policy
    from app.gateway.gateway import GatewayStopped

    caplog.set_level(logging.INFO, logger="qcai.gateway")
    monkeypatch.setattr(policy.PayloadPolicy, "check", lambda self, request, context: None)
    spec, adapter, seen, replies = _http_member()
    ok = {"output": {"verdict": "SUPPORTED", "ehmf_type": None, "span_id": "span-" + "a" * 64}, "usage": {"cost_units": 1}}
    replies.extend([httpx.Response(500), httpx.Response(503), httpx.Response(200, json=ok)])
    gateway = fresh_gateway(10, adapters={spec.adapter_id: adapter})
    assert gateway.verify(spec, _claim_item(), context=None).verdict == "SUPPORTED"
    assert len(seen) == 3 and gateway.budget.spent == 3
    calls = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.call"]
    assert [(line["outcome"], line["cost_units"]) for line in calls] == [("ok", 3)]
    # Two units: the first attempt and one retry are sent; the second retry is refused before it is sent.
    spec, adapter, seen, replies = _http_member()
    gateway = fresh_gateway(2, adapters={spec.adapter_id: adapter})
    with pytest.raises(GatewayStopped):
        gateway.verify(spec, _claim_item(), context=None)
    assert len(seen) == 2 and gateway.budget.spent == 2 and (gateway.state, gateway.stop_reason) == ("stopped", "budget_breach")


class _Unreadable(DailyBudget):
    """A budget whose store fails as a database outage would (sqlalchemy OperationalError)."""

    def __init__(self, units: int, *, fail_remaining: bool = True, fail_reserve_after: int = 0) -> None:
        super().__init__(units)
        self.fail_remaining = fail_remaining
        self.fail_reserve_after = fail_reserve_after
        self.reserved = 0

    def remaining(self) -> int:
        from sqlalchemy.exc import OperationalError

        if self.fail_remaining:
            raise OperationalError("SELECT gateway_budget_days", {}, Exception("database unavailable"))
        return super().remaining()

    def reserve(self, cost: int) -> bool:
        from sqlalchemy.exc import OperationalError

        if self.reserved >= self.fail_reserve_after:
            raise OperationalError("UPDATE gateway_budget_days", {}, Exception("database unavailable"))
        self.reserved += 1
        return super().reserve(cost)


def test_a_budget_store_failure_makes_members_unavailable_without_a_stop_or_a_raise(caplog, monkeypatch):
    # F-1: an unreadable or unwritable shared budget never escapes the gateway. Eligibility drops every member
    # (budget_unavailable); a call whose reservation (or a retry's) fails is refused (GatewayRefused): nothing is sent,
    # nothing is spent and the gateway stays open.
    from app.gateway import policy
    from app.gateway.adapters import FakeAdapter
    from app.gateway.gateway import GatewayRefused, GatewayStopped, ModelGateway
    from app.gateway.metrics import GATEWAY_METRICS

    caplog.set_level(logging.INFO, logger="qcai.gateway")
    monkeypatch.setattr(policy.PayloadPolicy, "check", lambda self, request, context: None)
    GATEWAY_METRICS.reset()
    fake = fake_spec("fake-alpha")
    unreadable = ModelGateway(budget=_Unreadable(10), adapters={fake.adapter_id: FakeAdapter(fake)})
    assert unreadable.eligible([fake], settings=Settings()) == [] and unreadable.state == "open"
    assert GATEWAY_METRICS.snapshot()["ineligible"] == {"budget_unavailable": 1}
    adapter = FakeAdapter(fake)
    unwritable = ModelGateway(budget=_Unreadable(10, fail_remaining=False), adapters={fake.adapter_id: adapter})
    assert unwritable.eligible([fake], settings=Settings()) == [fake]
    with pytest.raises(GatewayRefused) as excinfo:
        unwritable.verify(fake, _claim_item(), context=None)
    assert not isinstance(excinfo.value, GatewayStopped) and adapter.calls == 0 and unwritable.state == "open"
    # A retry whose reservation fails is not sent, and the member is only unavailable.
    spec, http_adapter, seen, replies = _http_member()
    retrying = ModelGateway(budget=_Unreadable(10, fail_remaining=False, fail_reserve_after=1), adapters={spec.adapter_id: http_adapter})
    with pytest.raises(GatewayRefused) as excinfo:
        retrying.verify(spec, _claim_item(), context=None)
    assert not isinstance(excinfo.value, GatewayStopped) and len(seen) == 1 and retrying.state == "open"
    events = [getattr(record, "json_fields", {}).get("event") for record in caplog.records]
    assert events.count("gateway.budget_unavailable") == 3 and "gateway.stopped" not in events


class _Store:
    """A shared stop store whose read or write fails as a database outage would."""

    def __init__(self, *, read_fails: bool = False, write_fails: bool = False) -> None:
        self.read_fails, self.write_fails = read_fails, write_fails
        self.reads = 0

    def read(self):
        from sqlalchemy.exc import OperationalError

        self.reads += 1
        if self.read_fails:
            raise OperationalError("SELECT gateway_stops", {}, Exception("database unavailable"))
        return None

    def write(self, reason: str) -> None:
        from sqlalchemy.exc import OperationalError

        if self.write_fails:
            raise OperationalError("INSERT gateway_stops", {}, Exception("database unavailable"))


def test_an_unreadable_shared_stop_keeps_the_state_and_never_raises_into_a_call(caplog, monkeypatch):
    # Spec 4.5: a read that fails logs gateway.stop_unread and leaves the state as it is; it never raises into an
    # eligibility decision, a call, the V2 mode or /ready, and never reopens a stopped gateway.
    from fastapi.testclient import TestClient

    from app.core.config_package import get_config_package
    from app.gateway import policy
    from app.gateway.adapters import FakeAdapter
    from app.gateway.controls import DatabaseStopStore
    from app.gateway.gateway import GatewayStopped, ModelGateway
    from app.main import app
    from app.services import v2_panel

    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    monkeypatch.setattr(policy.PayloadPolicy, "check", lambda self, request, context: None)
    fake = fake_spec("fake-alpha")
    store = _Store(read_fails=True)
    gateway = ModelGateway(budget=DailyBudget(10), adapters={fake.adapter_id: FakeAdapter(fake)}, stop_store=store)
    assert gateway.eligible([fake], settings=Settings()) == [fake]
    assert gateway.verify(fake, _claim_item(), context=None).verdict == "SUPPORTED"
    assert v2_panel.mode(Settings(model_gateway="on"), get_config_package(Settings()), gateway=gateway) == "on"
    unread = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.stop_unread"]
    assert len(unread) == store.reads == 3 and gateway.state == "open"
    gateway.stop("secret_in_logs")
    reads = store.reads
    with pytest.raises(GatewayStopped):
        gateway.verify(fake, _claim_item(), context=None)
    assert gateway.state == "stopped" and store.reads == reads  # a stopped gateway reads no more and never reopens
    # The process gateway's store failing: /ready still answers, with the state it holds.
    from sqlalchemy.exc import OperationalError

    def fail(self):
        raise OperationalError("SELECT gateway_stops", {}, Exception("database unavailable"))

    monkeypatch.setattr(DatabaseStopStore, "read", fail)
    response = TestClient(app).get("/ready")
    assert response.status_code == 200 and response.json()["gateway"]["state"] == "open" and response.json()["model_gateway"] == "shadow"


def test_an_unwritable_shared_stop_still_stops_this_instance_and_says_so(caplog):
    # Spec 4.5: a write that fails logs gateway.stop_unshared (the line the runbook acts on) and this instance stays
    # stopped; stop() returns normally and the security event is written.
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.db_models import SecurityEvent
    from app.gateway.gateway import ModelGateway

    caplog.set_level(logging.ERROR, logger="qcai.gateway")
    with SessionLocal() as db:
        start = int(db.scalar(select(func.max(SecurityEvent.seq))) or 0)
    gateway = ModelGateway(budget=DailyBudget(10), stop_store=_Store(write_fails=True))
    assert gateway.stop("payload_violation") is None and (gateway.state, gateway.stop_reason) == ("stopped", "payload_violation")
    unshared = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.stop_unshared"]
    assert unshared == [{"event": "gateway.stop_unshared", "reason": "payload_violation"}]
    with SessionLocal() as db:
        events = db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == "gateway.stopped")
                            .order_by(SecurityEvent.seq)).all()
    assert [event.details.get("reason") for event in events] == ["payload_violation"]
