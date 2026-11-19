"""Record the pre-migration (a257dd11) search baseline for AC-2-5 (Phase 2 spec 2.10).

Run once, at Phase 2 step 1, from the unmodified code:
    python scripts/record_legacy_baseline.py --write apps/api/tests/data/legacy_p1_baseline.json --cross-check-live

The results come from the frozen module app.services.retrieval_legacy_p1. --cross-check-live also runs the live
CourseStore.search, which is the a257dd11 code only before Phase 2 changes it, and refuses to write on any
difference. Queries are keyed by sha256; the snapshot holds no learner data and no source text beyond chunk ids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, Settings  # noqa: E402
from app.core.corpus_governance import get_corpus_registry  # noqa: E402
from app.services.content_assembler import MODULE_BLUEPRINTS, _module_lessons  # noqa: E402
from app.services.retrieval_legacy_p1 import LEGACY_ALGORITHM, build_legacy_chunks, legacy_search  # noqa: E402

DATA = API_ROOT / "tests" / "data"
AC_FIXTURE = DATA / "score_floor_queries.json"
CALIBRATION_FIXTURE = DATA / "phase2_calibration_queries.json"


def _canonical_sha(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def learner_questions() -> list[dict]:
    return [
        {"query": question, "expected_lessons": [lesson["slug"]]}
        for blueprint in MODULE_BLUEPRINTS
        for lesson in _module_lessons(blueprint)
        for question in lesson["learner_questions"]
    ]


def legacy_settings(name: str, workdir: Path) -> Settings:
    if name == "governed_empty":
        return Settings(environment="production", enforce_corpus_governance=True,
                        corpus_manifest_path=str(REPO_ROOT / "corpus" / "public" / "manifest.json"))
    manifest = workdir / "legacy_all_approved_manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "items": [{
        "id": "legacy-all-public", "version": "v1", "source": "temporary", "license": "temporary",
        "permitted_use": "temporary", "public_service": True,
        "asset_filenames": [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES]}]}), encoding="utf-8")
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest))


def _recall(chunks, items, *, score_floor: int | None = None) -> int:
    kwargs = {} if score_floor is None else {"score_floor": score_floor}
    return sum(
        bool(set(item["expected_lessons"]) & {r.lesson_slug for r in legacy_search(chunks, item["query"], top_k=5, **kwargs)})
        for item in items
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, required=True)
    parser.add_argument("--cross-check-live", action="store_true")
    args = parser.parse_args()
    ac = json.loads(AC_FIXTURE.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION_FIXTURE.read_text(encoding="utf-8"))
    queries = sorted({*(i["query"] for i in ac["in_domain"]), *ac["off_topic"], *ac["stopword_only"],
                      *(i["query"] for i in calibration["items"]), *(i["query"] for i in learner_questions())})
    lq = learner_questions()
    oos = ac["off_topic"] + ac["stopword_only"]
    snapshot = {
        "snapshot": "legacy-p1-baseline",
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip() or "unknown",
        "algorithm": LEGACY_ALGORITHM,
        "fixture_sha256": {"score_floor_queries": _canonical_sha(AC_FIXTURE), "phase2_calibration_queries": _canonical_sha(CALIBRATION_FIXTURE)},
        "configurations": {},
        "ungated_recall_at_5": {},
        "out_of_scope_with_results": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("governed_empty", "all_public_approved"):
            settings = legacy_settings(name, Path(tmp))
            registry = get_corpus_registry(settings)
            chunks = build_legacy_chunks(settings, registry.served(settings.source_documents), registry.served(settings.source_videos))
            per_query = []
            for query in queries:
                top = legacy_search(chunks, query, top_k=5)
                per_query.append({"q": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                                  "top5": [[r.chunk_id, r.lesson_slug, r.score] for r in top]})
            if args.cross_check_live:
                from app.services.content_assembler import CourseStore

                store = CourseStore(settings)
                for query in queries:
                    live = [[r.chunk_id, r.lesson_slug, r.score] for r in store.search(query, top_k=5)]
                    frozen = [[r.chunk_id, r.lesson_slug, r.score] for r in legacy_search(chunks, query, top_k=5)]
                    if live != frozen:
                        print(f"{name}: the frozen search differs from the live search", file=sys.stderr)
                        return 1
            snapshot["configurations"][name] = {
                "recall_at_5": _recall(chunks, ac["in_domain"]),
                "learner_questions_recall_at_5": _recall(chunks, lq),
                "chunks": len(chunks),
                "unique_chunk_ids": len({chunk.chunk_id for chunk in chunks}),
                "per_query": per_query,
            }
            snapshot["ungated_recall_at_5"][name] = _recall(chunks, ac["in_domain"], score_floor=0)
            snapshot["out_of_scope_with_results"][name] = sum(1 for q in oos if legacy_search(chunks, q, top_k=20))
    args.write.write_text(json.dumps(snapshot, indent=1) + "\n", encoding="utf-8", newline="\n")
    summary = {name: {k: v for k, v in c.items() if k != "per_query"} for name, c in snapshot["configurations"].items()}
    print(json.dumps({"configurations": summary, "ungated": snapshot["ungated_recall_at_5"], "oos": snapshot["out_of_scope_with_results"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
