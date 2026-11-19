"""Generate corpus/public/manifest.json (schema 2.0) from the assets on disk (plan Phase 2 task 2.1).

Run: python scripts/generate_manifest.py                 (writes the repository manifest)
     python scripts/generate_manifest.py --check         (exit 1 and a per-item diff if it is not current)
     python scripts/generate_manifest.py --video-hash size --check   (videos by LFS pointer or size; quick)

Licence fields (source, license, permitted_use, public_service) are carried over from the existing manifest: by
id for 2.0, by filename for 1.0. They never enter corpus_version or any span id. A Git LFS pointer contributes
its oid, which is the sha256 of the content, so a checkout without LFS content generates the same file.
--all-public-approved writes a temporary manifest that approves every public-plane, bound item, for tests and
calibration; it refuses the repository path.
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

from app.core.config import Settings  # noqa: E402
from app.core.config_package import get_config_package  # noqa: E402
from app.core.manifest_v2 import ManifestError, build_manifest, dumps_manifest, with_all_public_approved  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "corpus" / "public" / "manifest.json"


def item_diff(current: dict, expected: dict) -> list[str]:
    lines: list[str] = []
    for key in ("schema_version", "manifest_status", "generator", "span_scheme", "corpus_version"):
        if current.get(key) != expected.get(key):
            lines.append(f"{key}: {current.get(key)!r} -> {expected.get(key)!r}")
    old = {item.get("id"): item for item in current.get("items", []) if isinstance(item, dict)}
    new = {item["id"]: item for item in expected["items"]}
    for item_id in sorted(set(old) | set(new)):
        if item_id not in old:
            lines.append(f"{item_id}: missing from the manifest")
        elif item_id not in new:
            lines.append(f"{item_id}: in the manifest but not on disk")
        else:
            for field in sorted(set(old[item_id]) | set(new[item_id])):
                if old[item_id].get(field) != new[item_id].get(field):
                    lines.append(f"{item_id}.{field}: {old[item_id].get(field)!r} -> {new[item_id].get(field)!r}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="where the assets are (the root, then update_data/)")
    parser.add_argument("--existing", type=Path, help="carry licence fields from this manifest (default: --output)")
    parser.add_argument("--check", action="store_true", help="compare with --output instead of writing it")
    parser.add_argument("--video-hash", choices=("full", "size"), default="full")
    parser.add_argument("--all-public-approved", action="store_true", help="temporary manifest for tests; never the repository path")
    args = parser.parse_args(argv)

    existing_path = args.existing or args.output
    existing = None
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except ValueError:
            existing = None
    package = get_config_package(Settings())
    warnings: list[str] = []
    try:
        manifest = build_manifest(args.root, existing, package, video_hash=args.video_hash, warnings=warnings)
    except ManifestError as exc:
        print(f"manifest generation failed: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.all_public_approved:
        if args.output.resolve() == DEFAULT_OUTPUT.resolve():
            print("refused: an all-approved manifest is never written to the repository manifest", file=sys.stderr)
            return 2
        manifest = with_all_public_approved(manifest)
    if args.check:
        current = existing if existing is not None else {}
        differences = item_diff(current, manifest)
        if differences:
            print(f"{args.output} is not current; run python scripts/generate_manifest.py", file=sys.stderr)
            for line in differences:
                print(f"- {line}", file=sys.stderr)
            return 1
        print(f"{args.output.name} is current: {len(manifest['items'])} items, {manifest['corpus_version']}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps_manifest(manifest), encoding="utf-8", newline="\n")
    print(f"wrote {args.output}: {len(manifest['items'])} items, {manifest['corpus_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
