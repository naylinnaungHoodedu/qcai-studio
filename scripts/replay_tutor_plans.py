"""Three-plan replay report of the two-channel tutor (plan Phase 3 F: "three-plan replay report"; AC-3-2; plan L;
Phase 3 spec 7.17).

Run: python scripts/replay_tutor_plans.py --write docs/evaluation/phase3/three_plan_replay_v1.json
     python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json

The two-pass pipeline runs over the public-corpus fixture apps/api/tests/data/score_floor_queries.json (174
in-domain, 100 off-topic and 24 stopword-only items) under the three presentation plans (concise, stepwise,
socratic), in three configurations: governed_empty with p1-floor (the shipped D-31 build), and every public-plane,
bound item approved (a temporary manifest) with bm25f-v1 and with p1-floor. For every item the claim_set_hash and
the span set must be equal across the plans (the lock precedes rendering). It also reports the two-pass
bound-claim ratio beside the Phase 2 legacy ratio over the same lexical retrieval; a non-null two-pass ratio below
the package's tutor_pipeline.stop.phase2_bound_claim_ratio is the plan L stop.

This is an engineering replay on public-corpus fixtures. It is NOT E3 or LQ-1 evidence (plan Phase 3 H). Anything
under lqs/ is refused; no private-plane item, learner record, tutor turn or rating is read; nothing is written to a
database. The report holds hashes and counts only, never query, claim or span text.
Exit codes: --write 0 pass, 1 mismatch, 3 stop; --check 1 if the record differs from a fresh run (created_at and
commit aside), else as --write.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import os  # noqa: E402

# Importing the app must not create or touch a database file; the replay never writes one.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.core.config_package import canonical_sha256, get_config_package  # noqa: E402
from app.core.manifest_v2 import with_all_public_approved  # noqa: E402
from app.services.contained_answers import contain_answer  # noqa: E402
from app.services.content_assembler import CourseStore  # noqa: E402
from app.services.provenance import native_citation  # noqa: E402
from app.services.retrieval_engine import RetrievalEngine  # noqa: E402
from app.services.spans import span_set_digest  # noqa: E402
from app.services.tutor_pipeline.contracts import PresentationPlan  # noqa: E402
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline  # noqa: E402
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns  # noqa: E402

FIXTURE = API_ROOT / "tests" / "data" / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
DEFAULT_REPORT = REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json"
PLANS = ("concise", "stepwise", "socratic")
CONFIGURATIONS = (("governed_empty", "p1-floor"), ("all_public_approved", "bm25f-v1"), ("all_public_approved", "p1-floor"))
EVIDENCE_CLASS = "engineering replay on public-corpus fixtures; NOT E3 or LQ-1 evidence (plan Phase 3 H)"
EXIT_MISMATCH = 1
EXIT_STOP = 3


def _refuse_lqs(path: Path) -> None:
    resolved = Path(path).resolve()
    parts = resolved.relative_to(REPO_ROOT.resolve()).parts if resolved.is_relative_to(REPO_ROOT.resolve()) else resolved.parts
    if "lqs" in parts:
        raise SystemExit(f"refused: {path} is under lqs/; ULQS items MUST NOT be used by the replay (plan Phase 3 H)")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fixture_items(fixture: Path = FIXTURE, subset: int | None = None) -> list[tuple[str, str]]:
    """(stratum, query) for every fixture item, in file order; a subset is an evenly spaced, deterministic sample."""
    _refuse_lqs(fixture)
    payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    items = [("in_domain", item["query"]) for item in payload["in_domain"]]
    items += [("off_topic", query) for query in payload["off_topic"]]
    items += [("stopword_only", query) for query in payload["stopword_only"]]
    if subset is not None and subset < len(items):
        step = len(items) / subset
        items = [items[int(index * step)] for index in range(subset)]
    return items


def _settings(config: str, gate: str, manifest: Path) -> Settings:
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest), retrieval_gate=gate)


def _ratio(bound: int, proposed: int) -> float | None:
    return round(bound / proposed, 6) if proposed else None


def run_configuration(
    name: str,
    gate: str,
    manifest: Path,
    items: list[tuple[str, str]],
    *,
    generator_factory: Callable | None = None,
) -> dict:
    settings = _settings(name, gate, manifest)
    store = CourseStore(settings)
    engine = RetrievalEngine(store, settings)
    package = get_config_package(settings)
    generator = generator_factory(package) if generator_factory else None
    pipeline = TwoPassPipeline(engine, settings, generator=generator)
    baseline = package.tutor_pipeline.phase2_bound_claim_ratio
    answered = abstained = proposed = bound = 0
    reasons: Counter[str] = Counter()
    hash_equal = span_equal = distinct = 0
    mismatches: list[str] = []
    legacy = {"answered": 0, "claims": 0, "bound": 0}
    digest_rows: list[list[str]] = []
    registry = pipeline.registry
    for _, query in items:
        query_sha = _sha(query)
        resolved = resolve_turns([], LearnerTurn("fixture-" + query_sha[:12], query), package=package)
        results = []
        for plan_id in PLANS:
            results.append(
                pipeline.run(
                    PipelineInput(
                        resolved=resolved,
                        lesson_slug=None,
                        presentation=PresentationPlan(plan_id=plan_id, source="request"),
                        response_id=f"shadow-{uuid5(NAMESPACE_URL, f'qcai-replay|{name}|{gate}|{query}|{plan_id}')}",
                        delivery="shadow",
                        shadowed_response_id=f"turn-{uuid5(NAMESPACE_URL, f'qcai-replay|{name}|{gate}|{query}')}",
                    ),
                    record=False,
                )
            )
        first = results[0]
        hashes = {result.locked.claim_set_hash for result in results}
        span_sets = {result.locked.span_ids for result in results}
        hash_equal += len(hashes) == 1
        span_equal += len(span_sets) == 1
        if len(hashes) != 1 or len(span_sets) != 1 or len({result.decision for result in results}) != 1:
            mismatches.append(query_sha)
        if first.decision == "answer":
            answered += 1
            texts = {result.rendered.text for result in results if result.rendered is not None}
            distinct += len(texts) == len(PLANS)
        else:
            abstained += 1
            reasons[first.abstention_reason or "unknown"] += 1
        proposed += first.entry.counts.proposed_claims
        bound += first.entry.counts.bound_claims
        digest_rows.append([query_sha, first.decision, first.locked.claim_set_hash, span_set_digest(first.locked.span_ids)])
        # The Phase 2 legacy path over the same lexical retrieval: contained quotations, each citing its span.
        evidence = engine.evidence(resolved.text, lesson_slug=None, top_k=package.tutor_pipeline.top_k)
        citations = [native_citation(hit, corpus_version=store.corpus_version, settings=settings) for hit in evidence.results]
        contained = contain_answer(citations, registry, store.span_registry, settings=settings)
        if contained.decision == "answer":
            legacy["answered"] += 1
        legacy["claims"] += len(contained.claims)
        legacy["bound"] += sum(1 for claim in contained.claims if claim.cited_span_ids)
    ratio = _ratio(bound, proposed)
    floor, margin, threshold_version = store.index.thresholds
    return {
        "name": name,
        "gate": gate,
        "threshold_version": threshold_version,
        "corpus_version": store.corpus_version,
        "index_version": store.index_version,
        "items": len(items),
        "answered": answered,
        "abstained": abstained,
        "abstention_by_reason": dict(sorted(reasons.items())),
        "claim_set_hash_equal": hash_equal,
        "span_set_equal": span_equal,
        "rendered_text_distinct_among_answers": distinct,
        "mismatches": sorted(mismatches),
        "two_pass": {"proposed_claims": proposed, "bound_claims": bound, "bound_claim_ratio": ratio},
        "phase2_legacy": {**legacy, "bound_claim_ratio": _ratio(legacy["bound"], legacy["claims"])},
        "stop": bool(ratio is not None and ratio < baseline),
        "items_digest": canonical_sha256(sorted(digest_rows)),
    }


def compute(*, fixture: Path = FIXTURE, subset: int | None = None, generator_factory: Callable | None = None, configurations=CONFIGURATIONS) -> dict:
    items = fixture_items(fixture, subset)
    package = get_config_package(Settings())
    params = package.tutor_pipeline
    with tempfile.TemporaryDirectory(prefix="qcai-replay-") as temporary:
        approved = Path(temporary) / "manifest.json"
        approved.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
        manifests = {"governed_empty": REPO_MANIFEST, "all_public_approved": approved}
        results = [run_configuration(name, gate, manifests[name], items, generator_factory=generator_factory) for name, gate in configurations]
    mismatch = any(result["mismatches"] for result in results)
    stop = any(result["stop"] for result in results)
    try:
        fixture_path = Path(fixture).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        fixture_path = Path(fixture).name
    return {
        "report": "qcai-three-plan-replay",
        "format_version": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _commit(),
        "evidence_class": EVIDENCE_CLASS,
        "public_corpus_only": True,
        "excluded_sources": ["private plane", "lqs/ (ULQS)", "learner records, tutor turns, ratings"],
        "fixture": {"path": fixture_path, "sha256": canonical_sha256(json.loads(Path(fixture).read_text(encoding="utf-8"))), "items": len(items)},
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "tutor_pipeline": {
            "resolver": params.resolver_id,
            "generator": params.generator_default,
            "renderer": params.renderer_id,
            "subset_check": params.subset_check,
            "binding_rule": params.binding_rule,
            "prompt_hashes": {
                "resolver": params.resolver_prompt_hash,
                "evidential": params.evidential_prompt_hash,
                "pedagogical": params.pedagogical_prompt_hash,
            },
            "phase2_bound_claim_ratio_baseline": params.phase2_bound_claim_ratio,
        },
        "plans": list(PLANS),
        "configurations": results,
        "result": "mismatch" if mismatch else "stop" if stop else "pass",
    }


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def exit_code(report: dict) -> int:
    return {"pass": 0, "mismatch": EXIT_MISMATCH, "stop": EXIT_STOP}[report["result"]]


def _strip_volatile(report: dict) -> dict:
    return {key: value for key, value in report.items() if key not in {"created_at", "commit"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    _refuse_lqs(FIXTURE)
    target = args.write or args.check
    _refuse_lqs(target)
    fresh = compute()
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: result {fresh['result']}")
    else:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
        if _strip_volatile(committed) != _strip_volatile(fresh):
            differing = sorted(key for key in set(committed) | set(fresh) if key not in {"created_at", "commit"} and committed.get(key) != fresh.get(key))
            print(f"replay check failed: the record differs from a fresh run in: {', '.join(differing)}", file=sys.stderr)
            return 1
        print(f"replay record is current: result {fresh['result']}")
    for configuration in fresh["configurations"]:
        print(
            f"  {configuration['name']} / {configuration['gate']}: {configuration['answered']} answered, {configuration['abstained']} abstained, "
            f"{len(configuration['mismatches'])} mismatches, two-pass bound-claim ratio {configuration['two_pass']['bound_claim_ratio']} "
            f"(Phase 2 legacy {configuration['phase2_legacy']['bound_claim_ratio']})"
        )
    if fresh["result"] == "stop":
        print("stop condition (plan Phase 3 L): the two-pass bound-claim ratio fell below the Phase 2 baseline", file=sys.stderr)
    elif fresh["result"] == "mismatch":
        print("AC-3-2 fails: a claim_set_hash or span set differs across presentation plans", file=sys.stderr)
    return exit_code(fresh)


if __name__ == "__main__":
    sys.exit(main())
