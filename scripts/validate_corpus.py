"""Validate the public corpus manifest.

Run: python scripts/validate_corpus.py --check-public-assets   (AC-1-5; task 1.8: every approved item is reviewed)
     python scripts/validate_corpus.py --check-recall-stop     (plan Phase 2 L, spec conflict 29: no approved document
                                                                 under the p1-floor gate outside development)
     python scripts/validate_corpus.py --check-hashes          (AC-2-6: every manifest hash matches disk)
     python scripts/validate_corpus.py --check-near-duplicates (AC-2-8; task 2.9: no two bound items are near-duplicates)

--check-hashes accepts a Git LFS pointer's oid as the content hash (CI checks out without LFS) and recomputes
each item's span count and span-set digest and the corpus_version. --video-hash size checks a pointer by oid and
size and a hydrated video by size only, for quick in-suite runs; CI runs the full check.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, Settings  # noqa: E402
from app.core.config_package import get_config_package  # noqa: E402
from app.core.corpus_governance import (  # noqa: E402
    CorpusGovernanceError,
    CorpusRegistry,
    load_license_register,
    p1_floor_recall_stop,
    review_problems,
)

DEFAULT_REGISTER = REPO_ROOT / "corpus" / "license-register.csv"


def check_hashes(registry: CorpusRegistry, root: Path, video_hash: str) -> tuple[list[str], list[str]]:
    """(problems, report lines) for AC-2-6."""
    from app.core.manifest_v2 import file_sha256_and_size
    from app.services.content_assembler import DOCUMENT_TITLE_MAP, MODULE_BLUEPRINTS
    from app.services.spans import (
        authored_canonical_bytes,
        authored_sha256,
        build_spans,
        canonical_authored,
        canonical_document,
        check_library_versions,
        make_splitter,
        span_set_digest,
    )

    problems: list[str] = []
    lines: list[str] = []
    if registry.schema_version != "2.0":
        return [f"--check-hashes needs a schema 2.0 manifest (found {registry.schema_version})"], lines
    package = get_config_package(registry.settings)
    check_library_versions(package)
    splitter = make_splitter(package)
    resolver = Settings(source_assets_root=str(root))
    for item in registry.items:
        if item.kind == "authored":
            digest = authored_sha256(MODULE_BLUEPRINTS)
            size = len(authored_canonical_bytes(MODULE_BLUEPRINTS))
            spans = [record.span_id for record in build_spans(canonical_authored(MODULE_BLUEPRINTS, item_version=item.version), splitter)]
            basis = "canonical-json-authored-v1"
        else:
            paths = resolver._resolve_source_assets(list(item.asset_filenames[:1]))
            if not paths:
                problems.append(f"{item.item_id}: {item.asset_filenames[0]} is not on disk")
                continue
            digest, size, basis = file_sha256_and_size(paths[0], video_hash=video_hash if item.kind == "video" else "full")
            if digest is None:  # --video-hash size on a hydrated video: size only
                digest = item.sha256
            spans = None
            if item.kind == "document" and digest == item.sha256:
                # Spans are recomputed only for unchanged content: a damaged file is already a hash mismatch.
                try:
                    canonical = canonical_document(paths[0], item_id=item.item_id, item_version=item.version,
                                                   source_title=DOCUMENT_TITLE_MAP.get(paths[0].name, paths[0].stem))
                    spans = [record.span_id for record in build_spans(canonical, splitter)]
                except Exception as exc:  # a file that matches its hash but cannot be parsed is still a problem
                    problems.append(f"{item.item_id}: cannot be parsed for spans ({type(exc).__name__})")
        if digest != item.sha256:
            problems.append(f"{item.item_id}: sha256 differs from disk ({basis})")
        if size != item.size_bytes:
            problems.append(f"{item.item_id}: size_bytes {item.size_bytes} differs from disk {size} ({basis})")
        if spans is not None and (len(spans) != item.spans_count or span_set_digest(spans) != item.spans_set_sha256):
            problems.append(f"{item.item_id}: span count or span-set digest differs from a fresh build")
        lines.append(f"{item.item_id}: ok ({basis})" if not any(p.startswith(f"{item.item_id}:") for p in problems) else f"{item.item_id}: MISMATCH ({basis})")
    return problems, lines


def check_near_duplicates(registry: CorpusRegistry, root: Path) -> tuple[list[str], list[str]]:
    from app.core.near_duplicates import candidates_from_manifest, near_duplicate_pairs

    package = get_config_package(registry.settings)
    manifest = json.loads(registry.manifest_path.read_text(encoding="utf-8"))
    candidates = candidates_from_manifest(manifest, root, package)
    pairs = near_duplicate_pairs(candidates, package.near_duplicate)
    problems = [f"{pair.a} ~ {pair.b}: {'; '.join(pair.reasons)}" for pair in pairs]
    lines = [f"near-duplicate gate ({package.raw['near_duplicate']['version']}): {len(candidates)} bound public items, {len(pairs)} near-duplicate pair(s)"]
    return problems, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check-public-assets",
        action="store_true",
        help="Require every approved asset to have a reviewed license-register row (AC-1-5; task 1.8).",
    )
    parser.add_argument("--check-hashes", action="store_true", help="every manifest hash matches disk (AC-2-6)")
    parser.add_argument("--check-near-duplicates", action="store_true", help="the fingerprint gate (AC-2-8, task 2.9)")
    parser.add_argument(
        "--check-recall-stop",
        action="store_true",
        help="plan Phase 2 L stop (spec conflict 29): no approved document under the p1-floor gate outside development",
    )
    parser.add_argument("--video-hash", choices=("full", "size"), default="full")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="where the assets are (the root, then update_data/)")
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER, help="the license register CSV")
    args = parser.parse_args(argv)
    settings = Settings(environment="production", enforce_corpus_governance=True)
    try:
        registry = CorpusRegistry(settings)
    except CorpusGovernanceError as exc:
        print(f"Corpus manifest is invalid: {exc}", file=sys.stderr)
        return 1
    failed = False
    if args.check_public_assets:
        # The served catalogue is the manifest (Decision P1-D-07, D-31): an empty one is valid and serves nothing.
        problems = review_problems(registry, load_license_register(args.register), [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES])
        if problems:
            print("Public corpus is not ready to serve:\n" + "\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
            return 1
        approved = sorted({name for item in registry.approved_items for name in item.asset_filenames})
        withheld = len({*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES} - set(approved))
        print(f"Approved for public service: {len(approved)} asset(s); withheld: {withheld} of the application's source assets")
    if args.check_hashes:
        problems, lines = check_hashes(registry, args.root.resolve(), args.video_hash)
        for line in lines:
            print(line)
        if problems:
            failed = True
            print("Manifest hashes do not match disk (AC-2-6):\n" + "\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
        else:
            print(f"Every manifest hash matches disk (AC-2-6): {len(registry.items)} items, {registry.corpus_version}")
    if args.check_near_duplicates:
        problems, lines = check_near_duplicates(registry, args.root.resolve())
        for line in lines:
            print(line)
        if problems:
            failed = True
            print("Near-duplicate bound items (task 2.9):\n" + "\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
    if args.check_recall_stop:
        # Approving a document while the gate outside development is p1-floor lowers recall@5 (spec conflict 29).
        # The gate is the one these settings resolve (RETRIEVAL_GATE, else the production default p1-floor); the
        # owner override is reported, never silent. Governed start-up applies the same rule.
        stopped = p1_floor_recall_stop(registry, settings)
        if stopped and not settings.allow_p1_floor_with_documents:
            failed = True
            print(
                f"Recall stop (Phase 2 spec conflict 29): {len(stopped)} approved document item(s) under the p1-floor gate, "
                f"for example {stopped[0]}; switch RETRIEVAL_GATE under D-05 or recalibrate first",
                file=sys.stderr,
            )
        elif stopped:
            print(f"warning: recall stop overridden (ALLOW_P1_FLOOR_WITH_DOCUMENTS) for {len(stopped)} document item(s)", file=sys.stderr)
        else:
            print(f"Recall stop (spec conflict 29) clear: gate {settings.retrieval_gate}, no approved document under p1-floor")
    print(f"Validated corpus manifest at {registry.manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
