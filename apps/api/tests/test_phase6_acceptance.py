"""Phase 6 acceptance: V3 audit and adjudication (plan Phase 6 K AC-6-1 to AC-6-7, and its B, C, E, F, G, H, I, J and L
rows; plan 7.8 invariants 5 and 6; plan 13.6; docs/architecture/phase6-implementation-spec.md 13.1).

Every model call goes to a deterministic fake family (no network). Learner ids are uuid4 demo ids, reviewers synthetic
names. Service tests use fresh in-memory databases (v3_fakes.fresh_v3_sessions; FIXED_NOW only there); route tests
read a fresh database through a get_db override, or seed the shared database with the real clock. Security events are
read in seq order, and a test that counts denials uses a fresh event cap.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime, timedelta
from fractions import Fraction
import importlib.util
import itertools
import json
import logging
import math
from pathlib import Path
import random
import re
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import authorization as authz
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package
from app.core.db import SessionLocal, get_db
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.db_models import (
    ResponseLedgerHead,
    ResponseLedgerRecord,
    SecurityEvent,
    V3Claim,
    V3Draw,
    V3Flag,
    V3GoldLabelRecord,
    V3QueueItem,
)
from app.main import app
from app.services import security_log, v3
from app.services.ledger import verify_response_ledger
from app.services.tutor_pipeline.contracts import ENTRY_SCHEMAS
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.v2_panel.tiers import critical_for
from app.services.v3 import draw, queue
from app.services.v3.contracts import ApplyRequest, CusumAlarm
from app.services.v3.feedback import f_i
from app.services.v3.holds import released, withheld_claim_ids
from app.services.v3.metrics import slis
from app.services.v3.residual import wilson_upper
from app.services.v3.scan import run_scan, scan_until_done
from app.services.v3.stop import stop_state, tier1_withheld
from app.services.v3.triggers import ItemSpec, response_spec, x1_claims
from tutor_fakes import make_entry
from v1_fakes import dev_pipeline, run
from v2_fakes import RevisingGenerator, adapters_of, make_registry
import v3_fakes

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC_PATH = REPO_ROOT / "docs" / "architecture" / "phase6-implementation-spec.md"
SETTINGS = Settings(environment="development", v3_queue="shadow")
PACKAGE = get_config_package(SETTINGS)
TRUSTED_ORIGIN = "http://localhost:3000"
TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
NOW = v3_fakes.FIXED_NOW
client = TestClient(app)


def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _demo(role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"p6-{role}-{uuid4().hex[:10]}", "x-demo-role": role, "x-forwarded-for": f"phase6-{uuid4().hex}"}


def _guest(secret: str = DEVELOPMENT_GUEST_TOKEN_SECRET, origin: str = TRUSTED_ORIGIN) -> tuple[TestClient, dict[str, str]]:
    import time

    guest_id = f"guest-{uuid4().hex}"
    issued = int(time.time())
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(secret, guest_id, issued))
    return browser, {"origin": origin, "x-qcai-csrf": guest_csrf_for(secret, guest_id, issued)}


def _head_seq() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.max(SecurityEvent.seq))) or 0


def _events(start: int, event_type: str) -> list:
    with SessionLocal() as db:
        return db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == event_type).order_by(SecurityEvent.seq)).all()


def _ledger_rows(factory) -> list:
    with factory() as db:
        rows = [tuple(row) for row in db.execute(select(ResponseLedgerRecord.seq, ResponseLedgerRecord.entry, ResponseLedgerRecord.entry_sha256,
                                                        ResponseLedgerRecord.prev_hash, ResponseLedgerRecord.record_hash).order_by(ResponseLedgerRecord.seq))]
        head = tuple(db.execute(select(ResponseLedgerHead.seq, ResponseLedgerHead.record_hash)).first() or ())
    return rows + [head]


@pytest.fixture
def fresh_db_routes():
    """A fresh database behind every route that reads get_db (the queue routes; security events stay shared)."""
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        def override():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        try:
            yield factory
        finally:
            app.dependency_overrides.pop(get_db, None)


REVIEWER_ROUTES = [(method, path) for (method, path), policy in authz.ROUTE_POLICIES.items() if policy.access == authz.REVIEWER]


def _concrete(path: str) -> str:
    return path.replace("{item_id}", "v3i-" + "0" * 24)


# ==================================================================================================== AC-6-1


def _critical_target():
    base = dev_pipeline()
    return base, next(claim for claim in v3_fakes.critical_claims_of(base) if claim.claim_id == v3_fakes.CRITICAL_CLAIMS[0])


def test_ac_6_1_a_critical_tier_1_claim_with_one_objection_fires_x1_and_is_withheld():
    base, target = _critical_target()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    objection = {target.text: tuple(target.span_ids)}
    generator = RevisingGenerator(ExtractiveD19Generator(base.package))
    _, entry = v3_fakes.shadow_v3_record(adapters=v3_fakes.objecting_adapters(registry, "fake-beta-v1", objection), generator=generator)
    verdict = next(item for item in entry.verification.verdicts if item.claim_id == target.claim_id)
    assert (verdict.v2.critical, verdict.v2.tier, verdict.v2.objections) == (True, 1, 1)
    assert verdict.final == "abstain" and verdict.v3.escalation == "X2" and generator.revised == []   # never revised, never delivered
    assert x1_claims(entry) == {target.claim_id}
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [entry])
        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
        with factory() as db:
            item = db.execute(select(V3QueueItem.__table__).where(V3QueueItem.claim_key == target.claim_id)).first()
    assert queue.split(item.triggers) == {"X1", "X2"} and item.held is True and item.state == "queued" and item.subject == "claim"
    assert target.claim_id in withheld_claim_ids(entry)
    # The objector leaves the panel (it fails its next call): the claim's next tally passes 1oo2 in REDUCED-2, yet it stays
    # held, is listed in every correction and abstains with X2 after the last cycle.
    left = v3_fakes.objecting_adapters(registry, "fake-beta-v1", objection, fail_calls=(4,))
    _, entry = v3_fakes.shadow_v3_record(adapters=left, generator=RevisingGenerator(ExtractiveD19Generator(base.package)), cache=v3_fakes.NoCache())
    verdict = next(item for item in entry.verification.verdicts if item.claim_id == target.claim_id)
    block = entry.verification.v2
    assert (verdict.v2.mode, verdict.v2.rule, verdict.v2.outcome, verdict.v2.objections) == ("REDUCED-2", "1oo2", "pass", 0)
    assert verdict.final == "abstain" and verdict.v3.escalation == "X2" and block.cycles == 2
    assert all(target.claim_id in correction.failed_claim_ids for correction in block.corrections)
    assert x1_claims(entry) == {target.claim_id} and target.claim_id in withheld_claim_ids(entry)
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [entry])
        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
        with factory() as db:
            item = db.execute(select(V3QueueItem.__table__).where(V3QueueItem.claim_key == target.claim_id)).first()
    # Under package v6 (x-triggers-v2, Phase 7 spec conflict 3) the exhausted claim also fires X2; v5 fired X1 alone.
    expected = ("X1", "X2") if PACKAGE.v3.trigger_registry_version == "x-triggers-v2" else ("X1",)
    assert tuple(sorted(queue.split(item.triggers))) == expected and item.held is True
    # Under shadow X1 fires on the same objection; the finals are Phase 4's and no correction runs.
    shadow = Settings(model_gateway="shadow")
    _, entry = v3_fakes.shadow_v3_record(settings=shadow, adapters=v3_fakes.objecting_adapters(registry, "fake-beta-v1", objection))
    phase4 = run(dev_pipeline(), v3_fakes.CRITICAL_QUERY).entry
    assert x1_claims(entry) == {target.claim_id} and entry.verification.v2.cycles == 0
    assert [item.final for item in entry.verification.verdicts] == [item.final for item in phase4.verification.verdicts]
    # A one-objection claim of query 9 is not in the registry: no X1.
    claim9 = run(base, v3_fakes.in_domain(9)).locked.claims[0]
    assert claim9.claim_id not in v3_fakes.CRITICAL_CLAIMS
    _, entry = v3_fakes.shadow_v3_record(v3_fakes.in_domain(9), adapters=v3_fakes.objecting_adapters(
        registry, "fake-beta-v1", {claim9.text: tuple(claim9.span_ids)}))
    assert x1_claims(entry) == frozenset()
    # Outside development the registry is empty (D-25 open).
    assert critical_for(target.claim_id, PACKAGE, environment="development") is True
    assert critical_for(target.claim_id, PACKAGE, environment=Settings(environment="staging", guest_token_secret="s" * 32).environment) is False


def test_ac_6_1_the_development_critical_registry_lists_claims_the_pipeline_locks_at_tier_1():
    registry = PACKAGE.raw["v3"]["critical_claims"]["registries"]
    entries = registry["development"]["claims"]
    assert registry["development"]["synthetic"] is True and entries
    assert all(not registry[name]["claims"] for name in ("staging", "production", "default"))
    for index in sorted({entry["query_index"] for entry in entries}):
        wanted = {entry["claim_id"] for entry in entries if entry["query_index"] == index}
        locked = {claim.claim_id for claim in run(dev_pipeline(), v3_fakes.in_domain(index)).locked.claims}
        assert wanted <= locked, index
        _, record = v3_fakes.shadow_v3_record(v3_fakes.in_domain(index))
        tiers = {item.claim_id: (item.v2.tier, item.v2.critical) for item in record.verification.verdicts if item.v2 is not None}
        assert all(tiers[claim_id] == (1, True) for claim_id in wanted), tiers


# ==================================================================================================== AC-6-2


def test_ac_6_2_one_thousand_synthetic_deliveries_draw_33_to_69_and_a_same_seed_replay_draws_identical_ids():
    ids = [v3_fakes.synthetic_id(index) for index in range(1, 1001)]
    rate, x5 = PACKAGE.v3.draw_rate, PACKAGE.v3.x5_rate
    pure = {key for key in ids if draw.draw_trigger(PACKAGE.v3.draw_seed, key, base=rate, elevated=x5, x5_active=False) == "X6"}
    assert len(pure) == 47 and 33 <= len(pure) <= 69
    drawn_sets = []
    for _ in range(2):
        with v3_fakes.fresh_v3_sessions() as (factory, _engine):
            v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(1000))
            scan_until_done(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
            again = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
            with factory() as db:
                considered = db.scalar(select(func.count()).select_from(V3Draw))
                items = db.execute(select(ResponseLedgerRecord.response_id, V3QueueItem.triggers)
                                   .join(V3QueueItem, V3QueueItem.ledger_seq == ResponseLedgerRecord.seq)).all()
        assert considered == 1000 and again.records == 0 and again.items_created == 0
        assert all(queue.split(triggers) == {"X6"} for _, triggers in items)
        drawn_sets.append({response_id for response_id, _ in items})
    assert drawn_sets[0] == drawn_sets[1] == pure
    other = {key for key in ids if draw.draw_trigger("another-seed", key, base=rate, elevated=x5, x5_active=False) == "X6"}
    assert other != pure


# ==================================================================================================== AC-6-3


def test_ac_6_3_the_higher_severity_times_exposure_times_one_minus_k_ranks_first(fresh_db_routes):
    factory = fresh_db_routes
    first, second = v3_fakes.synthetic_deliveries(2)
    v3_fakes.append_all(factory, [first, second, make_entry(delivery="shadow")])
    run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)

    def spec(claim_key, subject, types, k):
        return ItemSpec(claim_key=claim_key, subject=subject, triggers=frozenset({"X6"} if subject == "response" else {"X2"}),
                        reasons=frozenset(), ehmf_types=frozenset(types), k=k, held=False)

    with factory() as db:
        specs = {"P": (2, spec("", "response", {"C"}, Fraction(0))), "Q": (3, spec("claim-" + "a" * 32, "claim", {"A"}, Fraction(0))),
                 "S": (3, spec("claim-" + "b" * 32, "claim", {"A"}, Fraction(2, 3)))}
        ids = {}
        for name, (seq, item) in specs.items():
            row = queue.record_row(db, seq)
            ids[name] = queue.upsert_item(db, record_row=row, spec=item, entry=queue.parse_entry(row), package=PACKAGE, now=NOW)[0]
        db.commit()
        stored = {name: queue.get_item(db, item_id) for name, item_id in ids.items()}
        listed = [row.item_id for row in queue.list_queue(db, limit=100, now=NOW, item_ids=ids.values())]
    assert {name: (row.severity, row.exposure, row.k, row.priority) for name, row in stored.items()} == {
        "P": (0.6, 2, 0.0, 1.2), "Q": (1.0, 1, 0.0, 1.0), "S": (1.0, 1, float(Fraction(2, 3)), float(Fraction(1, 3)))}
    assert listed == [ids["P"], ids["Q"], ids["S"]]
    # Severity alone would rank Q and S first; (1 - K) alone would tie P and Q.
    assert sorted("PQS", key=lambda name: -stored[name].severity) == ["Q", "S", "P"] and stored["P"].k == stored["Q"].k
    routed = client.get("/v3/queue?limit=100", headers=v3_fakes.reviewer("a")).json()["items"]
    assert [item["item_id"] for item in routed if item["item_id"] in ids.values()] == [ids["P"], ids["Q"], ids["S"]]
    assert all({"priority", "severity", "exposure", "k"}.isdisjoint(item) for item in routed)


# ==================================================================================================== AC-6-4


def test_ac_6_4_an_adjudication_appends_one_gold_row_and_changes_no_ledger_row():
    from app.services.v3.gold import verify_gold_store

    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(2)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=False)
        before = _ledger_rows(factory)
        request = v3_fakes.supported_labels(entries[0])
        with factory() as db:
            queue.claim_item(db, ids[0], user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            gold_before = db.scalar(select(func.count()).select_from(V3GoldLabelRecord))
            result = queue.adjudicate(db, ids[0], request("ac64-key-1"), user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == gold_before + 1
            from app.services.v3.contracts import GoldLabel

            entry = json.loads(db.scalar(select(V3GoldLabelRecord.entry).where(V3GoldLabelRecord.seq == result.gold_seq)))
            assert GoldLabel.model_validate(entry).item_id == ids[0] and verify_gold_store(db).ok
        assert _ledger_rows(factory) == before
        with factory() as db:
            assert verify_response_ledger(db).ok
            duplicate = queue.adjudicate(db, ids[0], request("ac64-key-1"), user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            assert (duplicate.gold_seq, duplicate.duplicate) == (result.gold_seq, True)
            with pytest.raises(queue.V3Conflict):
                queue.adjudicate(db, ids[0], request("ac64-key-2"), user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            head = db.execute(select(V3GoldLabelRecord.seq, V3GoldLabelRecord.record_hash).order_by(V3GoldLabelRecord.seq.desc())).first()
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(insert(V3GoldLabelRecord).values(seq=head.seq + 1, item_id=ids[0], review_round=1, actor_role="reviewer", action="adjudicate",
                                                            reviewer_digest="0" * 32, entry="{}", entry_sha256="0" * 64, prev_hash=head.record_hash,
                                                            record_hash="1" * 64, created_at=NOW))
                db.commit()
            db.rollback()
            queue.apply_item(db, ids[0], ApplyRequest(client_key="ac64-apply"), user_id="synthetic-reviewer-b", now=NOW)
            assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == gold_before + 1
        assert _ledger_rows(factory) == before


def test_plan_h_the_v3_export_and_residual_report_paths_leave_the_repository_tree_unchanged(residual_report, tmp_path, monkeypatch):
    # Plan L627-628: gold labels "MUST NOT enter the public repository". The residual report's in-process run (the module
    # fixture) and the gold export, through the service and the worker command, write only to their target outside the
    # checkout: the repository tree is the same before and after, and an export aimed at the checkout is refused (exit 2)
    # and writes nothing.
    from app.services.v3.gold import export_gold
    from app.workers import v3_queue as worker

    assert RESIDUAL_RUN_TREES and v3_fakes.tree_changes(RESIDUAL_RUN_TREES["before"], RESIDUAL_RUN_TREES["after"]) == []
    before = v3_fakes.repository_tree()
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(1)
        (item_id,) = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=False)
        with factory() as db:
            queue.claim_item(db, item_id, user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            queue.adjudicate(db, item_id, v3_fakes.supported_labels(entries[0])("hygiene-key-1"), user_id="synthetic-reviewer-a", now=NOW,
                             package=PACKAGE)
            queue.apply_item(db, item_id, ApplyRequest(client_key="hygiene-apply"), user_id="synthetic-reviewer-b", now=NOW)
            assert export_gold(db, tmp_path / "applied.jsonl") == 1 and export_gold(db, tmp_path / "all.jsonl", applied_only=False) == 1
        monkeypatch.setattr(worker, "SessionLocal", factory)
        assert worker.main(["export-gold", "--path", str(tmp_path / "worker.jsonl"), "--all"]) == 0
        targets = (v3_fakes.REPOSITORY / "gold.jsonl", v3_fakes.REPOSITORY / "docs" / "evaluation" / "phase6" / "gold.jsonl")
        try:
            for target in targets:
                assert worker.main(["export-gold", "--path", str(target), "--all"]) == 2 and not target.exists(), target
        finally:                                    # an export that was let through never stays in the checkout
            for target in targets:
                target.unlink(missing_ok=True)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["all.jsonl", "applied.jsonl", "worker.jsonl"]
    assert v3_fakes.tree_changes(before, v3_fakes.repository_tree()) == []


# ==================================================================================================== AC-6-5


def _residual_module():
    spec = importlib.util.spec_from_file_location("run_v3_residual_report", REPO_ROOT / "scripts" / "run_v3_residual_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESIDUAL_RUN_TREES: dict = {}


@pytest.fixture(scope="module")
def residual_report():
    module = _residual_module()
    before = v3_fakes.repository_tree()
    report = module.run(commit_source=lambda: "test")
    RESIDUAL_RUN_TREES.update(before=before, after=v3_fakes.repository_tree())   # read by the checkout-hygiene test
    return module, report


def test_ac_6_5_zero_errors_in_300_audited_items_bound_the_residual_below_1_3_percent(residual_report):
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from evaluation.qcai_eval.statistics import wilson_interval as harness
    finally:
        sys.path.remove(str(REPO_ROOT))
    z = 1.959963984540054
    assert wilson_upper(0, 300) == harness(0, 300)["upper"] == 0.012642971224546034 and wilson_upper(0, 300) < 0.013
    assert math.isclose(wilson_upper(0, 300), z * z / (300 + z * z), rel_tol=1e-12)
    assert (wilson_upper(1, 300), wilson_upper(3, 300)) == (0.018636693694531237, 0.02898349336233983)
    _, report = residual_report
    residual = report["residual"]
    assert (residual["audited_answers"], residual["errors"], residual["pass"]) == (300, 0, True) and residual["wilson95"]["upper"] < 0.013
    assert report["harness_equal"] is True and report["draw"]["x6"] == 300 and report["result"] == "pass"


# ==================================================================================================== AC-6-6


def _entry_schema_properties() -> set[str]:
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in (node.get("properties") or {}).items():
                names.add(key)
                walk(value)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for model in ENTRY_SCHEMAS.values():
        walk(model.model_json_schema())
    return names


def test_ac_6_6_a_learner_flag_sets_f_i_to_zero_and_changes_no_verdict_or_ledger_row():
    learner = _demo()
    turn_id = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=learner).json()["turn_id"]
    with SessionLocal() as db:
        legacy = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.response_id == turn_id)).first()
        shadow = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.shadowed_response_id == turn_id)).first()
        count = db.scalar(select(func.count()).select_from(ResponseLedgerRecord))
    assert legacy is not None and shadow is not None and shadow.entry_schema == "ledger-entry-v4"  # typed since Phase 7 (a v3 subclass)
    response = client.post("/v3/flags", json={"response_id": turn_id}, headers=learner)
    assert response.status_code == 200 and response.json() == {"status": "recorded", "f_i": 0.0, "duplicate": False}
    with SessionLocal() as db:
        assert f_i(db, legacy.seq) == 0.0 and f_i(db, shadow.seq) is None
        item = db.execute(select(V3QueueItem.__table__).where(V3QueueItem.ledger_seq == legacy.seq, V3QueueItem.claim_key == "")).first()
        assert "X3" in queue.split(item.triggers) and item.subject == "response"
        for before in (legacy, shadow):
            after = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.seq == before.seq)).first()
            assert tuple(after) == tuple(before)
        assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord)) == count
    verdicts = json.loads(shadow.entry)["verification"]["verdicts"]
    assert all({"v1", "v2", "final", "v3"} <= set(verdict) for verdict in verdicts)
    assert client.post("/v3/flags", json={"response_id": turn_id}, headers=learner).json()["duplicate"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(V3Flag).where(V3Flag.ledger_seq == legacy.seq)) == 1
    assert client.post("/v3/flags", json={"response_id": turn_id}, headers=_demo()).status_code == 404
    # Invariant 5's schema test: no ledger schema holds a learner rating or flag; the one rating is the verifier's.
    properties = _entry_schema_properties()
    assert not properties & {"f_i", "feedback", "flag", "flags", "learner_flag", "learner_rating"}
    assert "rating" in properties and "rating" in ENTRY_SCHEMAS["ledger-entry-v3"].model_json_schema()["$defs"]["AlignmentVote"]["properties"]
    assert {name for name in properties if "rating" in name} == {"rating"}


# ==================================================================================================== AC-6-7


@pytest.mark.parametrize("environment,setting", [("development", "shadow"), ("development", "off"), ("staging", "off"), ("staging", "shadow")])
def test_ac_6_7_a_guest_on_every_reviewer_route_gets_403_and_one_access_log_entry(environment, setting, monkeypatch):
    # The role check comes first in every environment: outside development too, where no reviewer is admitted (D-18), a
    # guest's refusal names the role, never the pool.
    from app import main as main_module

    monkeypatch.setattr(security_log, "_caps", security_log._Caps())
    if environment == "development":
        configured, secret, origin = Settings(environment="development", v3_queue=setting), DEVELOPMENT_GUEST_TOKEN_SECRET, TRUSTED_ORIGIN
    else:
        configured = v3_fakes.staging_settings(v3_queue=setting)
        secret, origin = configured.guest_token_secret, configured.allowed_origins[0]
        monkeypatch.setattr(main_module, "settings", configured)       # the CSRF and origin guard reads the process settings
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        assert len(REVIEWER_ROUTES) == 7
        for method, path in REVIEWER_ROUTES:
            browser, headers = _guest(secret, origin)
            start = _head_seq()
            response = browser.request(method, _concrete(path), headers=headers, json={} if method == "POST" else None)
            assert response.status_code == 403, (path, response.text)
            denials = _events(start, "authz.denied")
            assert [event.details for event in denials] == [{"route": path, "required": "role:reviewer", "provider": "guest"}], path
            assert _events(start, "request.forbidden") == []
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ======================================================================================= plan J, L, B, H, G, I


def _withheld_records():
    base, target = _critical_target()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    _, x1 = v3_fakes.shadow_v3_record(adapters=v3_fakes.objecting_adapters(registry, "fake-beta-v1", {target.text: tuple(target.span_ids)}),
                                      generator=RevisingGenerator(ExtractiveD19Generator(base.package)))
    down = adapters_of(registry, **{spec.adapter_id: {"down": True} for spec in registry.members})
    _, zero = v3_fakes.shadow_v3_record(adapters=down)
    assert any(verdict.final == "withhold" and "v2_degraded_withheld" in verdict.v3.reasons for verdict in zero.verification.verdicts)
    return target, x1, zero


def test_plan_j_with_no_reviewer_every_item_stays_withheld_and_queued():
    target, x1, zero = _withheld_records()
    held_before = (withheld_claim_ids(x1), withheld_claim_ids(zero))
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [x1, zero])
        before = _ledger_rows(factory)
        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
        later = NOW + timedelta(days=30)
        with factory() as db:
            items = db.execute(select(V3QueueItem.__table__)).all()
            assert items and all(queue.workflow_state(db, item, now=later) == "queued" for item in items)
            assert any(item.claim_key == target.claim_id and item.held for item in items)
            assert any("v2_degraded_withheld" in queue.split(item.reasons) for item in items)
            assert stop_state(db, PACKAGE, now=later).active is True
        assert _ledger_rows(factory) == before
    assert (withheld_claim_ids(x1), withheld_claim_ids(zero)) == held_before and all(held_before)
    assert released(None) is False


def test_plan_l_disabling_v3_releases_no_withheld_item(monkeypatch):
    off = Settings(environment="development", v3_queue="off")
    target, x1, _ = _withheld_records()
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [x1, *v3_fakes.reviewable_deliveries(1)])
        old = datetime.now(UTC) - timedelta(days=30)
        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=old)
        with factory() as db:
            row = queue.record_row(db, 2)
            queue.upsert_item(db, record_row=row, spec=response_spec(queue.parse_entry(row), "X3"), entry=queue.parse_entry(row), package=PACKAGE, now=old)
            db.commit()
            snapshot = sorted(tuple(item) for item in db.execute(select(V3QueueItem.__table__)))
        with pytest.raises(v3.V3Off):
            run_scan(settings=off, package=PACKAGE, session_factory=factory)
        with factory() as db:
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text("DELETE FROM v3_queue_items"))
                db.commit()
            db.rollback()
            assert sorted(tuple(item) for item in db.execute(select(V3QueueItem.__table__))) == snapshot
            assert f_i(db, 2) == 0.0
        assert target.claim_id in withheld_claim_ids(x1)
        # The stop is computed from the stored queue whatever the mode, and reaches a tier-1 V2 run over that database.
        assert tier1_withheld(off, PACKAGE, session_factory=factory) is True
        from v2_fakes import fresh_gateway, v2_pipeline

        pipeline = v2_pipeline(gateway=fresh_gateway(), registry=make_registry(("fake-alpha", "fake-beta", "fake-gamma")), session_factory=factory)
        stopped = run(pipeline, v3_fakes.CRITICAL_QUERY).entry
        assert stopped.verification.v2.kill_switch == "pre_verified_only" and stopped.verification.v2.calls == 0
        app.dependency_overrides[get_settings] = lambda: off
        try:
            for method, path in REVIEWER_ROUTES:
                body = {"client_key": "off-key-0001"} if method == "POST" else None
                response = client.request(method, _concrete(path), headers=v3_fakes.reviewer("a"), json=body)
                assert (response.status_code, response.headers.get("cache-control")) == (404, "no-store"), path
            assert client.post("/v3/flags", headers=_demo(), json={"response_id": f"turn-{uuid4()}"}).status_code == 404
        finally:
            app.dependency_overrides.pop(get_settings, None)
        # Re-enabling shows the same items, still held.
        with factory() as db:
            assert sorted(tuple(item) for item in db.execute(select(V3QueueItem.__table__))) == snapshot


def test_plan_l_queue_age_above_the_slo_for_two_days_withholds_tier_1(caplog):
    slo, hour = timedelta(seconds=PACKAGE.v3.queue_age_slo_s), timedelta(hours=1)

    def item(db, index, enqueued, closed=None):
        db.execute(insert(V3QueueItem).values(
            item_id=queue.item_id_for(index, ""), ledger_seq=index, claim_key="", subject="response", record_kind="delivery",
            response_digest="d" * 32, triggers="X6", reasons="", ehmf_types="", held=False, severity=1.0, exposure=1, k=0.0, priority=1.0,
            state="adjudicated" if closed else "queued", review_round=1, double_review=False, enqueued_at=enqueued, closed_at=closed,
            package_version="5.0.0", package_sha256="x"))

    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            item(db, 1, NOW - (slo + 49 * hour))
            db.commit()
            assert stop_state(db, PACKAGE, now=NOW).active is True
            db.execute(text("UPDATE v3_queue_items SET state = 'adjudicated', closed_at = :at"), {"at": NOW - hour / 2})
            db.commit()
            assert stop_state(db, PACKAGE, now=NOW).active is False
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            item(db, 1, NOW - (slo + 47 * hour))
            db.commit()
            assert stop_state(db, PACKAGE, now=NOW).active is False   # above the SLO for 47 hours only
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            item(db, 1, NOW - (slo + 50 * hour))
            for index in range(2, 50):
                item(db, index, NOW - 40 * hour)
            db.commit()
            assert stop_state(db, PACKAGE, now=NOW).active is True   # the oldest item: many young ones cannot dilute it
            assert slis(db, PACKAGE, now=NOW)["queue"]["age_p90_s"] < PACKAGE.v3.queue_age_slo_s

    def unreadable():
        raise RuntimeError("the queue cannot be read")

    caplog.set_level(logging.INFO)
    assert tier1_withheld(SETTINGS, PACKAGE, session_factory=unreadable) is True
    assert any("could not be read" in record.getMessage() for record in caplog.records)
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = adapters_of(registry)
    _, entry = v3_fakes.shadow_v3_record(adapters=adapters, v3_stop=lambda: True)
    block = entry.verification
    assert block.v2.kill_switch == "pre_verified_only" and block.v2.calls == 0 and block.final == "abstain"
    assert block.final_reason == "v2_kill_switch" and all(adapter.calls == 0 for adapter in adapters.values())
    assert block.v2.members == ()
    assert all(item.v2.outcome == "withheld" and item.v2.mode == "ZERO" for item in block.verdicts if item.v2 is not None)
    assert any("tier 1 runs pre-verified-only" in record.getMessage() for record in caplog.records)
    _, tier2 = v3_fakes.shadow_v3_record(TIER2, adapters=adapters_of(registry), v3_stop=lambda: True)
    assert tier2.verification.v2.kill_switch == "none" and tier2.verification.v2.calls > 0
    shadow = Settings(model_gateway="shadow")
    _, stopped = v3_fakes.shadow_v3_record(settings=shadow, adapters=adapters_of(registry), v3_stop=lambda: True)
    phase4 = run(dev_pipeline(), v3_fakes.CRITICAL_QUERY).entry
    assert [item.final for item in stopped.verification.verdicts] == [item.final for item in phase4.verification.verdicts]
    assert stopped.verification.v2.kill_switch == "pre_verified_only" and stopped.verification.v2.calls == 0


def _startup(extra: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {key: value for key, value in os.environ.items() if key not in {"V3_QUEUE", "CONFIG_PACKAGE_PATH", "ENFORCE_CORPUS_GOVERNANCE", "MODEL_GATEWAY"}}
    env.update({"PYTHONUNBUFFERED": "1", **extra})
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"], cwd=API_ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


def test_plan_l_v3_queue_defaults_and_refusals(monkeypatch, fresh_database_url):
    from app import main as main_module

    production = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"]}
    assert Settings().v3_queue == "shadow" and Settings(**production).v3_queue == "off"
    with pytest.raises(ValidationError, match="phase6_exit_passed"):
        Settings(**production, v3_queue="on")
    assert Settings(v3_queue="on").v3_queue == "on"   # development
    exited = dataclasses.replace(PACKAGE, flag_policy=dataclasses.replace(PACKAGE.flag_policy, phase6_exit_passed=True, phase6_exit_evidence="x"))
    monkeypatch.setattr("app.core.config_package.get_config_package", lambda settings=None: exited)
    allowed = Settings(**production, v3_queue="on")
    assert allowed.v3_queue == "on"
    for setting, key in (("on", "v3_queue_on"), ("shadow", "v3_queue_shadow")):
        recorded = []
        monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(main_module, "settings", Settings(**production, v3_queue=setting))
        monkeypatch.setattr(main_module, "get_config_package", lambda _settings=None: exited)
        monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append(kwargs["details"]))
        main_module._record_configuration_overrides()
        assert recorded and recorded[0].get(key) is True, setting
    monkeypatch.undo()
    # A v3 package problem stops a governed start-up only when V3 is requested; otherwise V3 is unavailable and off.
    broken = dataclasses.replace(PACKAGE, v3=dataclasses.replace(PACKAGE.v3, draw_rule="float-v1"))
    for requested, stops in (("shadow", True), ("off", False)):
        monkeypatch.setattr(main_module, "settings", Settings(enforce_corpus_governance=True, v3_queue=requested))
        try:
            if stops:
                with pytest.raises(ConfigPackageError, match="v3: "):
                    main_module._check_v3_package(broken)
            else:
                main_module._check_v3_package(broken)
                assert v3.V3_UNAVAILABLE_REASON is not None and main_module._v3_fields(PACKAGE)["available"] is False
                assert v3.mode(Settings(), PACKAGE) == "off"
        finally:
            v3.V3_UNAVAILABLE_REASON = None
    completed = _startup({"DATABASE_URL": fresh_database_url, "ENVIRONMENT": "production", "V3_QUEUE": "on",
                          "ALLOWED_ORIGINS": "https://qantumlearn.academy", "GUEST_TOKEN_SECRET": "a-production-like-secret-of-sufficient-length"})
    assert completed.returncode != 0 and "V3_QUEUE=on" in completed.stderr, completed.stderr[-500:]


def test_plan_b_no_reviewer_is_admitted_outside_development_while_d_18_is_open(monkeypatch):
    from app.api.routes import ledger as ledger_routes
    from app.core.reviewer_access import reviewer_admitted

    staging = v3_fakes.staging_settings(ledger_route_enabled=True)
    assert reviewer_admitted(staging) is False and reviewer_admitted(SETTINGS) is True
    owner = _demo()
    turn_id = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=owner).json()["turn_id"]
    with SessionLocal() as db:
        shadow_id = db.scalar(select(ResponseLedgerRecord.response_id).where(ResponseLedgerRecord.shadowed_response_id == turn_id))
    monkeypatch.setattr(security_log, "_caps", security_log._Caps())
    app.dependency_overrides[get_settings] = lambda: staging
    monkeypatch.setattr(ledger_routes, "get_settings", lambda: staging)
    try:
        for method, path in REVIEWER_ROUTES:
            start = _head_seq()
            response = client.request(method, _concrete(path), headers=v3_fakes.reviewer("a"), json={} if method == "POST" else None)
            assert (response.status_code, response.json()["detail"]) == (403, "No reviewer is admitted outside development while the reviewer pool "
                                                                             "(D-18) is unstaffed."), path
            assert [event.details["required"] for event in _events(start, "authz.denied")] == ["reviewer_pool:D-18"], path
        start = _head_seq()
        missing = client.get(f"/ledger/responses/turn-{uuid4()}", headers=v3_fakes.reviewer("a"))
        for response_id in (turn_id, shadow_id):
            read = client.get(f"/ledger/responses/{response_id}", headers=v3_fakes.reviewer("a"))
            assert (read.status_code, read.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Response not found."})
        assert _events(start, "ledger.reviewer_read") == []
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_plan_h_reviewers_see_public_quotable_spans_only_and_no_learner_identifier(fresh_db_routes, monkeypatch):
    from types import SimpleNamespace

    from app.api.routes import v3 as routes
    from app.core.corpus_governance import get_corpus_registry
    from app.services.content_assembler import CourseStore
    from app.services.v3.queue import span_shown

    factory = fresh_db_routes
    entries = v3_fakes.reviewable_deliveries(2)
    ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=datetime.now(UTC))
    reviewer = v3_fakes.reviewer("a")
    payloads = [client.get("/v3/queue", headers=reviewer).json()] + [client.get(f"/v3/items/{item_id}", headers=reviewer).json() for item_id in ids]
    flat = json.dumps(payloads)
    assert all(item["reviewable"] and all(claim["text"] for claim in item["claims"]) for item in payloads[1:])
    forbidden = [r"turn-[0-9a-f]{8}-", r"shadow-[0-9a-f]{8}-", r"qa-[0-9a-f]{8}-", r"thread-", r"message-", r"\bp6-", r"@", r"synthetic-a"]
    assert not [pattern for pattern in forbidden if re.search(pattern, flat)], flat[:300]
    keys = set(payloads[0])
    for payload in payloads[0]["items"] + payloads[1:]:          # the queue's items and each item read
        keys |= set(payload)
    assert len(payloads[0]["items"]) == 2
    assert not keys & {"ledger_seq", "severity", "exposure", "k", "priority", "votes", "objection_types", "final", "user_id", "response_id",
                       "support_share", "claim_labels"}
    # Over a governed store (D-31: no asset approved) no span is shown, so no item is reviewable.
    governed = Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"])
    store, registry = CourseStore(governed), get_corpus_registry(governed)
    monkeypatch.setattr(routes, "_sources", lambda settings: (store, registry))
    hidden = client.get(f"/v3/items/{ids[0]}", headers=reviewer).json()
    assert hidden["reviewable"] is False and all(not span["shown"] and span["text"] is None for claim in hidden["claims"] for span in claim["spans"])
    assert all(claim["text"] is None for claim in hidden["claims"])
    refused = client.post(f"/v3/items/{ids[0]}/claim", headers=reviewer)
    assert (refused.status_code, refused.json()) == (409, {"detail": "not_reviewable"})
    # A span record outside the public plane is never shown.
    text_, span_id = v3_fakes.quotable_claim()
    private = SimpleNamespace(span_registry={span_id: SimpleNamespace(plane="private_eval", item_kind="document", source_filename="x.docx", text=text_)})
    assert span_shown(span_id, store=private, corpus_registry=registry) == (False, None)
    # The import rule (spec 7.1).
    banned = ("app.services.learner_record", "app.services.learner_progress", "app.services.learning_intelligence", "app.services.microlearning",
              "app.core.auth", "app.api.routes", "app.services.answer_history", "app.services.retrieval_legacy_p1")
    for path in sorted((API_ROOT / "app" / "services" / "v3").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert not [name for name in names if name.startswith(banned)], path.name
        if path.name in ("stop.py", "triggers.py"):
            top = {node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.module}
            assert not [name for name in top if name.startswith(("app.services.v2_panel", "app.gateway"))], path.name


V3_TABLES = {"v3_queue_items", "v3_claims", "v3_draws", "v3_gold_labels", "v3_events", "v3_model_versions", "v3_flags", "v3_scans"}
PHASE5_REVISION, PHASE6_REVISION = "20261122_phase5_gateway_controls", "20261122_phase6_v3_audit"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=240)


def test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows(fresh_database_url):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    from sqlalchemy import inspect as sa_inspect

    from app.core.db import Base
    from app.services.ledger import SCHEMA_REVISION
    from test_response_ledger_migrations import PHASE7_REVISION, PHASE7_TABLES, PHASE8_TABLES

    scripts = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    assert scripts.get_heads() == [SCHEMA_REVISION]
    assert scripts.get_revision(SCHEMA_REVISION).down_revision == PHASE7_REVISION
    assert scripts.get_revision(PHASE7_REVISION).down_revision == PHASE6_REVISION
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        Base.metadata.drop_all(engine, tables=[Base.metadata.tables[name] for name in V3_TABLES | PHASE7_TABLES | PHASE8_TABLES])
        others = set(sa_inspect(engine).get_table_names())
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", PHASE5_REVISION).returncode == 0
        upgraded = _alembic(fresh_database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        checked = _alembic(fresh_database_url, "check")
        assert checked.returncode == 0 and "No new upgrade operations detected" in (checked.stdout + checked.stderr), checked.stderr[-2000:]
        assert V3_TABLES <= set(sa_inspect(engine).get_table_names())
        engine.dispose()
        downgraded = _alembic(fresh_database_url, "downgrade", PHASE7_REVISION)
        assert downgraded.returncode == 0, downgraded.stderr[-2000:]
        tables = set(sa_inspect(engine).get_table_names())
        assert not PHASE8_TABLES & tables and PHASE7_TABLES <= tables
        engine.dispose()
        # A CUSUM alarm (from outside the ledger) keeps the tables too; a model_change event (derived from the records and
        # the registry) is not counted: one of each gives "1 cusum_alarm rows".
        events = ("INSERT INTO v3_events (kind, payload, from_ledger_seq, window_deliveries, created_at) "
                  "VALUES ('model_change', '{}', 0, 1500, CURRENT_TIMESTAMP), ('cusum_alarm', '{}', 0, 1500, CURRENT_TIMESTAMP)")
        for table, statement in (("v3_events", events),
                                 ("v3_flags", "INSERT INTO v3_flags (user_id, ledger_seq, created_at) VALUES ('guest-synthetic', 1, CURRENT_TIMESTAMP)"),
                                 ("v3_queue_items", None), ("v3_gold_labels", None)):
            with engine.begin() as connection:
                if statement:
                    connection.exec_driver_sql(statement)
                elif table == "v3_queue_items":
                    connection.execute(insert(V3QueueItem).values(
                        item_id="v3i-" + "f" * 24, ledger_seq=1, claim_key="", subject="response", record_kind="delivery", response_digest="d" * 32,
                        triggers="X6", reasons="", ehmf_types="", held=False, severity=1.0, exposure=1, k=0.0, priority=1.0, state="queued",
                        review_round=1, double_review=False, enqueued_at=NOW, package_version="5.0.0", package_sha256="x"))
                else:
                    connection.execute(insert(V3GoldLabelRecord).values(
                        seq=1, item_id="v3i-" + "f" * 24, review_round=1, actor_role="reviewer", action="adjudicate", reviewer_digest="0" * 32,
                        entry="{}", entry_sha256="0" * 64, prev_hash="0" * 64, record_hash="0" * 64, created_at=NOW))
            engine.dispose()
            refused = _alembic(fresh_database_url, "downgrade", PHASE5_REVISION)
            named = "v3_events holds 1 cusum_alarm rows" if table == "v3_events" else f"{table} holds 1 rows"
            assert refused.returncode != 0 and "export first" in refused.stderr and named in refused.stderr, refused.stderr[-800:]
            assert "allow_v3_drop=true" in refused.stderr and "export-gold --all" in refused.stderr
        dropped = _alembic(fresh_database_url, "-x", "allow_v3_drop=true", "downgrade", PHASE5_REVISION)
        assert dropped.returncode == 0, dropped.stderr[-2000:]
        remaining = set(sa_inspect(engine).get_table_names()) - {"alembic_version"}
        assert not remaining & V3_TABLES and remaining == others - {"alembic_version"}
    finally:
        engine.dispose()


def test_plan_g_pre_ledger_deliveries_are_reported_as_non_auditable():
    from app.db_models import QAInteraction, TutorThread, TutorTurn
    from app.services.v3.metrics import non_auditable

    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            db.execute(insert(QAInteraction).values(user_id="guest-synthetic", lesson_slug=None, question="q", answer="a", citations=[],
                                                    created_at=NOW - timedelta(days=3)))
            db.add(TutorThread(id="thread-synthetic", user_id="guest-synthetic", title="t"))
            db.flush()
            db.add(TutorTurn(id=f"turn-{uuid4()}", thread_id="thread-synthetic", user_id="guest-synthetic", resolved_query="q", retrieval_mode="lexical",
                             provider="p", model="m", decision="answer", decision_reason="r", citations=[], claims=[], corpus_version="c",
                             policy_version="p", ledger_record_expected=None))
            db.commit()
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(3), now=NOW)
        scan_until_done(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
        with factory() as db:
            counts = non_auditable(db)
            considered = db.scalar(select(func.count()).select_from(V3Draw))
            body = slis(db, PACKAGE, now=NOW)
    assert counts == {"tutor_turns": 1, "qa_before_ledger": 1, "ledger_disabled": 0, "lost_records": 0, "pending": 0} and considered == 3
    assert body["draws"]["non_auditable"] == counts


def test_plan_i_ready_reports_package_v5_and_the_v3_fields_and_no_count():
    from sqlalchemy import event

    from app import main as main_module
    from app.core.db import engine

    body = client.get("/ready").json()
    assert body["config_package_version"] == PACKAGE.package_version and body["v3_queue"] == "shadow" and body["v3_queue_setting"] == "shadow"
    assert body["phase6_exit_passed"] is False
    fields = body["v3"]
    assert fields == {
        "version": "v3-audit-v1", "trigger_registry": PACKAGE.v3.trigger_registry_version, "triggers": ["X1", "X2", "X3", "X4", "X5", "X6"],
        "draw": {"rule": "seeded-sha256-bernoulli-v1", "rate": "1/20", "x5_rate": "1/5", "x5_window_deliveries": 1500}, "double_review": "1/10",
        "queue_age_slo_s": 259200, "stop_window_s": 172800, "stop_measure": "oldest_open_item_age",
        "critical_registry": {"environment": "development", "entries": 3}, "reviewer_pool": "unstaffed", "gold_schema": "v3-gold-label-v1",
        "provisional": True, "available": True}
    assert not set(fields) & {"count", "open", "depth", "seed", "head", "stop"} and "qcai-x6-v1" not in json.dumps(body)
    before = main_module._build_fields()
    learner = _demo()
    turn_id = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=learner).json()["turn_id"]
    client.post("/v3/flags", json={"response_id": turn_id}, headers=learner)
    client.post("/v3/scan", headers=v3_fakes.reviewer("a"))
    statements: list[str] = []

    def seen(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", seen)
    try:
        after = main_module._build_fields()
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    assert after == before
    assert all(statement.startswith("SELECT gateway_stops.reason FROM gateway_stops") for statement in statements), statements
    staging = v3_fakes.staging_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main_module, "settings", staging)
        assert main_module._v3_fields(PACKAGE)["critical_registry"] == {"environment": "staging", "entries": 0}
        assert main_module._v3_mode(PACKAGE) == "off"


def test_plan_i_v3_slis_report_the_escalation_share_queue_age_draws_agreement_and_residual():
    base, target = _critical_target()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    _, x1 = v3_fakes.shadow_v3_record(adapters=v3_fakes.objecting_adapters(registry, "fake-beta-v1", {target.text: tuple(target.span_ids)}),
                                      generator=RevisingGenerator(ExtractiveD19Generator(base.package)))
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        deliveries = v3_fakes.reviewable_deliveries(40)
        # The shadow record shadows delivery 3, so its X1 item counts on that delivery's seq.
        shadow = x1.model_copy(update={"shadowed_response_id": deliveries[2].response_id})
        v3_fakes.append_all(factory, deliveries[:5], now=NOW - timedelta(hours=10))
        v3_fakes.append_all(factory, [shadow], now=NOW - timedelta(hours=10))
        v3_fakes.append_all(factory, deliveries[5:], now=NOW - timedelta(hours=9))
        # An abstention delivery the draw left undrawn (asserted below); it gets an X6 item by hand.
        abstention = v3_fakes.synthetic_deliveries(1, start=950, decision="abstain")[0]
        v3_fakes.append_all(factory, [abstention], now=NOW - timedelta(hours=9))
        scan_until_done(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW - timedelta(hours=8))
        with factory() as db:
            x6_items = [row.item_id for row in db.execute(select(V3QueueItem.item_id, V3QueueItem.triggers)) if "X6" in queue.split(row.triggers)]
            # One counted X3 item on delivery 1, and the X1 item of the shadow record on delivery 3.
            row = queue.record_row(db, 1)
            queue.upsert_item(db, record_row=row, spec=response_spec(queue.parse_entry(row), "X3"), entry=queue.parse_entry(row), package=PACKAGE,
                              now=NOW - timedelta(hours=8))
            # Two audits the residual never counts (spec 4.11): an X5 audit of an answer delivery, and an X6 audit of an abstention.
            uncounted = {}
            for record, trigger in ((deliveries[9], "X5"), (abstention, "X6")):
                seq = db.scalar(select(ResponseLedgerRecord.seq).where(ResponseLedgerRecord.response_id == record.response_id))
                assert db.scalar(select(V3Draw.drawn).where(V3Draw.ledger_seq == seq)) is None
                row = queue.record_row(db, seq)
                with v3_fakes.double_review_selection(False):   # one round each (the selection is fixed when an item is created)
                    item_id, created = queue.upsert_item(db, record_row=row, spec=response_spec(queue.parse_entry(row), trigger),
                                                         entry=queue.parse_entry(row), package=PACKAGE, now=NOW - timedelta(hours=8))
                assert created
                uncounted[item_id] = record
            db.commit()
        pair_ids = v3_fakes.seed_items(factory, v3_fakes.reviewable_deliveries(2, start=900), package=PACKAGE, now=NOW - timedelta(hours=7),
                                       double_review=True)
        request = v3_fakes.supported_labels(deliveries[0])
        with factory() as db:
            for item_id, disagree in zip(pair_ids, (False, True)):
                queue.claim_item(db, item_id, user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
                queue.adjudicate(db, item_id, request(f"pair1-{item_id[4:14]}"), user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
                queue.claim_item(db, item_id, user_id="synthetic-reviewer-b", now=NOW, package=PACKAGE)
                labels = request(f"pair2-{item_id[4:14]}", "CONTRADICTED", "A") if disagree else request(f"pair2-{item_id[4:14]}")
                queue.adjudicate(db, item_id, labels, user_id="synthetic-reviewer-b", now=NOW, package=PACKAGE)
            assert queue.get_item(db, pair_ids[1]).review_round == 3
            single_round = 0
            for item_id in x6_items:
                queue.claim_item(db, item_id, user_id="synthetic-reviewer-c", now=NOW, package=PACKAGE)
                queue.adjudicate(db, item_id, request(f"x6-{item_id[4:14]}"), user_id="synthetic-reviewer-c", now=NOW, package=PACKAGE)
                single_round += int(not queue.get_item(db, item_id).double_review)   # a double-review item waits for its round 2
            for item_id, record in uncounted.items():
                labels = v3_fakes.supported_labels(record)
                queue.claim_item(db, item_id, user_id="synthetic-reviewer-c", now=NOW, package=PACKAGE)
                queue.adjudicate(db, item_id, labels(f"audit-{item_id[4:14]}", *(("CONTRADICTED", "A") if record.claims else ())),
                                 user_id="synthetic-reviewer-c", now=NOW, package=PACKAGE)
                assert queue.get_item(db, item_id).state == "adjudicated"
            body = slis(db, PACKAGE, now=NOW)
            considered = db.scalar(select(func.count()).select_from(V3Draw))
            x6 = db.scalar(select(func.count()).select_from(V3Draw).where(V3Draw.drawn == "X6"))
            open_ages = [int((NOW - queue.utc(row.enqueued_at)).total_seconds()) for row in db.execute(select(V3QueueItem.enqueued_at).where(V3QueueItem.state == "queued"))]
    share = body["escalation_share"]
    # 41 deliveries considered; the X3 item on delivery 1 and the shadow record's X1 item (on delivery 3) count, X5 and X6 never.
    assert share["deliveries"] == considered == 41 and share["escalated"] == 2 and share["share"] == "2/41" and share["max"] == "1/10"
    assert share["above_max"] is False and share["counted"] == ["X1", "X2", "X3", "X4"]
    assert body["draws"]["considered"] == considered and body["draws"]["x6"] == x6 and body["draws"]["x6_rate"] == f"{x6}/{considered}"
    from app.services.v3.metrics import nearest_rank

    assert body["queue"]["age_p90_s"] == nearest_rank(open_ages, 0.9) and body["queue"]["age_max_s"] == max(open_ages)
    assert body["double_review"]["pairs"] == 2 and body["double_review"]["agreeing"] == 1 and body["double_review"]["agreement"] == "1/2"
    # The residual counts the X6-audited answer deliveries only: neither the X5 audit (labelled CONTRADICTED) nor the abstention.
    assert body["residual"]["audited"] == single_round and body["residual"]["errors"] == 0
    assert all(month["month"] == "2026-11" for month in body["residual"]["by_month"])
    assert body["gold"]["rows"] >= 4 and body["stop"]["active"] is False and body["x5"] == {"active": False, "events": 0}


def test_plan_f_the_trigger_registry_document_matches_the_package():
    document = (REPO_ROOT / "docs" / "architecture" / "v3-trigger-registry.md").read_text(encoding="utf-8")
    v3_raw = PACKAGE.raw["v3"]
    for trigger, rule in v3_raw["triggers"]["rules"].items():
        row = next(line for line in document.splitlines() if line.startswith(f"| {trigger} |"))
        assert f"`{rule}`" in row, trigger
        assert ("| counted |" in row) is (trigger in v3_raw["triggers"]["counted"]), trigger
    x1, x1_row = v3_raw["triggers"]["x1"], next(line for line in document.splitlines() if line.startswith("| X1 |"))
    tiers = [str(tier) for tier in x1["tiers"]]
    assert f"at tiers {', '.join(tiers[:-1])} and {tiers[-1]}" in x1_row and f"at tier {x1['withhold_tier']} only" in x1_row
    for reason in v3_raw["triggers"]["queue_reasons"]:
        assert f"`{reason}`" in document
    severity = v3_raw["priority"]["severity"]
    if severity.get("source") == "ehmf.weights":  # package v6 (Phase 7): V3 severity is the ehmf weights
        weights = PACKAGE.raw["ehmf"]["weights"]
        severity = {**{key: weights[key] for key in ("A", "B", "C", "D", "E")}, "unknown": severity["unknown"], "disclosed_conflict": weights["D_disclosed"]}
    for name, weight in severity.items():
        assert f"| {name} | {weight} |" in document, name
    for key in ("rule", "exposure_rule", "claim_set_key_rule", "k_rule"):
        assert f"`{v3_raw['priority'][key]}`" in document
    draw_rate, x5_rate = v3_raw["draw"]["rate"], v3_raw["triggers"]["x5"]["audit_rate"]
    assert f"`{v3_raw['draw']['rule']}`" in document and f"seed `{v3_raw['draw']['seed']}`" in document
    assert f"{draw_rate['numerator']}/{draw_rate['denominator']}" in document and f"{x5_rate['numerator']}/{x5_rate['denominator']}" in document
    assert f"{v3_raw['triggers']['x5']['window_deliveries']} learner deliveries" in document
    double = v3_raw["workflow"]["double_review"]["rate"]
    assert f"double review {double['numerator']}/{double['denominator']}" in document
    slo = v3_raw["slo"]
    assert f"{slo['queue_age_slo_s']} s" in document and f"{slo['stop_window_s']} s" in document and f"{slo['stop_sample_s']} s" in document
    assert f"`{v3_raw['triggers']['version']}`" in document


def test_plan_f_the_committed_residual_report_matches_a_fresh_run_and_names_its_evidence_class(residual_report):
    module, fresh = residual_report
    committed = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase6" / "v3_residual_report_v1.json").read_text(encoding="utf-8"))
    assert module.comparable(committed) == module.comparable(fresh)
    assert module.input_problems(committed["inputs"]) == []
    assert committed["evidence_class"].startswith("synthetic telemetry, not research results") and committed["public_corpus_only"] is True
    assert committed["config_package"] == {"version": PACKAGE.package_version, "sha256": PACKAGE.sha256}
    readme = (REPO_ROOT / "docs" / "evaluation" / "phase6" / "README.md").read_text(encoding="utf-8")
    assert "synthetic telemetry, not research results" in readme and "run_v3_residual_report.py --check" in readme and "Phase 10" in readme


def test_plan_e_only_two_v3_tables_hold_a_person_s_id_and_erasure_reaches_them():
    from app.core.db import Base
    from app.services.erasure import USER_KEY_COLUMNS, erase_user, user_keyed_tables

    keyed = {table.name for table in user_keyed_tables() if table.name.startswith("v3_")}
    assert keyed == {"v3_claims", "v3_flags"}
    for name in ("v3_queue_items", "v3_draws", "v3_gold_labels", "v3_events", "v3_model_versions", "v3_scans"):
        assert not set(USER_KEY_COLUMNS) & set(Base.metadata.tables[name].c.keys()), name
    learner = _demo()
    turn_id = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=learner).json()["turn_id"]
    client.post("/v3/flags", json={"response_id": turn_id}, headers=learner)
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(2)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=False)
        with factory() as db:
            queue.claim_item(db, ids[0], user_id="synthetic-reviewer-e", now=NOW, package=PACKAGE)
            queue.adjudicate(db, ids[0], v3_fakes.supported_labels(entries[0])("erase-key-1"), user_id="synthetic-reviewer-e", now=NOW, package=PACKAGE)
            queue.claim_item(db, ids[1], user_id="synthetic-reviewer-e", now=NOW, package=PACKAGE)
            erase_user(db, "synthetic-reviewer-e")
            db.commit()
            assert db.scalar(select(func.count()).select_from(V3Claim)) == 0
            assert queue.workflow_state(db, queue.get_item(db, ids[1]), now=NOW) == "queued"
            assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == 1
    with SessionLocal() as db:
        seq = db.scalar(select(ResponseLedgerRecord.seq).where(ResponseLedgerRecord.response_id == turn_id))
        erase_user(db, learner["x-demo-user"])
        db.commit()
        assert db.scalar(select(func.count()).select_from(V3Flag).where(V3Flag.ledger_seq == seq)) == 0
        assert f_i(db, seq) == 0.0   # F_i lives on the X3 item, which holds no learner id


def test_invariant_5_a_flag_feeds_quality_only_and_never_a_verdict():
    properties = _entry_schema_properties()
    assert not properties & {"f_i", "feedback", "flag", "flags", "learner_flag", "learner_rating"}
    # The flag table is read by the feedback service only; no verdict, ledger or pipeline module reads it or F_i.
    for path in sorted((API_ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(API_ROOT / "app").as_posix()
        if "V3Flag" in source:
            assert relative in ("db_models.py", "services/v3/feedback.py"), relative
        if re.search(r"\bf_i\(", source):
            assert relative == "services/v3/feedback.py", relative
        if relative.startswith(("services/v1_checks/", "services/v2_panel/", "services/tutor_pipeline/", "services/ledger.py")):
            assert "v3.feedback" not in source and "v3_flags" not in source, relative


def test_invariant_6_no_x1_claim_is_delivered_under_any_fault_schedule():
    base, target = _critical_target()
    claims = v3_fakes.critical_claims_of(base)
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    rng = random.Random(6061)
    fired = objector_left = 0
    for schedule in range(300):
        options = {}
        objector = rng.choice([spec.adapter_id for spec in registry.members])
        for spec in registry.members:
            option: dict = {}
            if rng.random() < 0.15:
                option["down"] = True
            if rng.random() < 0.15:
                option["late_ms"] = 10_000.0
            if spec.adapter_id == objector or rng.random() < 0.2:
                objected = rng.sample(claims, rng.randint(1, len(claims)))
                from v2_fakes import claim_key

                option["script"] = {claim_key(claim.text, span_id): ("CONTRADICTED", rng.choice("ABCDE")) for claim in objected for span_id in claim.span_ids}
            if rng.random() < 0.4 or (spec.adapter_id == objector and schedule % 3 == 0):
                option["fail_calls"] = tuple(sorted(rng.sample(range(2, 12), rng.randint(1, 3))))
            options[spec.adapter_id] = option
        adapters = adapters_of(registry, **options)
        cache = v3_fakes.NoCache() if schedule % 2 else None
        _, entry = v3_fakes.shadow_v3_record(adapters=adapters, generator=RevisingGenerator(ExtractiveD19Generator(base.package)), cache=cache)
        verification = entry.verification
        x1 = x1_claims(entry)
        held = withheld_claim_ids(entry)
        for verdict in verification.verdicts:
            if verdict.claim_id in x1:
                assert verdict.final != "deliver", (schedule, verdict.claim_id)
                assert verdict.claim_id in held
        fired += bool(x1)
        objector_left += any(verdict.claim_id in x1 and verdict.v2 is not None and verdict.v2.objections == 0 for verdict in verification.verdicts)
    assert fired >= 30 and objector_left >= 1, (fired, objector_left)


def test_freeze_outside_development_v3_is_off_and_no_learner_path_changes(monkeypatch):
    from app import main as main_module

    production = Settings(environment="production", enable_demo_auth=True, guest_token_secret="p" * 40, allowed_origins=["https://qantumlearn.academy"])
    assert v3.mode(production, get_config_package(production)) == "off"
    learner = _demo()
    with SessionLocal() as db:
        counts = {table: db.scalar(text(f"SELECT COUNT(*) FROM {table}")) for table in sorted(V3_TABLES)}
    turn_id = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=learner).json()["turn_id"]
    with SessionLocal() as db:
        assert {table: db.scalar(text(f"SELECT COUNT(*) FROM {table}")) for table in sorted(V3_TABLES)} == counts   # a chat writes no V3 row
    monkeypatch.setattr(security_log, "_caps", security_log._Caps())
    for setting in ("off", "shadow"):
        configured = Settings(environment="production", enable_demo_auth=True, guest_token_secret="p" * 40,
                              allowed_origins=["https://qantumlearn.academy"], v3_queue=setting)
        app.dependency_overrides[get_settings] = lambda configured=configured: configured
        try:
            assert client.post("/v3/flags", json={"response_id": turn_id}, headers=learner).status_code == 404, setting
            assert client.get("/v3/queue", headers=v3_fakes.reviewer("a")).status_code == 403, setting
        finally:
            app.dependency_overrides.pop(get_settings, None)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main_module, "settings", production)
        assert main_module._v3_mode(get_config_package(production)) == "off"
    source = (API_ROOT / "tests" / "test_phase5_acceptance.py").read_text(encoding="utf-8")
    assert "def test_freeze_public_payloads_with_shipped_non_development_settings_are_byte_identical_to_phase_4(" in source


def test_plan_13_6_flag_combinations_with_v3_queue_never_release_or_reach_learners():
    from app.api.routes.v3 import flag_intake_open
    from app.services.tutor_pipeline.contracts import TWO_PASS_DELIVERY_IMPLEMENTED

    checked = refused = 0
    for environment, queue_setting, gateway, two_pass in itertools.product(("development", "staging", "production"), ("off", "shadow", "on"),
                                                                          ("off", "shadow", "on"), ("off", "shadow", "on")):
        options = dict(environment=environment, v3_queue=queue_setting, model_gateway=gateway, two_pass_tutor=two_pass,
                       allowed_origins=["https://qantumlearn.academy"], guest_token_secret="c" * 40)
        development = environment == "development"
        expected_refusal = (two_pass == "on" or (gateway == "on" and not development) or (queue_setting == "on" and not development))
        try:
            settings = Settings(**options)
        except ValidationError:
            refused += 1
            assert expected_refusal, options
            continue
        assert not expected_refusal, options
        checked += 1
        package = get_config_package(settings)
        mode = v3.mode(settings, package)
        if not development:
            assert mode == ("shadow" if queue_setting == "shadow" else "off"), options
        assert flag_intake_open(settings) is (development and queue_setting != "off"), options
    assert checked and refused and TWO_PASS_DELIVERY_IMPLEMENTED is False and released(None) is False


def test_plan_c_the_metrics_count_gold_claims_toward_the_dawid_skene_minimum():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(3)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=False)
        with factory() as db:
            for index, item_id in enumerate(ids):
                queue.claim_item(db, item_id, user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
                queue.adjudicate(db, item_id, v3_fakes.supported_labels(entries[index])(f"ds-key-{index:04d}"), user_id="synthetic-reviewer-a", now=NOW,
                                 package=PACKAGE)
            gold = slis(db, PACKAGE, now=NOW)["gold"]
    assert gold == {"rows": 3, "head_seq": 3, "claims_labelled": 3, "dawid_skene_minimum": 200}
    assert PACKAGE.v2.panel_weights_version == get_config_package(SETTINGS).v2.panel_weights_version == "equal-weights-v1"


# ===================================================================================================== docs


def _code_fields(source: str, name: str) -> list[str]:
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]


def test_phase6_spec_section_3_lists_the_code_s_fields():
    section = spec_text().split("## 3. Data shapes", 1)[1].split("## 4. Algorithms", 1)[0]
    blocks = re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL)
    assert len(blocks) >= 3
    sources = {"contracts": (API_ROOT / "app" / "services" / "v3" / "contracts.py").read_text(encoding="utf-8"),
               "triggers": (API_ROOT / "app" / "services" / "v3" / "triggers.py").read_text(encoding="utf-8"),
               "scan": (API_ROOT / "app" / "services" / "v3" / "scan.py").read_text(encoding="utf-8"),
               "stop": (API_ROOT / "app" / "services" / "v3" / "stop.py").read_text(encoding="utf-8")}
    rules = (API_ROOT / "app" / "services" / "v3" / "rules.py").read_text(encoding="utf-8")
    checked = 0
    for block in blocks:
        tree = ast.parse(block)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                owner = next(name for name, source in sources.items() if re.search(rf"^class {node.name}\b", source, flags=re.MULTILINE))
                spec_fields = [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]
                assert spec_fields == _code_fields(sources[owner], node.name), node.name
                checked += 1
            elif isinstance(node, ast.Assign) and block is blocks[-1]:
                assert ast.unparse(node) in {ast.unparse(item) for item in ast.parse(rules).body if isinstance(item, ast.Assign)}, ast.unparse(node)
                checked += 1
    assert checked >= 20


def test_phase6_docs_quote_the_plan_and_state_the_current_rules():
    spec = spec_text()
    head = spec.split("\n## 18. Review history\n", 1)[0]
    plan_l = ("Disabling V3 MUST NOT release withheld items.", "Stop (operator policy, set under Decision D-06): queue age above SLO for two days "
              "limits tier 1 to pre-verified content.")
    plan_k = "then X1 fires and it is withheld"
    plan_d = ("X1 critical-claim objection (registry [Decision D-25]; withheld at tier 1); X2 Type A/B unresolved after two cycles; X3 learner flag "
              "(F_i = 0, never a verdict); X4 abstention margin [Decision D-06]; X5 CUSUM alarm or model change (audit 20%); X6 audit draw.")
    task3 = "Workflow queued -> claimed -> adjudicated -> applied; append-only gold store; 10% double review (operator policy, set under Decision D-06)."
    flat = " ".join(head.split())
    assert all(sentence in flat for sentence in plan_l) and plan_k in flat and plan_d in flat and task3 in flat
    for number in range(32, 40):
        assert f"| PD-{number} |" in head, number
    for number in range(89, 104):
        assert f"| DI-{number} |" in head, number
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 6: V3 audit and adjudication (runbook)", 1)[1]
    example = (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8")
    assert "V3_QUEUE" in head and "V3_QUEUE" in runbook and 'V3_QUEUE: "off"' in example
    assert "Disabling V3 MUST NOT release withheld items" in (REPO_ROOT / "docs" / "adr" / "ADR-009-v3-audit-and-adjudication.md").read_text(encoding="utf-8")
    from test_phase3_docs import NARRATIVE

    assert NARRATIVE.findall(head) == []


def test_phase6_docs_state_what_each_caller_of_a_v3_route_gets():
    # What the code answers (test_ac_6_7_a_guest_on_every_reviewer_route_gets_403_and_one_access_log_entry,
    # test_plan_b_no_reviewer_is_admitted_outside_development_while_d_18_is_open,
    # test_outside_development_a_caller_without_a_credential_gets_401_and_no_security_event): a reviewer route gives an
    # authenticated caller of another role 403 and authz.denied in every environment (outside development every
    # authenticated caller), 404 only to an admitted reviewer while V3 is off, and 401 with no security event to a caller
    # without a credential where demo auth is off; the flag route gives an authenticated caller 404 outside development.
    # Each text an operator reads says so, and none says that every /v3 route answers 404.
    import inspect

    from app.api.routes import v3 as v3_routes
    from app.services import v3 as v3_package

    flat = lambda value: " ".join(value.split())  # noqa: E731
    head = spec_text().split("\n## 18. Review history\n", 1)[0]
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 6: V3 audit and adjudication (runbook)", 1)[1]
    example = (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8")
    example = example.split("# Phase 6 (V3 audit and adjudication", 1)[1].split('V3_QUEUE: "off"', 1)[0]
    config = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    config = config.split("# Phase 6 (V3 audit and adjudication", 1)[1].split("v3_queue: Literal", 1)[0]
    texts = {"spec": head, "runbook": runbook, "env example": example.replace("#", " "), "matrix note": authz.V3_REVIEWER_NOTE,
             "routes": inspect.getdoc(v3_routes), "package": inspect.getdoc(v3_package), "setting": config.replace("#", " ")}
    stale = re.compile(r"every (?:`?/v3`? )?route answers 404|reviewer routes answer 404(?! (?:only )?to an admitted reviewer)"
                       r"|security event to every caller|every caller gets 403")
    for name, value in texts.items():
        value = flat(value)
        assert not stale.search(value), (name, stale.search(value))
        assert "401" in value and "403" in value, name
    for name in ("spec", "runbook", "env example", "matrix note", "routes"):
        assert "authz.denied" in texts[name] and "no security event" in flat(texts[name]), name
    assert "An admitted reviewer gets 404 unless V3_QUEUE is shadow or on" in authz.V3_REVIEWER_NOTE
    assert "reads 401, not 403" in flat(runbook)
    # The draw's seed is public by design (spec 4.2): the server mints every response id the draw keys on.
    assert 'turn_id = f"turn-{uuid4()}"' in (API_ROOT / "app" / "services" / "tutor_orchestrator.py").read_text(encoding="utf-8")
    assert 'response_id=f"qa-{uuid4()}"' in (API_ROOT / "app" / "services" / "qa_engine.py").read_text(encoding="utf-8")
    draw = head.split("### 4.2 The draw", 1)[1].split("### 4.3", 1)[0]
    assert "**The seed is public by design.**" in draw and "no caller can choose or change which deliveries are drawn" in flat(draw)
    # AC-6-7's reading: the API's reviewer routes; the development console over them is not a gate (spec conflict 5).
    conflict_5 = flat(head.split("5. **AC-6-7 \"an access-log entry\".**", 1)[1].split("\n6. ", 1)[0])
    assert "AC-6-7's \"reviewer route\" is read as the API's reviewer routes" in conflict_5 and "`reviewerHeaders`" in conflict_5


def test_phase6_docs_name_the_logger_each_phase6_event_logs_on():
    spec = spec_text()
    table = spec.split("### 10.3 Log events", 1)[1].split("### 10.4", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    sources = "\n".join(path.read_text(encoding="utf-8") for path in sorted((API_ROOT / "app").rglob("*.py")))
    checked = 0
    for row in rows:
        events = re.findall(r"`([a-z0-9_.]+)`", row.split("|")[1])
        logger = re.search(r"`(qcai\.[a-z0-9]+)`", row.split("|")[2]).group(1)
        for name in events:
            assert f'"{name}"' in sources, name
            checked += 1
        assert f'getLogger("{logger}")' in sources, logger
    assert checked >= 12
    observability = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").split("## Phase 6 SLIs: V3 (plan Phase 6 I)", 1)[1]
    for name in ("v3.scan", "v3.stop", "v3.x5_event", "tutor.v2.v3_stop", "v3_queue_shadow", "v3_queue_on"):
        assert name in observability, name
    # Every v3.* event the code logs, and each field it gives the worker's status and gold lines, is listed in 10.3 and
    # in the observability runbook (a table that names only some cannot pass).
    logged = set(re.findall(r'"(v3\.[a-z0-9_]+)"', sources)) - {"v3.json"}
    listed = set(re.findall(r"`(v3\.[a-z0-9_]+)`", table))
    assert logged and logged <= listed, sorted(logged - listed)
    named = set(re.findall(r'(?:`|event=")(v3\.[a-z0-9_]+)(?:`|")', observability))   # `v3.x` or jsonPayload.event="v3.x"
    assert logged <= named, sorted(logged - named)
    worker = next(line for line in table.splitlines() if "`v3.status`" in line)
    for field in ("`mode`", "`problems`", "`problem_count`", "`scans`", "`last`", "`applied_only`"):
        assert field in worker, field


PHASE6_EXTENDED_MODULES = (
    "conftest.py", "test_authorization.py", "test_config_package.py", "test_configuration_overrides.py", "test_phase3_acceptance.py",
    "test_phase4_acceptance.py", "test_phase5_acceptance.py", "test_response_ledger_migrations.py", "test_v2_correction.py", "test_v2_panel.py",
)


def test_phase6_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    phase_6 = strategy.split("## Phase 6 acceptance map", 1)[1].split("\n## ", 1)[0]
    files = phase_6.split("### Phase 6 test files", 1)[1]
    added_table, changed_table = files.split("### Phase 6 changes to existing test modules", 1)
    changed_table = changed_table.split("**Exit gate.**", 1)[0]

    def rows_of(table: str) -> dict[str, str]:
        return {match.group(1): match.group(2) for line in table.splitlines() if (match := re.match(r"\| `([^`]+)` \| (.+) \|$", line))}

    rows, changed = rows_of(added_table), rows_of(changed_table)
    tests = API_ROOT / "tests"
    expected = {path.name for pattern in ("test_phase6_*.py", "test_v3_*.py", "v3_fakes.py") for path in tests.glob(pattern)}
    expected |= {"apps/frontend/tests/v3-review.integration.test.ts"}
    assert sorted(rows) == sorted(expected), sorted(set(rows) ^ expected)
    assert sorted(changed) == sorted(PHASE6_EXTENDED_MODULES), sorted(set(changed) ^ set(PHASE6_EXTENDED_MODULES))
    # The modules Phase 6 changed are all here, and each carries Phase 6 content (no row maps a module Phase 6 left alone).
    assert {"test_authorization.py", "test_config_package.py", "test_configuration_overrides.py", "test_response_ledger_migrations.py",
            "test_v2_correction.py", "test_v2_panel.py", "conftest.py"} <= set(PHASE6_EXTENDED_MODULES)
    markers = ("Phase 6", "v3_fakes", "app.services.v3", "V3_QUEUE", "v3_queue", "PHASE6")
    for name in PHASE6_EXTENDED_MODULES:
        assert any(marker in (tests / name).read_text(encoding="utf-8") for marker in markers), name
    for name, text_ in {**rows, **changed}.items():
        assert len(text_) > 80, name
    names = set()
    for path in tests.glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    assert [name for name in re.findall(r"`(test_[a-z0-9_]+)`", phase_6) if name not in names] == []
    assert "**Exit gate.**" in phase_6 and "phase6_exit_passed" in phase_6


def test_phase6_docs_the_texts_phase6_made_false_state_the_current_code():
    import inspect

    from app.api.routes import ledger as ledger_route
    from app.services import ledger as ledger_service
    from app.services.v1_checks import v1_5_abstention
    from app.services.v2_panel import tiers

    flat = lambda value: " ".join((value or "").split())  # noqa: E731
    assert "critical claims follow X1 in Phase 6" not in flat(inspect.getdoc(tiers)) and "v3.critical_claims" in flat(inspect.getdoc(tiers))
    assert "Phase 6 X4 trigger candidate" not in flat(inspect.getdoc(v1_5_abstention)) and "X4 trigger (app.services.v3.triggers.x4_fires)" in flat(
        inspect.getdoc(v1_5_abstention))
    assert "Phase 6 consumes it (DI-56)" not in flat(ledger_service.pending_v3_intents.__doc__)
    assert "the Phase 6 scan reads the records itself" in flat(ledger_service.pending_v3_intents.__doc__)
    assert "reviewer_admitted" in flat(inspect.getdoc(ledger_route))
    phase5 = (REPO_ROOT / "docs" / "architecture" / "phase5-implementation-spec.md").read_text(encoding="utf-8")
    assert "development holds Phase 6's synthetic registry" in phase5 and "The X1 trigger and the sticky hold" in phase5
    phase3 = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
    assert "`.../v5.json` with Phase 6" in phase3 and "5 since Phase 6, and 6 since Phase 7" in phase3 and "`.../v6.json` with Phase 7" in phase3
    ledger_paragraph = next(line for line in phase3.splitlines() if "LEDGER_READER_ROLES" in line and "D-18" in line)
    assert "reviewer_admitted" in ledger_paragraph
    phase4 = (REPO_ROOT / "docs" / "architecture" / "phase4-implementation-spec.md").read_text(encoding="utf-8")
    assert "`v5.json` with Phase 6" in phase4 and "5 since Phase 6" in phase4 and "`v6.json` with Phase 7" in phase4


def test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head():
    # The Phase 3 rollback's "Check the stamp" step names alembic's current head (`ledger.SCHEMA_REVISION`, which alembic
    # current prints with "(head)") and takes the Phase 6, then the Phase 5 downgrade step from it; no other revision is
    # called the head.
    from app.services.ledger import SCHEMA_REVISION

    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    step = runbook.split("3. **Check the stamp:** `alembic current`.", 1)[1].split("\n4. ", 1)[0]
    # Since Phase 7 the head is 20261123_phase7_ehmf: its bullet takes the Phase 7 step, then the Phase 6 and Phase 5 steps.
    assert re.findall(r"`([0-9a-z_]+) \(head\)`", step) == [SCHEMA_REVISION] == ["20261123_phase8_learner"]
    head_bullet = next(line for line in step.splitlines() if f"`{SCHEMA_REVISION} (head)`" in line)
    assert "alembic downgrade 20261123_phase7_ehmf" in head_bullet
    assert "allow_ehmf_drop=true downgrade 20261122_phase6_v3_audit" in head_bullet
    assert any(line.strip().startswith("- `20261123_phase7_ehmf`:") for line in step.splitlines())
    assert "allow_v3_drop=true downgrade 20261122_phase5_gateway_controls" in head_bullet and "export-gold --all" in head_bullet
    assert any(line.strip().startswith("- `20261122_phase6_v3_audit`:") for line in step.splitlines())
    assert "alembic downgrade 20261119_phase3_response_ledger" in head_bullet
    assert any(line.strip().startswith("- `20261122_phase5_gateway_controls`:") for line in step.splitlines())
    assert step.rstrip().splitlines()[-1].strip() == "- Anything else: stop."


def test_phase6_docs_the_spec_ends_in_one_review_history_table():
    head, history = spec_text().split("\n## 18. Review history\n", 1)
    assert re.findall(r"^## (\d+)\. ", head, flags=re.MULTILINE) == [str(number) for number in range(18)]
    assert "\n## " not in history and "\n### " not in history and history.count("\n| Round |") == 1
    intro = history.split("\n| Round |", 1)[0]
    assert "may describe behaviour that a later round superseded" in intro and "sections 0-17 are authoritative" in intro
    rows = [line for line in history.splitlines() if line.startswith("| ") and not line.startswith(("| Round |", "|---"))]
    assert [row.split(" | ", 1)[0] for row in rows[:2]] == ["| Spec (pre-code)", "| Spec review 1 (pre-code)"]
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    for row in rows:
        round_name, commit, findings = row.split(" | ", 2)
        assert "pre-code" in round_name or re.search(r"`[0-9a-f]{7,40}`|the commit", commit), round_name
        assert all(name in names for name in re.findall(r"`(test_[a-z0-9_]+)`", findings)), round_name
    # A review round is named only in section 18 (a gold label's "round 2" is a domain term here, so it is allowed).
    assert re.findall(r"\b[Rr]eview \d+\b(?![/.\d])", head) == []


def test_phase6_docs_the_records_name_the_merge_and_the_cited_main_run():
    # PR #38 was squash-merged as 31343c8 (tree identical to 1c49b74); main run 45180967316 passed every job and is the
    # cited run (Phase 7 design E15). The spec's DI-89 row, its section 17 exit bullet and the test strategy's Phase 6 exit
    # paragraph name the merge, the merged tree and that run, none keeps a pre-merge phrase, and the exit stays not passed.
    spec = spec_text()
    head, history = spec.split("\n## 18. Review history\n", 1)
    exit_block = head.split("**Exit (plan P).**", 1)[1]
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    texts = {
        "DI-89": next(line for line in head.splitlines() if line.startswith("| DI-89 |")),
        "spec 17": next(line for line in exit_block.splitlines() if line.startswith("- The AC tests are done in code.")),
        "test strategy": next(line for line in strategy.split("## Phase 6 acceptance map", 1)[1].splitlines() if line.startswith("**Exit gate.**")),
    }
    for name, text in texts.items():
        for fact in ("`31343c8`", "`1c49b74`", "45180967316"):
            assert fact in text, (name, fact)
        for stale in ("no run on `main` exists before the merge", "each later commit needs its own run", "the cited run must be on `main`",
                      "the cited CI run must be on `main`"):
            assert stale.lower() not in text.lower(), (name, stale)
    assert "The exit is not passed." in texts["DI-89"] and texts["DI-89"].endswith("| Eng / PI | Open |")
    assert "The exit is not passed." in texts["test strategy"]
    assert "- `phase6_exit_passed` stays `false`. The exit is not passed." in exit_block
    assert "| Converge 2 | `1c49b74` |" in history and "| Merge | `31343c8` |" in history
