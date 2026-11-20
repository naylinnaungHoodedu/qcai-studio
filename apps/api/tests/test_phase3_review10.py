"""Phase 3, tenth review round (2026-11-20; Phase 3 spec 18.4, review history, round 10). Each test fails if its
defect comes back.

K1  the invariant 1 fixture tells learners apart by every field it is meant to compare: a learner-dependent
    abstention reason, floor, margin, sufficiency score, counts or top_k each fails it, and the record it compares
    keeps every field of the shadow record but its ids.
K2  a new Cloud SQL connection is bounded by app.core.db (CONNECT_TIMEOUT_S), as the attempt horizon assumes: the
    connector bounds none of it.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import logging
import math
from pathlib import Path
import threading
import time

from google.cloud.sql.connector import IPTypes
import pg8000.dbapi
import pytest
from sqlalchemy import create_engine, exc as sa_exc
from sqlalchemy.engine import URL
from sqlalchemy.pool import QueuePool

from app.core import db as db_module
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import CONNECT_MAX_PENDING, CONNECT_TIMEOUT_S, ConnectTimeout, bounded_connect, cloud_sql_creator
from app.core.structured_logging import FIELDS
from app.services import ledger
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.pipeline import TwoPassPipeline

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


# ============================================================================================================ K1


def _old_projection(item: dict) -> dict:
    """The five fields the invariant 1 test compared before the ninth round."""
    record = item["record"]
    return {"request": item["retrieve"]["request"], "envelopes": item["envelopes"],
            "bundle": [(span["span_id"], span["score"]) for span in record["retrieval"]["evidence"]],
            "claim_set_hash": record["claim_set_hash"], "decision": record["decision"]}


_LEARNER = {"mastery": None}


def _for_one_learner(mutate):
    """mutate(value) for the 0.9 learner only; the others see the value unchanged."""
    return lambda value: mutate(value) if _LEARNER["mastery"] == 0.9 else value


def _patch_entry(monkeypatch, mutate) -> None:
    real = TwoPassPipeline._entry
    mutate_one = _for_one_learner(mutate)
    monkeypatch.setattr(TwoPassPipeline, "_entry", lambda self, *args, **kwargs: mutate_one(real(self, *args, **kwargs)))


def _patch_bundle(monkeypatch, mutate) -> None:
    real = pipeline_module.retrieve
    mutate_one = _for_one_learner(mutate)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kwargs: mutate_one(real(engine, request, **kwargs)))


def _sufficiency(**changes):
    def mutate(bundle):
        sufficiency = bundle.sufficiency
        update = {key: change(getattr(sufficiency, key)) for key, change in changes.items()}
        return bundle.model_copy(update={"sufficiency": sufficiency.model_copy(update=update)})
    return mutate


def _other_reason(entry):
    if entry.decision != "abstain":
        return entry
    other = next(reason for reason in contracts.GATE_ABSTENTION_REASONS if reason != entry.abstention_reason)
    assert other in contracts.ABSTENTION_REASONS
    return entry.model_copy(update={"abstention_reason": other})


def _more_render_attempts(entry):
    return entry.model_copy(update={"counts": entry.counts.model_copy(update={"render_attempts": entry.counts.render_attempts + 1})})


def _learner_dependent_top_k(monkeypatch) -> None:
    """The pipeline asks for one more span for the 0.9 learner, and the retrieval itself still uses the packaged
    top_k: the bundle, the record and the old five fields stay equal, and only the retrieval call differs."""
    real_retrieve = pipeline_module.retrieve
    real_run = TwoPassPipeline.run

    def run(self, item, **kwargs):
        if _LEARNER["mastery"] != 0.9:
            return real_run(self, item, **kwargs)
        params = self.params
        self.params = dataclasses.replace(params, top_k=params.top_k + 1)
        try:
            return real_run(self, item, **kwargs)
        finally:
            self.params = params

    monkeypatch.setattr(TwoPassPipeline, "run", run)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, *, top_k, registry: real_retrieve(
        engine, request, top_k=packaged_top_k(), registry=registry))


def packaged_top_k() -> int:
    return get_config_package(Settings()).tutor_pipeline.top_k


LEARNER_DEPENDENT = {
    # A learner-dependent abstention reason: the decision, spans and hash stay equal (finding K1 named it).
    "abstention_reason": lambda monkeypatch: _patch_entry(monkeypatch, _other_reason),
    "counts": lambda monkeypatch: _patch_entry(monkeypatch, _more_render_attempts),
    # A learner-dependent floor, margin or sufficiency score that leaves the same results above it.
    "floor": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(floor=lambda value: value + 0.001)),
    "margin": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(margin=lambda value: value + 0.001)),
    "sufficiency_score": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(score=lambda value: (value or 0.0) + 0.001)),
    # Plan 12.4(c) and CT-04: an identical top-k.
    "top_k": _learner_dependent_top_k,
}


@pytest.mark.parametrize("field", sorted(LEARNER_DEPENDENT))
def test_k1_each_learner_dependent_value_fails_the_invariant_1_fixture(monkeypatch, field):
    from test_phase3_acceptance import observe_three_learners

    monkeypatch.setitem(_LEARNER, "mastery", None)
    LEARNER_DEPENDENT[field](monkeypatch)
    observed, captured, _ = observe_three_learners(monkeypatch, prefix=f"k1-{field.replace('_', '-')}",
                                                   on_learner=lambda mastery: _LEARNER.__setitem__("mastery", mastery))
    # The comparison before the ninth round could not see it: its five fields are equal for all three learners.
    assert all([_old_projection(item) for item in learner] == [_old_projection(item) for item in observed[0]] for learner in observed)
    # The fixture does: the 0.1 and 0.5 learners agree and the 0.9 learner differs.
    assert observed[1] == observed[0] and observed[2] != observed[0]
    differing = [index for index, (item, other) in enumerate(zip(observed[2], observed[0])) if item != other]
    assert differing
    if field == "top_k":
        top_ks = {call["top_k"] for call in captured["requests"]}
        assert len(top_ks) == 2 and all(observed[2][index]["retrieve"] != observed[0][index]["retrieve"] for index in differing)
        assert all(observed[2][index]["record"] == observed[0][index]["record"] for index in range(len(observed[0])))
    else:
        assert all(observed[2][index]["record"] != observed[0][index]["record"] for index in differing)
    if field == "abstention_reason":
        assert any(item["record"]["decision"] == "abstain" for item in observed[2])


def _perturbed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "-other"
    if value is None:
        return "other"
    if isinstance(value, list):
        return [*value, {"other": 1}]
    if isinstance(value, dict):
        return {**value, "other": 1}
    raise AssertionError(type(value))


def _leaves(value, path=()):
    """Every leaf of a JSON value (an empty list or object counts as one), with its path."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _leaves(item, (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path, value


