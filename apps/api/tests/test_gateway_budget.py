"""Phase 5 daily budget (plan Phase 5 task 5.10 "daily budget hard stop"; plan I "alert at 80% of budget"; AC-5-9; A-15,
hold H9; PD-26; Phase 5 spec 4.4)."""

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
