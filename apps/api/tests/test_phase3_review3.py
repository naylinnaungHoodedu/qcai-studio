"""Phase 3, third review round (2026-11-19; Phase 3 spec 18.6). Each test fails if its defect comes back.

D1  the shadow log line carries the plan L bound-claim ratio terms (/ready's), so the cross-instance SLI cannot
    raise a false stop on a merge or a budget overrun.
D2  task 3.3 "atomic claims": the D-19 reading (one verbatim sentence per claim) is recorded as an unratified
    deviation, not left implicit.
D3  plan 12.8 is quoted in full, with its proposed default and why it is not applied.
D4  the subset check fails a rendering that shows no claim, or a claim without its citation; the ledger records
    what the passing rendering showed.
D5  the budgets in force are stamped on every record, reported on /ready, and an override raises config.override.
D6  configuration package flag_policy is marked provisional (PD-10).
D7  the ADRs, the spec and the evidence records say what the code does.
D8  a ledger check that overlaps appends reports a sound chain as sound.
D9  public /ready carries no per-run shadow output (AC-3-6).
D10 no code or page claims a Q&A ledger record is unlinkable while the asker's Q&A history exists.
D11 the pydantic floor that keeps production chat bodies unchanged is declared and checked at start-up.
D12 the required status check "api-postgres" still reports under the driver matrix.
D13 the in-image worker runs the coverage and export steps; the PostgreSQL append bounds idle time in its
    transaction.
(D14, the evidence-panel accessibility, is in the frontend tests; D15, the flaky in-flight test, is in
test_response_ledger.py.)

Isolation (spec M17): chain tests use fresh_database_url. No skips: dialect-specific assertions branch inside.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app import main as main_module
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.core.db import Base, SessionLocal
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import TutorMessage, TutorThread, TutorTurn
from app.main import app
from app.services import claim_gate, ledger
from app.services.ledger import append_ledger_entry, build_legacy_entry, record_legacy_delivery, verify_response_ledger
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import PresentationPlan, bound_claim_ratio_terms
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.metrics import PUBLIC_SHADOW_FIELDS, TWO_PASS_METRICS
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.shadow import ShadowJob, run_shadow, shadow_budget_ms
from tutor_fakes import FaultyRenderer, make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
DATA = Path(__file__).parent / "data"
PLAN_PATH = REPO_ROOT.parent / "QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
REGRESSION_QUERY = json.loads((DATA / "phase3_replay_regressions.json").read_text(encoding="utf-8"))["items"][0]["query"]
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
# A query whose two-pass answer has several claims on several spans (spec 18.10 H1: the graph-shrinking query now
# answers with one whole sentence, because its other spans start or end inside the sentences it matched).
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
client = TestClient(app)


@pytest.fixture
def clean_metrics():
    TWO_PASS_METRICS.reset()
    yield
    TWO_PASS_METRICS.reset()


def _thread_with_message(content: str) -> tuple[str, str]:
    with SessionLocal() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review3-{uuid4().hex[:10]}", title="t")
        db.add(thread)
        db.flush()
        message = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content=content, created_at=datetime.now(UTC))
        db.add(message)
        db.commit()
        return thread.id, message.id


def _job(thread_id: str, message_id: str) -> ShadowJob:
    return ShadowJob(shadow_response_id=f"shadow-{uuid4()}", shadowed_response_id=f"turn-{uuid4()}", thread_id=thread_id, user_message_id=message_id,
                     lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="default"))


def _shadow_line(caplog) -> dict:
    (line,) = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "tutor.two_pass.shadow"]
    return line


def _run(pipeline: TwoPassPipeline, query: str, *, budget_ms: int | None = None):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"),
                        budget_ms=budget_ms, record=False)


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


# ============================================================================================================ D1


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _ClockedGenerator:
    """Moves the pipeline's clock on by 10 s while it proposes: the budget runs out after the generator returns."""

    def __init__(self, inner, clock: _FakeClock) -> None:
        self.inner, self.ref, self.clock = inner, inner.ref, clock

    def propose(self, envelope):
        self.clock.now += 10.0
        return self.inner.propose(envelope)


