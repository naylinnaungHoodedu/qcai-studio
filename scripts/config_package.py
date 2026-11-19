"""Check or re-hash the configuration package v1 (Phase 2 spec 2.5).

Run: python scripts/config_package.py --check    (validates v1.json and its v1.json.sha256; exit 1 on a problem)
     python scripts/config_package.py --rehash   (recomputes the stopword hash and rewrites v1.json.sha256)
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

from app.core.config_package import (  # noqa: E402
    DEFAULT_PACKAGE_PATH,
    ConfigPackageError,
    canonical_sha256,
    load_config_package,
    stopwords_sha256,
)


def write_package(path: Path, payload: dict) -> str:
    """Write the package as LF JSON with its sidecar hash; returns the hash."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    digest = canonical_sha256(json.loads(path.read_text(encoding="utf-8")))
    path.with_name(path.name + ".sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--rehash", action="store_true")
    parser.add_argument("--path", type=Path, default=DEFAULT_PACKAGE_PATH)
    args = parser.parse_args(argv)
    if args.rehash:
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        words = sorted(set(payload["retrieval"]["stopwords"]["words"]))
        payload["retrieval"]["stopwords"]["words"] = words
        payload["retrieval"]["stopwords"]["sha256"] = stopwords_sha256(words)
        digest = write_package(args.path, payload)
        print(f"rehashed {args.path.name}: sha256 {digest}")
        return 0
    try:
        package = load_config_package(args.path, governed=True)
    except ConfigPackageError as exc:
        print(f"configuration package check failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"configuration package {package.package_version} ok: sha256 {package.sha256}; "
        f"floor {package.abstention.floor}, margin {package.abstention.margin} (provisional until {package.abstention.provisional_until})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
