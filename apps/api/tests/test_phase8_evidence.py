"""Phase 8 synthetic evidence, import isolation, and shared adaptation control."""

import ast
import json
import re
from string import Formatter
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db_models import Base, LearnerAdaptationStop, LearnerAssessmentFact, QuizAttempt
from app.schemas import LearnerConsentRecord
from app.services.erasure import user_keyed_tables
from app.services.learner_record_privacy import retention_classes, set_consent
from app.services.learner_record_shadow import clear_adaptation_stop, shadow_presentation, stop_adaptation
from scripts.prove_erasure import compute as prove_erasure
from scripts.run_invariance_harness import LEARNER_FIELDS, compute as run_harness


ROOT = Path(__file__).resolve().parents[3]


def test_ac_8_3_three_mastery_levels_yield_identical_claim_set_cited_spans_and_decision():
    proof = run_harness(subset=3)
    assert proof["items"] >= 3 and len(set(proof["plans"])) == 3
    assert not proof["violations"] and not proof["f2_fields"]
    assert len(set(proof["observation_sha256"])) == 1
    assert proof["items_with_distinct_rendering"] > 0


def test_ac_8_4_evidential_prompts_and_the_abstention_configuration_hold_zero_learner_state_fields():
    from app.services.tutor_pipeline.evidential import EXTRACTIVE_RULE

    slots = {field for _, field, _, _ in Formatter().parse(EXTRACTIVE_RULE) if field}
    assert not slots & LEARNER_FIELDS
    assert not run_harness(subset=3)["f2_fields"]


def test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected(monkeypatch):
    from app.services.tutor_pipeline import pipeline

    original = pipeline.build_envelope

    def builder(*args, **kwargs):
        result = original(*args, **kwargs)
        if result is None:
            return None
        instructions = result.instructions.model_copy(update={"rule_id": "fixture stepwise"})
        return result.model_copy(update={"instructions": instructions})

    monkeypatch.setattr(pipeline, "build_envelope", builder)
    assert "learner-value" in run_harness(subset=3)["f2_fields"]


def test_plan_p_the_harness_takes_the_item_set_and_the_generation_design_as_inputs(tmp_path):
    from scripts.replay_tutor_plans import fixture_items

    path = tmp_path / "public-pair.json"
    path.write_text(json.dumps([query for _, query in fixture_items()[:2]]), encoding="utf-8")
    report = run_harness(items_path=path, design="two-pass")
    assert report["items"] == 2 and report["item_set"] == path.name and report["design"] == "two-pass"


def test_plan_i_a_harness_violation_writes_a_shared_stop_and_security_event(tmp_path, monkeypatch, caplog):
    import sys
    from sqlalchemy import select
    from app.core.structured_logging import FIELDS
    from app.db_models import SecurityEvent
    from scripts import run_invariance_harness as harness

    path = tmp_path / "dev-stop.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(engine)
        monkeypatch.setattr(sys, "argv", ["harness", "--probe", "--stop-sqlite", str(path)])
        monkeypatch.setattr(harness, "compute", lambda *args, **kwargs: {
            "items": 1, "violations": [{"fields": ["evidence"]}], "f2_fields": [], "plans": ["concise"],
            "items_with_distinct_rendering": 0,
        })
        caplog.set_level("INFO")
        assert harness.main() == 3
        with Session(engine) as db:
            assert db.get(LearnerAdaptationStop, "planner").reason == "invariance"
            assert db.scalar(select(SecurityEvent.event_type).order_by(SecurityEvent.seq)) == "learner.harness.stop"
        assert {"event": "learner.harness.violation", "reason": "invariance"} in [
            getattr(row, FIELDS, None) for row in caplog.records
        ]
    finally:
        engine.dispose()


