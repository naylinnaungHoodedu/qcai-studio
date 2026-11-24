"""Compare evidence and final decisions across three synthetic presentation choices."""

import argparse
from collections.abc import Mapping
from dataclasses import fields
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from scripts.run_v2_fixtures import Environment, _gateway, _pipeline, run_inputs
from scripts.replay_tutor_plans import FIXTURE, REGRESSIONS, _commit, fixture_items, regression_items

from app.core.config_package import canonical_sha256, get_config_package
from app.core.phase8_settings import LEVELS
from app.gateway.contracts import AlignmentRequest
from app.schemas import (
    LearnerConsentRecord, LearnerRecordOperationInput, LearnerRecordOperationsRequest, LearnerRecordRead,
    LearnerReplicaIssued, LearnerReplicaRequest,
)
from app.services.learner_record_metrics import record_signal
from app.services.learner_record_planner import LearnerPresentation, plan_presentation
from app.services.tutor_pipeline.contracts import LEARNER_STATE_FIELDS, PresentationPlan
from app.services.tutor_pipeline.pipeline import PipelineInput
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.v2_panel.cache import ProcessEvidentialCache


LEARNER_FIELDS = frozenset(LEARNER_STATE_FIELDS).union(
    (field.name for field in fields(LearnerPresentation)),
    LearnerRecordRead.model_fields, LearnerRecordOperationInput.model_fields, LearnerRecordOperationsRequest.model_fields,
    LearnerConsentRecord.model_fields, LearnerReplicaIssued.model_fields, LearnerReplicaRequest.model_fields,
    {"subject_id", "receipt_id", "principal_digest", "erasure_epoch", "id"},
)
PLANNER_VALUE = re.compile(r"(?<![\w.])(?:concise|stepwise|socratic|0\.[159])(?![\w.])", re.IGNORECASE)


def learner_fields(value, *, scan_values: bool = False):
    if isinstance(value, Mapping):
        return (set(value) & LEARNER_FIELDS).union(*(learner_fields(item, scan_values=scan_values) for item in value.values()))
    if isinstance(value, (tuple, list)):
        return set().union(*(learner_fields(item, scan_values=scan_values) for item in value))
    if scan_values and isinstance(value, str) and PLANNER_VALUE.search(value):
        return {"learner-value"}
    if scan_values and type(value) is float and value in LEVELS:
        return {"learner-value"}
    return set()


def snapshot(result):
    rendered = result.rendered
    delivered = sorted({segment.claim_id for segment in rendered.segments if segment.claim_id}) if rendered else []
    verification = result.entry.verification
    return {
        "retrieval": canonical_sha256(result.request.model_dump(mode="json")),
        "evidence": canonical_sha256(result.bundle.model_dump(mode="json")),
        "claim_plan": canonical_sha256(result.plan.model_dump(mode="json")) if result.plan else None,
        "locked_claims": result.locked.claim_set_hash,
        "delivered_claims": delivered,
        "citations": sorted(set(rendered.citations)) if rendered else [],
        "decision": result.decision,
        "final_verification": verification.final,
        "v2": sorted((verdict.claim_id, verdict.v2.outcome) for verdict in verification.verdicts if verdict.v2),
    }


def _items(path, subset):
    public = fixture_items(FIXTURE) + regression_items(REGRESSIONS)
    if path is None:
        return fixture_items(FIXTURE, subset) + regression_items(REGRESSIONS), "public-fixtures"
    path = path.resolve(strict=True)
    if {part.lower() for part in path.parts} & {"lqs", "private", "licensed"}:
        raise ValueError("The item set must come from public engineering fixtures.")
    texts = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(texts, list) or not texts or
            any(not isinstance(query, str) or query not in {item[1] for item in public} for query in texts)):
        raise ValueError("Use a nonempty JSON list of approved public fixture questions.")
    return [("selected", query) for query in texts], path.name


