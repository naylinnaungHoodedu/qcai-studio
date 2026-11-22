"""Compare evidence and final decisions across three synthetic presentation choices."""

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
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
from app.gateway.contracts import AlignmentRequest
from app.services.learner_record_planner import plan_presentation
from app.services.tutor_pipeline.contracts import LEARNER_STATE_FIELDS, PresentationPlan
from app.services.tutor_pipeline.pipeline import PipelineInput
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.v2_panel.cache import ProcessEvidentialCache


LEVELS = (0.1, 0.5, 0.9)
LEARNER_FIELDS = frozenset(LEARNER_STATE_FIELDS) | {"expected_record_version", "consent_class", "replica_id"}


def learner_fields(value):
    if isinstance(value, Mapping):
        return (set(value) & LEARNER_FIELDS).union(*(learner_fields(item) for item in value.values()))
    if isinstance(value, (tuple, list)):
        return set().union(*(learner_fields(item) for item in value))
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


def compute(subset=None):
    items = fixture_items(FIXTURE, subset) + regression_items(REGRESSIONS)
    plans = [
        plan_presentation(
            ("fixture-lesson",), server_mastery={"fixture-lesson": mastery}, completed_lessons=set(),
            attempt_counts={}, default_plan="concise", adaptation_allowed=True,
        ).plan_id
        for mastery in LEVELS
    ]
    observations = []
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
                for _, query in items:
                    digest = canonical_sha256(query)
                    question = resolve_turns([], LearnerTurn("fixture-" + digest[:12], query), package=package)
                    result = pipeline.run(PipelineInput(
                        resolved=question, lesson_slug=None, presentation=PresentationPlan(plan_id=plan, source="request"),
                        response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}",
                    ), record=False)
                    if result.envelope:
                        breaches.update(learner_fields(result.envelope.model_dump(mode="json")))
                    observed = snapshot(result)
                    observed["resolved"] = canonical_sha256(question.model_dump(mode="json"))
                    rows.append((digest, observed))
                for payload in gateway.captured:
                    data = payload.model_dump(mode="json")
                    # The pinned alignment band is a verifier policy constant (DI-82), not a learner band.
                    if isinstance(payload, AlignmentRequest) and data.get("band") == {
                        "min_grade": package.v1.readability_min, "max_grade": package.v1.readability_max,
                    }:
                        data.pop("band")
                    breaches.update(learner_fields(data))
                observations.append(rows)
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
    report = compute(args.subset)
    stopped = report["violations"] or report["f2_fields"] or len(set(report["plans"])) < len(LEVELS)
    print(f"Items: {report['items']}, violations: {len(report['violations'])}, F-2 fields: {report['f2_fields']}")
    if stopped:
        print(json.dumps(report["violations"][:5], sort_keys=True), file=sys.stderr)
        if args.stop_sqlite:
            _change_local_stop(args.stop_sqlite, "evidential-state" if report["f2_fields"] else "invariance")
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
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
