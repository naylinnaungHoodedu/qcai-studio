"""V1.5, abstention below the floor and the X4 mark (Phase 4 spec 4.6, conflict 19; M11; R-15)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline.contracts import GATE_ABSTENTION_REASONS, NO_QUOTABLE_EVIDENCE, Sufficiency
from app.services.v1_checks.v1_5_abstention import check_v1_5, x4_margin
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

PACKAGE = get_config_package(Settings())


def _sufficiency(decision: str, reason: str = "evidence", gate: str = "bm25f-v1") -> Sufficiency:
    return Sufficiency(score=None if decision == "abstain" else 5.0, gate=gate, threshold_version="t", floor=2.35, margin=2.4, decision=decision, reason=reason)


@pytest.mark.parametrize("reason", [*GATE_ABSTENTION_REASONS, "corpus_version_mismatch", NO_QUOTABLE_EVIDENCE])
def test_the_gate_s_abstention_is_v1_5_s_with_its_reason(reason):
    result = check_v1_5(_sufficiency("abstain", reason))
    assert (result.outcome, result.reason_code, result.ehmf_types, result.claim_id) == ("abstain", reason, ("A",), None)


def test_near_miss_marks_and_answer_passes():
    assert (check_v1_5(_sufficiency("near_miss")).outcome, check_v1_5(_sufficiency("near_miss")).reason_code) == ("mark", "near_miss")
    assert check_v1_5(_sufficiency("answer")).reason_code == "answer"


def test_p1_floor_never_marks_and_the_x4_margin_is_the_package_s():
    assert x4_margin(PACKAGE, "bm25f-v1") == PACKAGE.abstention.margin == 2.4
    assert x4_margin(PACKAGE, "p1-floor") == 0.0
    from app.services.content_assembler import CourseStore
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline

    settings = Settings(retrieval_gate="p1-floor")
    result = run(TwoPassPipeline(RetrievalEngine(CourseStore(settings), settings), settings), MULTI_CLAIM)
    assert result.bundle.sufficiency.margin == 0.0 and result.bundle.sufficiency.decision != "near_miss"
    assert [r.outcome for r in result.entry.verification.checks if r.check_id == "V1.5"] in (["pass"], ["abstain"])


def test_a_marked_response_is_labelled_near_floor_and_its_claims_carry_an_x4_intent(monkeypatch):
    from app.services.tutor_pipeline import pipeline as pipeline_module

    real = pipeline_module.retrieve

    def near(engine, request, **kwargs):
        bundle = real(engine, request, **kwargs)
        return bundle.model_copy(update={"sufficiency": bundle.sufficiency.model_copy(update={"decision": "near_miss"})})

    monkeypatch.setattr(pipeline_module, "retrieve", near)
    record = run(dev_pipeline(), MULTI_CLAIM).entry.verification
    assert "near_floor" in record.labels
    assert record.verdicts and all(v.v3 is not None and "x4_margin" in v.v3.reasons and v.v3.trigger == "X4" for v in record.verdicts)