def compute(subset=None, *, items_path=None, design="two-pass"):
    if design != "two-pass":
        raise ValueError("The supported engineering design is two-pass.")
    items, item_set = _items(items_path, subset)
    plans = [
        plan_presentation(
            ("fixture-lesson",), server_mastery={"fixture-lesson": mastery}, completed_lessons=set(),
            attempt_counts={}, default_plan="concise", adaptation_allowed=True,
        ).plan_id
        for mastery in LEVELS
    ]
    observations = []
    renderings = []
    breaches = set()
    with tempfile.TemporaryDirectory(prefix="phase8-invariance-") as directory:
        env = Environment(Path(directory))
        try:
            settings = env.settings(()).model_copy(update={"model_gateway": "shadow", "model_egress_providers": []})
            package = get_config_package(settings)
            for name in ("abstention", "gates", "v2"):
                breaches.update(learner_fields(package.raw.get(name, {})))
            breaches.update(learner_fields(package.raw.get("v1", {}).get("v1_5", {})))
            for plan in plans:
                gateway = _gateway(package, settings)
                gateway.captured = []
                cache = ProcessEvidentialCache(
                    max_plans=package.gateway.cache_max_plans, max_verdicts=package.gateway.cache_max_verdicts
                )
                pipeline = _pipeline(env, settings, gateway, cache)
                rows = []
                rendered = []
                for _, query in items:
                    capture_start = len(gateway.captured)
                    digest = canonical_sha256(query)
                    question = resolve_turns([], LearnerTurn("fixture-" + digest[:12], query), package=package)
                    result = pipeline.run(PipelineInput(
                        resolved=question, lesson_slug=None, presentation=PresentationPlan(plan_id=plan, source="request"),
                        response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}",
                    ), record=False)
                    envelope = result.envelope.model_dump(mode="json") if result.envelope else None
                    if envelope:
                        breaches.update(learner_fields(envelope))
                        breaches.update(learner_fields(envelope["instructions"], scan_values=True))
                    observed = snapshot(result)
                    observed["resolved"] = canonical_sha256(question.model_dump(mode="json"))
                    observed["envelope"] = canonical_sha256(envelope)
                    verifier_inputs = []
                    for payload in gateway.captured[capture_start:]:
                        data = payload.model_dump(mode="json")
                        # Alignment legitimately receives rendered prose and the fixed V1 readability band.
                        if isinstance(payload, AlignmentRequest) and data.get("band") == {
                            "min_grade": package.v1.readability_min, "max_grade": package.v1.readability_max,
                        }:
                            data.pop("band")
                        breaches.update(learner_fields(data))
                        breaches.update(learner_fields(data.get("instructions", {}), scan_values=True))
                        if not isinstance(payload, AlignmentRequest):
                            verifier_inputs.append(canonical_sha256(data))
                    observed["verifier_inputs"] = sorted(verifier_inputs)
                    rows.append((digest, observed))
                    rendered.append(canonical_sha256(result.rendered.text) if result.rendered else None)
                observations.append(rows)
                renderings.append(rendered)
        finally:
            env.close()
    violations = [
        {"query_sha256": variants[0][0], "fields": sorted(
            key for key in variants[0][1] if any(row[1][key] != variants[0][1][key] for row in variants[1:])
        )}
        for variants in zip(*observations)
        if any(row != variants[0] for row in variants[1:])
    ]
    return {
        "format": "phase8-public-invariance-v1",
        "evidence_scope": "Public engineering fixtures. E3 and LQ-1 require separate research evidence.",
        "items": len(items), "levels": list(LEVELS), "plans": plans,
        "item_set": item_set, "design": design, "item_set_sha256": canonical_sha256(items),
        "items_with_distinct_rendering": sum(len(set(variants) - {None}) > 1 for variants in zip(*renderings)),
        "observation_sha256": [canonical_sha256(rows) for rows in observations],
        "f2_fields": sorted(breaches), "violations": violations,
        "inputs": run_inputs(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", type=Path)
    action.add_argument("--check", type=Path)
    action.add_argument("--probe", action="store_true")
    action.add_argument("--clear-stop-sqlite", type=Path)
    parser.add_argument("--subset", type=int)
    parser.add_argument("--items", type=Path)
    parser.add_argument("--design", choices=["two-pass"], default="two-pass")
    parser.add_argument("--stop-sqlite", type=Path)
    args = parser.parse_args()
    if args.clear_stop_sqlite:
        _change_local_stop(args.clear_stop_sqlite, None)
        return 0
    if args.subset is not None and (not args.probe or args.subset < 1):
        parser.error("--subset is available only for a positive-sized probe")
    if args.write and _commit().endswith("-dirty"):
        print("Refused: commit the build before generating the report.", file=sys.stderr)
        return 4
    report = compute(args.subset, items_path=args.items, design=args.design)
    stopped = (report["violations"] or report["f2_fields"] or len(set(report["plans"])) < len(LEVELS)
               or not report["items_with_distinct_rendering"])
    print(f"Items: {report['items']}, violations: {len(report['violations'])}, F-2 fields: {report['f2_fields']}")
    if stopped:
        reason = "evidential-state" if report["f2_fields"] else "invariance"
        record_signal("learner.harness.violation", reason=reason)
        print(json.dumps(report["violations"][:5], sort_keys=True), file=sys.stderr)
        if args.stop_sqlite:
            _change_local_stop(args.stop_sqlite, reason)
        return 3
    if args.check:
        if report != json.loads(args.check.read_text(encoding="utf-8")):
            print("Invariance evidence drifted.", file=sys.stderr)
            return 1
    elif args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


def _change_local_stop(path: Path, reason: str | None) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import Session

    from app.services.learner_record_shadow import clear_adaptation_stop, stop_adaptation
    from app.services.security_log import append_security_event

    database = path.resolve(strict=True)
    if not database.is_file() or str(database).startswith("\\\\"):
        raise ValueError("Supply an existing local development SQLite database.")
    engine = create_engine(URL.create("sqlite", database=database.as_posix()))
    try:
        with Session(engine) as db:
            if reason is None:
                clear_adaptation_stop(db)
            else:
                stop_adaptation(db, reason)
            db.commit()
        append_security_event("learner.harness.stop" if reason else "learner.harness.clear", "success",
                              details={"reason": reason or "operator"}, session_factory=lambda: Session(engine))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