def test_d1_the_shadow_log_line_carries_the_ready_ratio_terms_for_a_merged_run(clean_metrics, caplog):
    settings = Settings()
    thread_id, message_id = _thread_with_message(REGRESSION_QUERY)
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        run_shadow(_job(thread_id, message_id), settings=settings,
                   pipeline_factory=lambda: TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings))
    line = _shadow_line(caplog)
    # The regression item merges one sentence held by two overlapping spans: the raw counts leave it out of bound.
    assert line["dropped"].get("merged", 0) >= 1 and line["bound"] < line["proposed"]
    detail = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert (line["ratio_proposed"], line["ratio_bound"]) == (detail["proposed_claims"], detail["bound_claims"])
    assert line["ratio_bound"] == line["ratio_proposed"] > 0  # every proposed claim bound: the ratio is 1.0, no stop
    assert detail["bound_claim_ratio_stop"] is False


def test_d1_the_shadow_log_line_leaves_a_budget_skipped_claim_out_of_both_terms(clean_metrics, caplog):
    settings = Settings()
    clock = _FakeClock()
    thread_id, message_id = _thread_with_message("Why does routing depth matter?")
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        run_shadow(_job(thread_id, message_id), settings=settings, pipeline_factory=lambda: TwoPassPipeline(
            RetrievalEngine(get_course_store(), settings), settings, generator=_ClockedGenerator(ExtractiveD19Generator(PACKAGE), clock), clock=clock))
    line = _shadow_line(caplog)
    assert line["proposed"] > 0 and line["dropped"] == {"budget_exceeded": line["proposed"]}
    assert (line["ratio_proposed"], line["ratio_bound"]) == (0, 0)
    detail = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert (detail["proposed_claims"], detail["bound_claims"]) == (0, 0) and detail["bound_claim_ratio_stop"] is False


def test_d1_the_runbook_sli_sums_the_ratio_terms_not_the_raw_counts():
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    assert "jsonPayload.ratio_bound" in runbook and "jsonPayload.ratio_proposed" in runbook
    assert "sum of `jsonPayload.bound` over sum of `jsonPayload.proposed`" not in runbook
    shadow_source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "bound_claim_ratio_terms(entry.counts)" in shadow_source


# ============================================================================================================ D2


def test_d2_the_atomic_claims_reading_is_an_unratified_recorded_deviation():
    decision = RAW["owner_decisions"]["PLAN-3.3"]
    assert decision["ratified"] is False and decision["status"] == "provisional" and "DI-47" in decision["record"]
    (deviation,) = decision["deviations"]
    quoted = "3.3 Claim plan: atomic claims bound to span ids from a structured envelope; unbound dropped [Risk R-11]."
    assert deviation["plan"] == "3.3: \"Claim plan: atomic claims bound to span ids from a structured envelope; unbound dropped [Risk R-11].\""
    if PLAN_PATH.exists():  # the plan sits beside the repository on the workstation; CI has the quotation only
        assert quoted in PLAN_PATH.read_text(encoding="utf-8")
    assert "one verbatim whole sentence" in deviation["applied"] and "Phase 5" in deviation["applied"]
    assert "**34. Task 3.3 \"atomic claims\"" in SPEC
    # The behaviour the reading describes: a clause cut from a sentence never binds (a cut can drop a negation).
    assert "not_verbatim" in contracts.BINDING_FAILURES


# ============================================================================================================ D3


def test_d3_plan_12_8_is_quoted_in_full_with_its_proposed_default_and_why_it_is_not_applied():
    retention = RAW["owner_decisions"]["PLAN-12.8"]
    full = "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted); proposed default release life plus 24 months."
    assert retention["text"] == full
    if PLAN_PATH.exists():
        plan = " ".join(PLAN_PATH.read_text(encoding="utf-8").split())
        assert full in plan
    assert (retention["proposed_default"], retention["proposed_default_applied"], retention["behaviour"]) == ("release life plus 24 months", False, "retain")
    assert "no release life has ended" in retention["why_not_applied"]
    assert "proposed default release life plus 24 months" in SPEC


# ============================================================================================================ D4


