"""V1.5, abstention below the floor and the X4 mark (Phase 4 spec 4.6, conflict 19; M11; R-15)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package, load_config_package
from app.services.tutor_pipeline.contracts import GATE_ABSTENTION_REASONS, NO_QUOTABLE_EVIDENCE, Sufficiency
from app.services.v1_checks.v1_5_abstention import check_v1_5, x4_margin
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

PACKAGE = get_config_package(Settings())
FLOOR, MARGIN = 2.35, 2.4


def _sufficiency(decision: str, reason: str = "evidence", gate: str = "bm25f-v1", score: float | None = 5.0) -> Sufficiency:
    return Sufficiency(score=None if decision == "abstain" else score, gate=gate, threshold_version="t", floor=FLOOR, margin=MARGIN,
                       decision=decision, reason=reason)


@pytest.mark.parametrize("reason", [*GATE_ABSTENTION_REASONS, "corpus_version_mismatch", NO_QUOTABLE_EVIDENCE])
def test_the_gate_s_abstention_is_v1_5_s_with_its_reason(reason):
    result = check_v1_5(_sufficiency("abstain", reason), x4_margin=MARGIN)
    assert (result.outcome, result.reason_code, result.ehmf_types, result.claim_id) == ("abstain", reason, ("A",), None)


def test_near_miss_marks_and_answer_passes():
    # A top score within the X4 margin above the floor marks; one at or past floor + margin passes.
    near = check_v1_5(_sufficiency("near_miss", score=FLOOR + MARGIN / 2), x4_margin=MARGIN)
    assert (near.outcome, near.reason_code) == ("mark", "near_miss")
    assert check_v1_5(_sufficiency("answer", score=FLOOR + MARGIN), x4_margin=MARGIN).reason_code == "answer"
    assert check_v1_5(_sufficiency("answer", score=5.0), x4_margin=MARGIN).reason_code == "answer"


def test_v1_5_applies_the_configured_x4_margin_whatever_margin_the_gate_flags_with(tmp_path):
    # Plan Phase 4 B ("V1.3, X4 and V1.9 values set as operator policy (Q-22)") and D ("Thresholds load from
    # configuration [Risk R-46]"): the X4 margin is the package's, per gate, and V1.5 applies it. With the shipped values
    # (bm25f-v1: abstention.margin; p1-floor: 0.0) it marks exactly what the gate flags near_floor; an owner value moves
    # the mark with no code change, under either gate.
    score = FLOOR + 1.0
    assert check_v1_5(_sufficiency("near_miss", score=score), x4_margin=MARGIN).outcome == "mark"
    assert check_v1_5(_sufficiency("near_miss", score=score), x4_margin=0.5).outcome == "pass"
    assert check_v1_5(_sufficiency("answer", score=score, gate="p1-floor"), x4_margin=0.0).outcome == "pass"
    assert check_v1_5(_sufficiency("answer", score=score, gate="p1-floor"), x4_margin=1.5).outcome == "mark"
    raw = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    raw["v1"]["v1_5"]["x4_margin"] = {"bm25f-v1": 1.0, "p1-floor": 1.5}
    path = tmp_path / "v3.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "v3.json.sha256").write_text(canonical_sha256(raw) + "\n", encoding="utf-8")
    owner = load_config_package(path, governed=False)
    assert dict(owner.v1.x4_margin) == {"bm25f-v1": 1.0, "p1-floor": 1.5} and owner.abstention.margin == MARGIN
    assert x4_margin(owner, "p1-floor") == 1.5
    # The runner reads the package's margin for the bundle's gate.
    pipeline = dev_pipeline()
    pipeline.v1_params = dataclasses.replace(pipeline.v1_params, x4_margin={"bm25f-v1": 1000.0, "p1-floor": 0.0})
    record = run(pipeline, MULTI_CLAIM).entry.verification
    assert [r.outcome for r in record.checks if r.check_id == "V1.5"] == ["mark"] and "near_floor" in record.labels


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
        sufficiency = bundle.sufficiency
        return bundle.model_copy(update={"sufficiency": sufficiency.model_copy(update={"decision": "near_miss", "score": sufficiency.floor})})

    monkeypatch.setattr(pipeline_module, "retrieve", near)
    record = run(dev_pipeline(), MULTI_CLAIM).entry.verification
    assert "near_floor" in record.labels
    assert record.verdicts and all(v.v3 is not None and "x4_margin" in v.v3.reasons and v.v3.trigger == "X4" for v in record.verdicts)
