"""V1.5, abstention below the floor and the X4 mark (Phase 4 spec 4.6, conflict 19; M11; R-15)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package, load_config_package
from app.services.tutor_pipeline.contracts import GATE_ABSTENTION_REASONS, NO_QUOTABLE_EVIDENCE, Sufficiency
from app.services.v1_checks.v1_5_abstention import check_v1_5, x4_margin
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

PACKAGE = get_config_package(Settings())
FLOOR, MARGIN = 2.35, 2.4
P1_FLOOR = 6.0  # P1-D-04's floor, which p1-floor applies to the P1 floor score
DATA = Path(__file__).parent / "data"


def _fixture_queries() -> list[str]:
    fixture = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
    return [item["query"] for item in fixture["in_domain"]]


def _p1_sufficiency(score: float) -> Sufficiency:
    # What a p1-floor bundle records: the top result's P1 floor score against floor 6 and margin 0 (Phase 4 spec 4.6).
    return Sufficiency(score=score, gate="p1-floor", threshold_version="score-floor-p1-v1", floor=P1_FLOOR, margin=0.0,
                       decision="answer", reason="evidence")


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
    # An answered bundle that records no score cannot be shown to clear the margin: it marks (the conservative side).
    assert check_v1_5(Sufficiency(score=None, gate="bm25f-v1", threshold_version="t", floor=FLOOR, margin=MARGIN,
                                  decision="answer", reason="evidence"), x4_margin=MARGIN).outcome == "mark"


def test_v1_5_applies_the_configured_x4_margin_whatever_margin_the_gate_flags_with(tmp_path):
    # Plan Phase 4 B ("V1.3, X4 and V1.9 values set as operator policy (Q-22)") and D ("Thresholds load from
    # configuration [Risk R-46]"): the X4 margin is the package's, per gate, and V1.5 applies it. With the shipped values
    # (bm25f-v1: abstention.margin; p1-floor: 0.0) it marks exactly what the gate flags near_floor; an owner value moves
    # the mark with no code change, under either gate. A p1-floor sufficiency is what that gate records: the P1 floor
    # score against floor 6 (test_p1_floor_x4_margin_applies_to_the_floor_score_of_a_real_bundle builds real ones).
    score = FLOOR + 1.0
    assert check_v1_5(_sufficiency("near_miss", score=score), x4_margin=MARGIN).outcome == "mark"
    assert check_v1_5(_sufficiency("near_miss", score=score), x4_margin=0.5).outcome == "pass"
    assert check_v1_5(_p1_sufficiency(P1_FLOOR), x4_margin=0.0).outcome == "pass"
    assert check_v1_5(_p1_sufficiency(P1_FLOOR + 1.0), x4_margin=1.5).outcome == "mark"
    assert check_v1_5(_p1_sufficiency(P1_FLOOR + 2.0), x4_margin=1.5).outcome == "pass"
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


def test_p1_floor_x4_margin_applies_to_the_floor_score_of_a_real_bundle():
    # Plan Phase 4 D "below score floor; within margin X4 mark": under p1-floor (the gate outside development) the floor
    # (P1-D-04's 6) applies to the P1 floor score, not to the ranking score, which adds the module boost and substring
    # hits of every query term. The bundle records the top result's floor score, so an owner X4 margin marks a top
    # result just above the floor, under real p1-floor bundles.
    from app.core.corpus_governance import get_corpus_registry
    from app.services.content_assembler import CourseStore
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.tutor_pipeline.contracts import RetrievalRequest
    from app.services.tutor_pipeline.retrieve import retrieve, sufficiency_of

    settings = Settings(retrieval_gate="p1-floor")
    store = CourseStore(settings)
    engine = RetrievalEngine(store, settings)
    registry = get_corpus_registry(settings)
    rows = []
    for query in _fixture_queries():
        bundle = retrieve(engine, RetrievalRequest(text=query, corpus_version=store.corpus_version), top_k=4, registry=registry)
        if bundle.sufficiency.decision == "abstain":
            continue
        top = bundle.spans[0]
        floor_score = store.index.p1_scores(query, store.entry(top.span_id), None)[1]
        sufficiency = bundle.sufficiency
        assert (sufficiency.gate, sufficiency.floor, sufficiency.margin, sufficiency.decision) == ("p1-floor", P1_FLOOR, 0.0, "answer")
        assert sufficiency.score == floor_score >= P1_FLOOR, query
        # The legacy record's sufficiency (the learner-facing search behind a contained answer) records the same score.
        assert sufficiency_of(engine.search(query, top_k=4), threshold_version="t").score == floor_score, query
        rows.append((query, sufficiency, top.score))
    assert len(rows) > 100
    at_floor = [row for row in rows if row[1].score == P1_FLOOR]
    clear = [row for row in rows if row[1].score >= P1_FLOOR + 2.0]
    assert at_floor and clear
    # The ranking score of a top result at the floor is well above floor + 1, so comparing it would never mark.
    assert all(ranking >= P1_FLOOR + 1.0 for _, _, ranking in at_floor)
    for query, sufficiency, _ in at_floor:
        assert check_v1_5(sufficiency, x4_margin=1.0).outcome == "mark", query
        assert check_v1_5(sufficiency, x4_margin=0.0).outcome == "pass", query
    for query, sufficiency, _ in clear:
        assert check_v1_5(sufficiency, x4_margin=1.0).outcome == "pass", query


def test_v1_5_marks_a_top_score_the_display_rounding_would_lift_to_floor_plus_margin():
    # The gate flags near_floor on the 9-digit score; a span's display score is rounded to 4 digits. A top score in
    # [floor + margin - 5e-5, floor + margin) is near_floor although its display score reaches floor + margin; the
    # bundle records the 9-digit score, so V1.5 with the shipped X4 margin (the gate's) marks exactly what the gate flags.
    from app.core.corpus_governance import get_corpus_registry
    from app.services.content_assembler import CourseStore
    from app.services.lexical_index import LexicalIndex
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.tutor_pipeline.contracts import RetrievalRequest
    from app.services.tutor_pipeline.retrieve import retrieve

    settings = Settings()
    store = CourseStore(settings)
    assert store.gate == "bm25f-v1"
    registry = get_corpus_registry(settings)
    margin = store.package.abstention.margin
    for query in _fixture_queries():
        decision = store.index.evaluate(query, top_k=4)
        if decision.results and round(decision.results[0].score, 4) > decision.results[0].score:
            raw = decision.results[0].score
            break
    else:  # pragma: no cover - the fixture always has one
        pytest.fail("no fixture query whose top score rounds up")
    display = round(raw, 4)
    floor = (raw + display) / 2 - margin  # floor + margin lies strictly between the raw and the display score
    assert raw < floor + margin <= display
    store.index = LexicalIndex(store.chunks, store.package.retrieval, dataclasses.replace(store.package.abstention, floor=floor), gate="bm25f-v1")
    engine = RetrievalEngine(store, settings)
    response = engine.evidence(query, top_k=4)
    assert response.results[0].near_floor and response.results[0].score == display >= floor + margin
    bundle = retrieve(engine, RetrievalRequest(text=query, corpus_version=store.corpus_version), top_k=4, registry=registry)
    assert (bundle.sufficiency.decision, bundle.sufficiency.score) == ("near_miss", raw)
    result = check_v1_5(bundle.sufficiency, x4_margin=x4_margin(PACKAGE, "bm25f-v1"))
    assert (result.outcome, result.reason_code) == ("mark", "near_miss")