@pytest.mark.parametrize("mode", ["drop_all_claims", "drop_citations"])
def test_d4_a_rendering_without_claims_or_citations_never_answers(mode):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    import random

    always = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(3), modes=(mode,), outside_sentence="x", outside_span_id="span-" + "9" * 64)
    result = _run(TwoPassPipeline(engine, settings, renderer=always), IN_DOMAIN)
    assert (result.decision, result.abstention_reason, result.render_attempts) == ("abstain", "subset_check_failed", 3)
    assert result.entry.presentation.rendered_claim_ids == () and result.entry.presentation.rendered_span_ids == ()


class _DropLastClaim:
    """Leaves the last locked claim (and its citation markers) out: a partial rendering, which passes."""

    renderer_id = "template-renderer-v1"

    def render(self, locked, plan, *, attempt):
        from tutor_fakes import _relayout

        rendered = TemplateRenderer().render(locked, plan, attempt=attempt)
        last_line = max(segment.line for segment in rendered.segments if segment.kind == "claim")
        kept = [segment for segment in rendered.segments if segment.line != last_line]
        cited = tuple(dict.fromkeys(segment.span_id for segment in kept if segment.kind == "citation"))
        return _relayout(rendered, kept, cited)


def test_d4_the_ledger_records_which_claims_and_spans_the_answer_showed():
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    assert full.decision == "answer" and len(full.locked.claims) >= 2
    presentation = full.entry.presentation
    assert presentation.rendered_claim_ids == tuple(claim.claim_id for claim in full.locked.claims)
    assert presentation.rendered_span_ids == full.rendered.citations
    # A rendering that leaves a claim out still answers (spec 4.9: a subset), and the record says what it showed.
    partial = _run(TwoPassPipeline(engine, settings, renderer=_DropLastClaim()), MULTI_CLAIM)
    assert partial.decision == "answer" and partial.locked.claim_set_hash == full.locked.claim_set_hash
    shown = partial.entry.presentation.rendered_claim_ids
    assert len(shown) == len(partial.locked.claims) - 1 and set(shown) < {claim.claim_id for claim in partial.entry.claims}
    assert partial.entry.presentation.rendered_span_ids == partial.rendered.citations
    assert set(partial.entry.presentation.rendered_span_ids) <= set(partial.entry.span_ids)
    # The contract refuses an answer whose rendering showed nothing, or ids outside the record.
    payload = full.entry.model_dump(mode="json")
    for edit in ({"rendered_claim_ids": []}, {"rendered_span_ids": []}, {"rendered_claim_ids": ["claim-" + "0" * 32]}):
        changed = {**payload, "presentation": {**payload["presentation"], **edit}}
        with pytest.raises(ValidationError):
            contracts.LedgerEntry.model_validate(changed)


# ============================================================================================================ D5


def test_d5_every_record_stamps_the_budgets_in_force_and_whether_they_were_overridden():
    from app.services.ledger import LegacyDelivery

    delivery = LegacyDelivery(response_id=f"turn-{uuid4()}", decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
                              answer_sha256="0" * 64, retrieval_mode="lexical", provider="none", model="m", corpus_version="c", index_version="i",
                              gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0, policy_version="p")
    packaged = build_legacy_entry(delivery, settings=Settings(), package=PACKAGE, manifest_sha256=None).versions.budgets
    assert (packaged.shadow_ms, packaged.ledger_append_ms, packaged.overridden) == (None, PARAMS.ledger_append_budget_ms, ())
    overridden = build_legacy_entry(delivery, settings=Settings(tutor_ledger_append_budget_ms=700), package=PACKAGE, manifest_sha256=None)
    assert (overridden.versions.budgets.ledger_append_ms, overridden.versions.budgets.overridden) == (700, ("ledger_append_ms",))
    # A shadow record stamps the shadow budget it ran under.
    settings = Settings(two_pass_shadow_budget_ms=1500)
    result = _run(TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings), IN_DOMAIN, budget_ms=shadow_budget_ms(settings, PACKAGE))
    assert (result.entry.versions.budgets.shadow_ms, result.entry.versions.budgets.overridden) == (1500, ("shadow_ms",))
    unbounded = _run(TwoPassPipeline(RetrievalEngine(get_course_store(), Settings()), Settings()), IN_DOMAIN)
    assert (unbounded.entry.versions.budgets.shadow_ms, unbounded.entry.versions.budgets.overridden) == (None, ())