def test_plan_d_task_4_leaves_one_learner_state_presentation_path():
    from app.services import learner_record

    assert not hasattr(learner_record, "build_pedagogical_context")
    for name in ("adr/ADR-001-grounding-separation.md", "architecture/phase3-implementation-spec.md"):
        assert "build_pedagogical_context" not in (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_ac_8_4_no_evidential_or_verifier_module_imports_a_phase8_module():
    app = ROOT / "apps" / "api" / "app"
    for directory in ("services/tutor_pipeline", "services/v1_checks", "services/v2_panel", "gateway"):
        for path in (app / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                names = [item.name for item in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                assert not any("learner_record" in name or "phase8_settings" in name for name in names), path.name


def test_plan_f_the_committed_erasure_proof_matches_a_fresh_run():
    saved = ROOT / "docs" / "evaluation" / "phase8" / "erasure_proof_v1.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == prove_erasure()


def test_plan_p_the_committed_invariance_report_matches_a_fresh_run():
    saved = ROOT / "docs" / "evaluation" / "phase8" / "invariance_harness_report_v1.json"
    expected = json.loads(saved.read_text(encoding="utf-8"))
    fresh = run_harness()
    # The CLI additionally verifies the exact module set imported by the standalone process.
    assert {k: v for k, v in fresh.items() if k != "inputs"} == {k: v for k, v in expected.items() if k != "inputs"}


def test_phase8_docs_the_consent_schema_matches_the_record_model():
    schema = ROOT / "docs" / "security" / "consent-record.v1.schema.json"
    assert json.loads(schema.read_text(encoding="utf-8")) == LearnerConsentRecord.model_json_schema()


def test_plan_j_all_user_keyed_tables_have_a_retention_class():
    assert set(retention_classes()) == {table.name for table in user_keyed_tables()}


def test_ac_8_7_the_privacy_inventory_equals_the_cookies_and_storage_keys_in_code():
    api = ROOT / "apps" / "api" / "app"
    frontend = ROOT / "apps" / "frontend" / "src"
    frontend_sources = [path.read_text(encoding="utf-8") for path in frontend.rglob("*") if path.suffix in {".ts", ".tsx"}]
    api_sources = [path.read_text(encoding="utf-8") for path in api.rglob("*.py")]
    disclosures = (frontend / "lib" / "privacy-disclosures.ts").read_text(encoding="utf-8")
    cookie = r"""["'`](qcai_[a-z0-9_]+)["'`]"""
    key = r"""["'`](qcai-[a-z0-9-]+)["'`]"""
    storage_sources = (
        r"(?:local|session)Storage\.(?:setItem|getItem|removeItem)\(\s*" + key,
        r"const \w*STORAGE_KEY\w* = " + key,
    )
    assert set(re.findall(r"name:\s*" + cookie, disclosures)) == set(re.findall(cookie, "\n".join(frontend_sources + api_sources)))
    assert set(re.findall(r"key:\s*" + key, disclosures)) == {
        match for pattern in storage_sources for source in frontend_sources for match in re.findall(pattern, source)
    }


def test_phase8_durable_stop_is_visible_to_a_new_session(fresh_database_url):
    engine = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(engine)
        subject = f"demo-{uuid4().hex}"
        with Session(engine) as first:
            set_consent(first, "demo", subject, "adaptation", True, Settings(_env_file=None))
            attempt = QuizAttempt(user_id=subject, lesson_slug="first", score=1, responses={})
            first.add(attempt)
            first.flush()
            first.add(LearnerAssessmentFact(attempt_id=attempt.id, user_id=subject, lesson_slug="first", mastery=0.9))
            stop_adaptation(first, "invariance")
            first.commit()
        with Session(engine) as second:
            assert second.get(LearnerAdaptationStop, "planner").reason == "invariance"
            assert shadow_presentation(second, "demo", subject, ("first", "second"), "concise").lesson_order == (
                "first", "second",
            )
            clear_adaptation_stop(second)
            second.commit()
        with Session(engine) as third:
            assert third.get(LearnerAdaptationStop, "planner") is None
            assert shadow_presentation(third, "demo", subject, ("first", "second"), "concise").plan_id == "socratic"
    finally:
        engine.dispose()