def _set(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


IDS = {("response_id",), ("shadowed_response_id",)}


def _is_id(path) -> bool:
    """The fields that name the response, the turn it shadows and the learner's own turns: learner_independent leaves
    out exactly these."""
    return (path in IDS or path[:2] == ("resolved_question", "source_turn_ids")
            or (len(path) == 3 and path[0] == "claims" and path[2] == "response_id"))


def test_k1_the_compared_record_keeps_every_field_of_the_shadow_record_but_its_ids(monkeypatch):
    from test_phase3_acceptance import entry_of, learner_independent, observe_three_learners, records

    observed, _, _ = observe_three_learners(monkeypatch, prefix="k1-leaves")
    entries = [entry_of(row) for row in records(delivery="shadow")[-len(observed[0]) * 3:]]
    answered = next(entry for entry in entries if entry["decision"] == "answer" and entry["claims"])
    abstained = next(entry for entry in entries if entry["decision"] == "abstain")
    checked = 0
    for entry in (answered, abstained):
        reference = learner_independent(entry)
        for path, value in _leaves(entry):
            changed = copy.deepcopy(entry)
            _set(changed, path, _perturbed(value))
            if _is_id(path):
                assert learner_independent(changed) == reference, path
            else:
                assert learner_independent(changed) != reference, path
                checked += 1
    # The fields plan 7.8 invariant 1, 12.4(c) and CT-04 name are among those compared.
    named = {("abstention_reason",), ("retrieval", "floor"), ("retrieval", "margin"), ("retrieval", "threshold_version"),
             ("retrieval", "sufficiency", "decision"), ("retrieval", "sufficiency", "floor"), ("counts", "render_attempts")}
    assert named <= {path for path, _ in _leaves(abstained)} | {path for path, _ in _leaves(answered)}
    assert checked > 60


def test_k1_the_retrieval_call_the_fixture_records_holds_the_top_k_the_pipeline_passed(monkeypatch):
    from test_phase3_acceptance import observe_three_learners

    observed, captured, _ = observe_three_learners(monkeypatch, prefix="k1-topk")
    assert {call["top_k"] for call in captured["requests"]} == {packaged_top_k()}
    assert all(item["retrieve"]["top_k"] == packaged_top_k() for learner in observed for item in learner)


# ============================================================================================================ K2


class _Connection:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class _StalledConnector:
    """A Cloud SQL connector whose connect waits until released (an instance that accepts TCP and never answers)."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.release = threading.Event()
        self.calls: list[tuple] = []
        self.made: list[_Connection] = []
        self.error = error

    def connect(self, connection_name, driver, **kwargs):
        self.calls.append((connection_name, driver, kwargs))
        self.release.wait(10)
        if self.error is not None:
            raise self.error
        connection = _Connection()
        self.made.append(connection)
        return connection


def _creator(connector, *, timeout_s=0.3, max_pending=CONNECT_MAX_PENDING):
    return cloud_sql_creator(connector, "project:region:instance", user="app", password="pw", db="qcai", ip_type=IPTypes.PRIVATE,
                             timeout_s=timeout_s, max_pending=max_pending)


def test_k2_a_stalled_cloud_sql_connect_raises_at_its_bound_and_its_late_connection_is_closed(caplog):
    connector = _StalledConnector()
    creator = _creator(connector)
    caplog.set_level(logging.WARNING, logger="qcai.db")
    started = time.monotonic()
    with pytest.raises(ConnectTimeout):
        creator()
    elapsed = time.monotonic() - started
    assert 0.25 <= elapsed < 1.5, elapsed
    events = [getattr(record, FIELDS, {}).get("event") for record in caplog.records]
    assert "db.connect.timeout" in events
    # The connector returns later: that connection never reaches the pool, it is closed.
    connector.release.set()
    deadline = time.monotonic() + 5
    while not connector.made and time.monotonic() < deadline:
        time.sleep(0.01)
    assert connector.made and connector.made[0].closed.wait(5)
    assert issubclass(ConnectTimeout, pg8000.dbapi.OperationalError)


def test_k2_a_connect_within_the_bound_returns_its_connection_and_an_error_is_raised_unchanged():
    connector = _StalledConnector()
    connector.release.set()
    connection = _creator(connector, timeout_s=5)()
    assert connection is connector.made[0] and not connection.closed.is_set()
    assert connector.calls == [("project:region:instance", "pg8000", {"user": "app", "password": "pw", "db": "qcai", "ip_type": IPTypes.PRIVATE})]
    refused = ConnectionRefusedError("refused (test)")
    failing = _StalledConnector(error=refused)
    failing.release.set()
    with pytest.raises(ConnectionRefusedError) as raised:
        _creator(failing, timeout_s=5)()
    assert raised.value is refused


def test_k2_sqlalchemy_raises_a_stalled_connect_as_an_operational_error_within_the_bound():
    connector = _StalledConnector()
    engine = create_engine(URL.create("postgresql+pg8000"), creator=_creator(connector), poolclass=QueuePool)
    try:
        started = time.monotonic()
        with pytest.raises(sa_exc.OperationalError) as raised:
            engine.connect()
        assert time.monotonic() - started < 1.5
        assert isinstance(raised.value.orig, ConnectTimeout)
    finally:
        connector.release.set()
        engine.dispose()


def test_k2_the_connect_slots_cap_the_stalled_connects():
    connector = _StalledConnector()
    creator = _creator(connector, timeout_s=0.2, max_pending=2)
    for _ in range(2):
        with pytest.raises(ConnectTimeout):
            creator()
    started = time.monotonic()
    with pytest.raises(ConnectTimeout, match="slot"):
        creator()  # both slots are held by stalled connects: no third thread, and the wait still ends at the bound
    assert time.monotonic() - started < 1.0 and len(connector.calls) == 2
    connector.release.set()
    deadline = time.monotonic() + 5
    while len(connector.made) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(connection.closed.wait(5) for connection in connector.made)
    fresh = creator()  # the slots came free when the stalled connects returned
    assert fresh is connector.made[-1] and not fresh.closed.is_set()


def test_k2_bounded_connect_releases_its_slot_on_every_outcome():
    slots = threading.BoundedSemaphore(1)
    assert bounded_connect(lambda: "connection", timeout_s=1, slots=slots) == "connection"
    with pytest.raises(KeyError):
        bounded_connect(lambda: {}["missing"], timeout_s=1, slots=slots)
    assert slots.acquire(timeout=1)  # one slot, still free after a success and a failure
    slots.release()


def test_k2_the_production_engine_uses_the_bounded_creator_and_the_horizon_counts_its_bound():
    source = (API_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")
    branch = source.split("if settings.cloud_sql_connection_name and", 1)[1].split("\nelse:", 1)[0]
    assert "get_cloud_sql_connection = cloud_sql_creator(" in branch and "creator=get_cloud_sql_connection" in branch
    assert "cloud_sql_connector.connect(" not in source  # no unbounded connect left
    defaults = inspect.signature(cloud_sql_creator).parameters
    assert defaults["timeout_s"].default == CONNECT_TIMEOUT_S == 30 and defaults["max_pending"].default == CONNECT_MAX_PENDING
    # One slot for each connection the pool can hold, overflow included.
    assert 'engine_kwargs["pool_size"] = 20' in source and 'engine_kwargs["max_overflow"] = 10' in source and 20 + 10 == CONNECT_MAX_PENDING
    # The horizon's connect term is the bound app.core.db enforces, not a library default.
    assert ledger.CONNECT_TIMEOUT_S is db_module.CONNECT_TIMEOUT_S
    ledger_source = (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8")
    assert "from app.core.db import CONNECT_TIMEOUT_S" in ledger_source and "\nCONNECT_TIMEOUT_S =" not in ledger_source
    params = ledger.ledger_params(ledger.get_config_package(Settings()))
    per_append = ledger.POOL_CHECKOUT_TIMEOUT_S + CONNECT_TIMEOUT_S + (ledger.ATTEMPT_STATEMENTS + 1) * params.ledger_append_budget_ms / 1000
    assert ledger.attempt_horizon_s(params, params.ledger_append_budget_ms) == 60 * math.ceil(
        (math.ceil(params.ledger_append_max_in_flight / params.ledger_append_workers) * per_append + ledger.HORIZON_MARGIN_S) / 60) == 360