def test_d5_ready_reports_the_budgets_and_an_override_is_alerted(monkeypatch):
    body = client.get("/ready").json()
    assert body["tutor_pipeline"]["budgets"] == {"shadow_ms": PARAMS.shadow_budget_ms, "ledger_append_ms": PARAMS.ledger_append_budget_ms, "overridden": []}
    assert body["tutor_pipeline"]["subset_check"] == claim_gate.SUBSET_CHECK_RULE == PARAMS.subset_check
    recorded = []
    production = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"],
                  "guest_token_secret": "a-production-like-secret-of-sufficient-length"}
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", Settings(**production, two_pass_shadow_budget_ms=900, tutor_ledger_append_budget_ms=300))
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append(kwargs["details"]))
    main_module._record_configuration_overrides()
    assert recorded == [{"shadow_budget_overridden": True, "ledger_append_budget_overridden": True}]
    assert main_module._budget_fields(PACKAGE) == {"shadow_ms": 900, "ledger_append_ms": 300, "overridden": ["shadow_ms", "ledger_append_ms"]}


# ============================================================================================================ D6


def test_d6_flag_policy_is_marked_provisional_and_the_loader_requires_it():
    assert RAW["flag_policy"]["provisional"] is True and "PD-10" in RAW["flag_policy"]["authority"]
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    payload["flag_policy"].pop("provisional")
    with pytest.raises(ConfigPackageError, match="flag_policy must be marked provisional"):
        parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    # The new route limits are the existing routes' limits, recorded as PD-11 engineering parameters. Since spec 18.10
    # H5 POST /tutor/turns has no limit of its own: it shares POST /assistant/chat's window and limit.
    settings = Settings()
    assert settings.ledger_rate_limit == settings.spans_rate_limit and not hasattr(settings, "tutor_turns_rate_limit")
    source = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert "provisional (PD-11" in source


# ============================================================================================================ D7


def test_d7_the_records_say_what_the_code_does():
    adr5 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
    assert "NFKC normalisation" not in adr5 and "never NFKC-folded" in adr5 and claim_gate.SUBSET_CHECK_RULE in adr5
    # The spec names the sentence rule in force wherever it states the binding or the evidential rule.
    for stale in ("sentences_v1(span.text)", '"sentence_rule": "sentences-v1"', "a whole `sentences-v1` sentence of every cited span"):
        assert stale not in SPEC, stale
    assert RAW["tutor_pipeline"]["evidential"]["sentence_rule"] == "sentences-v2"


# ============================================================================================================ D8


def _appender(database_url: str):
    factory, engine = fresh_sessions(database_url)
    return factory, engine


def test_d8_appends_that_commit_between_the_checks_statements_never_break_a_sound_chain(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    writer_factory, writer_engine = _appender(fresh_database_url)
    try:
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        selects = []

        def append_between_statements(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)
                if len(selects) > 1:  # after the first read, an append commits before every later statement
                    append_ledger_entry(make_entry(), session_factory=writer_factory, budget_ms=5000)

        event.listen(engine, "before_cursor_execute", append_between_statements)
        try:
            with factory() as db:
                check = verify_response_ledger(db)
        finally:
            event.remove(engine, "before_cursor_execute", append_between_statements)
        assert check.ok, check.problems
        assert check.count == 3 and check.head_row[0] == 3 and check.appended_during_check >= 1
        with factory() as db:
            quiet = verify_response_ledger(db)
        assert quiet.ok and quiet.count == 3 + len(selects) - 1 and quiet.appended_during_check == 0
    finally:
        engine.dispose()
        writer_engine.dispose()


def test_d8_checks_under_live_traffic_all_pass(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    writer_factory, writer_engine = _appender(fresh_database_url)
    stop = threading.Event()
    errors: list[BaseException] = []

    def traffic():
        while not stop.is_set():
            try:
                append_ledger_entry(make_entry(), session_factory=writer_factory, budget_ms=5000)
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)
                return
            time.sleep(0.005)

    try:
        for _ in range(40):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        writer = threading.Thread(target=traffic)
        writer.start()
        try:
            results = []
            for _ in range(8):
                with factory() as db:
                    results.append(verify_response_ledger(db))
        finally:
            stop.set()
            writer.join(30)
        assert not errors, errors
        assert all(result.ok for result in results), [result.problems for result in results if not result.ok]
    finally:
        engine.dispose()
        writer_engine.dispose()


def test_d8_a_record_past_the_head_and_a_missing_head_are_still_problems(fresh_database_url):
    from test_phase3_acceptance import guards_lifted

    factory, engine = fresh_sessions(fresh_database_url)
    try:
        appended = [append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000) for _ in range(3)]
        with guards_lifted(engine):
            with engine.begin() as connection:
                connection.execute(text("UPDATE response_ledger_head SET seq = 2, record_hash = :h"), {"h": appended[1].record_hash})
        with factory() as db:
            check = verify_response_ledger(db)
        assert not check.ok and "seq 3 lies past the chain head (seq 2)" in check.problems
        with guards_lifted(engine):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM response_ledger_head"))
        with factory() as db:
            check = verify_response_ledger(db)
        assert not check.ok and "the chain head is missing" in check.problems
    finally:
        engine.dispose()


