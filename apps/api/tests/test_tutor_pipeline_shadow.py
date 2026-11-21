"""Phase 3: the shadow runner's log line and the public /ready shadow block (plan Phase 3 I and L; AC-3-6; spec 4.11,
11.3).

D1  the shadow log line carries the plan L bound-claim ratio terms (/ready's), so the cross-instance SLI cannot raise a
    false stop on a merge or a budget overrun.
D9  public /ready carries no per-run shadow output.
E15 public /ready carries no shadow field that changes with a run's outcome.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.db_models import TutorMessage, TutorThread
from app.main import app
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import PresentationPlan
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, LICENSE_METRICS, PUBLIC_SHADOW_FIELDS, TWO_PASS_METRICS
from app.services.tutor_pipeline.pipeline import TwoPassPipeline
from app.services.tutor_pipeline.shadow import ShadowJob, run_shadow


DATA = Path(__file__).parent / "data"
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
REGRESSION_QUERY = json.loads((DATA / "phase3_replay_regressions.json").read_text(encoding="utf-8"))["items"][0]["query"]
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
client = TestClient(app)
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()
    yield
    LEDGER_METRICS.reset()
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


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"review4-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"review4-{uuid4().hex}"}


# =============================================================================================================== D1


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


# =============================================================================================================== D9


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


# ============================================================================================================== E15


def test_e15_public_ready_carries_no_shadow_field_that_changes_with_a_runs_outcome(clean_metrics):
    LICENSE_METRICS.reset()
    before = client.get("/ready").json()["slis"]
    response = client.post("/assistant/chat", headers=fresh(demo("e15")), json={"message": IN_DOMAIN})
    assert response.status_code == 200
    after = client.get("/ready").json()["slis"]
    assert set(after["two_pass_shadow"]) == set(PUBLIC_SHADOW_FIELDS) == {"scheduled", "phase2_bound_claim_ratio_baseline"}
    ledger_block = after["tutor_ledger"]
    assert set(ledger_block["attempted"]) == set(ledger_block["appended"]) == set(ledger_block["failed"]) == {"legacy"}
    assert set(ledger_block["non_public_spans_excluded"]) == {"legacy", "qa"}
    # Only what the turn itself did changes: one shadow scheduled, one legacy record.
    assert after["two_pass_shadow"]["scheduled"] == before["two_pass_shadow"]["scheduled"] + 1
    assert ledger_block["appended"]["legacy"] == before["tutor_ledger"]["appended"]["legacy"] + 1
    # The shadow's outcome stays in process.
    detail = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert {"completed", "failed", "bound_claim_ratio_stop"} <= set(detail) and LEDGER_METRICS.snapshot()["attempted"]["shadow"] >= 0
    for hidden in ("completed", "failed", "bound_claim_ratio_stop", "decisions", "bound_claim_ratio"):
        assert hidden not in after["two_pass_shadow"]
    assert "/ready` `slis.two_pass_shadow` holds only `scheduled` and `phase2_bound_claim_ratio_baseline`" in OBSERVABILITY