# ============================================================================================================ D9


def test_d9_public_ready_shows_no_per_run_shadow_output(clean_metrics):
    before = client.get("/ready").json()["slis"]["two_pass_shadow"]
    response = client.post("/assistant/chat", headers={"x-demo-user": f"review3-{uuid4().hex[:10]}", "x-demo-role": "learner",
                                                       "x-forwarded-for": f"review3-{uuid4().hex}"}, json={"message": IN_DOMAIN})
    assert response.status_code == 200
    after = client.get("/ready").json()["slis"]["two_pass_shadow"]
    assert set(before) == set(after) == set(PUBLIC_SHADOW_FIELDS)
    # Review round 4 (spec 18.7 E15) also took out completed, failed and the stop flag, which still told a learner
    # whether their own turn's run completed, where it failed and whether it tripped the stop.
    for hidden in ("decisions", "abstention_by_reason", "proposed_claims", "bound_claims", "bound_claim_ratio", "render_regenerations", "budget_exceeded",
                   "completed", "failed", "bound_claim_ratio_stop"):
        assert hidden not in after
    # The detail still exists in process (and in each run's log line) for operators and tests.
    assert TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)["scheduled"] == after["scheduled"]


# =========================================================================================================== D10


def test_d10_no_code_claims_a_qa_record_is_unlinkable_while_the_qa_row_exists():
    sources = {
        "ledger.py": (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8"),
        "qa_engine.py": (API_ROOT / "app" / "services" / "qa_engine.py").read_text(encoding="utf-8"),
        "contracts.py": (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8"),
        "verify_ledger.py": (REPO_ROOT / "scripts" / "verify_ledger.py").read_text(encoding="utf-8"),
        "deployment.md": (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8"),
    }
    for name, source in sources.items():
        for claim in ("unlinkable from the start", "holds no learner link", "no learner link is stored", "with no learner link",
                      "holds no link to its Q&A row"):
            assert claim not in source, (name, claim)
    assert "rendered_text_sha256 is its sha256" in sources["ledger.py"]


# =========================================================================================================== D11


def test_d11_the_pydantic_floor_is_declared_and_the_start_up_probe_holds():
    import pydantic

    from app import schemas

    requirements = (API_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "pydantic>=2.12.4,<3" in [line.strip() for line in requirements]
    major, minor, patch = (int(part) for part in pydantic.VERSION.split(".")[:3])
    assert (major, minor, patch) >= (2, 12, 4)
    assert "value" not in schemas._ExcludeIfProbe().model_dump()
    assert schemas.AssistantChatResponse.model_fields["evidence"].exclude_if is not None


# =========================================================================================================== D12


def test_d12_the_required_api_postgres_check_still_reports_under_the_driver_matrix():
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    # P1-D-12: the required checks on main are api-and-evaluation, api-postgres and frontend, by job name.
    for required in ("api-and-evaluation", "api-postgres", "frontend"):
        assert required in jobs and "strategy" not in jobs[required] and "name" not in jobs[required], required
    legs = jobs["api-postgres-driver"]
    assert legs["strategy"]["matrix"]["driver"] == ["psycopg", "pg8000"] and legs["name"] == "api-postgres (${{ matrix.driver }})"
    gate = jobs["api-postgres"]
    assert gate["needs"] == ["api-postgres-driver"] and gate["if"] == "always()"
    assert gate["steps"] == [{"run": 'test "${{ needs.api-postgres-driver.result }}" = "success"'}]


# =========================================================================================================== D13


def _worker(database_url: str, *args: str) -> tuple[int, dict | None, str]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    lines = [line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line]
    return completed.returncode, (json.loads(lines[-1][lines[-1].index("{"):]) if lines else None), completed.stderr


def test_d13_the_in_image_worker_runs_coverage_and_export(fresh_database_url, tmp_path):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        # Spec 18.12 J5: the turns are older than the 360 s attempt horizon, so the one without a record is unrecorded
        # (a newer one would be pending: its append may still be running).
        since = datetime.now(UTC) - timedelta(hours=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review3-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            turns = [f"turn-{uuid4()}" for _ in range(2)]
            for turn_id in turns:
                # Made by a Phase 3 image with the ledger on (spec 18.8 F12): each expects a record.
                db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                                 model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                                 policy_version="p", created_at=datetime.now(UTC) - timedelta(minutes=10), ledger_record_expected=True))
            db.commit()
        append_ledger_entry(make_entry(turns[0]), session_factory=factory, budget_ms=5000)
        export_path = tmp_path / "ledger-export.jsonl"
        code, report, _ = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--export", str(export_path))
        assert code == 0 and report["status"] == "ok" and report["records"] == 1
        assert (report["coverage"]["turns_since"], report["coverage"]["unrecorded"], report["coverage"]["pending"]) == (2, 1, 0)
        assert report["exported"] == {"rows": 1} and json.loads(export_path.read_text(encoding="utf-8").splitlines()[0])["response_id"] == turns[0]
        assert fresh_database_url not in json.dumps(report)
        inside = REPO_ROOT / "ledger-export-review3.jsonl"
        code, report, _ = _worker(fresh_database_url, "--export", str(inside))
        assert code == 2 and report["status"] == "usage" and not inside.exists()
        code, report, _ = _worker(fresh_database_url, "--coverage-since", "not-a-time")
        assert code == 2 and report["status"] == "usage"
    finally:
        engine.dispose()


def test_d13_the_runbook_runs_production_ledger_steps_through_the_worker():
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    assert "python -m app.workers.response_ledger --export" in runbook
    assert "python -m app.workers.response_ledger --coverage-since" in runbook
    assert "TUTOR_LEDGER_ENABLED=false" in runbook and "CPU" in runbook
    assert "scripts/verify_ledger.py --export" not in runbook
    # Review round 4 (spec 18.7 E9): the text an operator sees when the downgrade refuses names the worker too.
    migration = (API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py").read_text(encoding="utf-8")
    assert "scripts/verify_ledger.py --export" not in migration and "python -m app.workers.response_ledger --export" in migration


def test_d13_a_postgres_append_that_stalls_holding_the_head_lock_is_ended_by_the_server(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    seen: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    try:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=1500)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        if engine.dialect.name != "postgresql":
            assert not any(statement.startswith("SET LOCAL") for statement in seen)
            return
        timeout = next(statement for statement in seen if statement.startswith("SET LOCAL idle_in_transaction_session_timeout"))
        first_read = next(index for index, statement in enumerate(seen) if statement.startswith("SELECT response_ledger.seq"))
        assert seen.index(timeout) < first_read and 0 < int(timeout.split("'")[1].removesuffix("ms")) <= 1500
        # A process that stalls after SELECT ... FOR UPDATE: the server ends its session, which frees the head row.
        stalled = []

        def stall_after_the_head_lock(conn, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE" in statement and not stalled:
                stalled.append(1)
                time.sleep(1.5)

        event.listen(engine, "after_cursor_execute", stall_after_the_head_lock)
        try:
            with pytest.raises(Exception):
                append_ledger_entry(make_entry(), session_factory=factory, budget_ms=400, attempts=1)
        finally:
            event.remove(engine, "after_cursor_execute", stall_after_the_head_lock)
        started = time.monotonic()
        other = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=1500)
        assert other.seq == 2 and time.monotonic() - started < 1.5  # the lock was released; the chain did not fork
        with factory() as db:
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()
