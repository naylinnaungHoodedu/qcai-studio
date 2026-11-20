"""Check or re-hash the configuration package (Phase 2 spec 2.5; Phase 3 spec 5.5).

Run: python scripts/config_package.py --check [--path P]   (validates the package and its sidecar hash; for package
                                                             v2 also the tutor-pipeline schema pins, prompt hashes and
                                                             schema structure; exit 1 on a problem)
     python scripts/config_package.py --rehash [--path P]  (recomputes the stopword hash and, for v2, the schema pins,
                                                             the three prompt hashes and the legacy containment rule
                                                             hash from the code; rewrites the sidecar)
     python scripts/config_package.py --write-schemas      (writes the eight contract schemas from the pydantic models,
                                                             then --rehash)
The default path is the shipped package v2; v1 stays readable for one release (--path .../v1.json, DI-42).
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
    parse_config_package,
    stopwords_sha256,
)


def write_package(path: Path, payload: dict) -> str:
    """Write the package as LF JSON with its sidecar hash; returns the hash."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    digest = canonical_sha256(json.loads(path.read_text(encoding="utf-8")))
    path.with_name(path.name + ".sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    return digest


def write_schemas(path: Path) -> list[Path]:
    from app.services.tutor_pipeline.package_check import model_schema

    payload = json.loads(path.read_text(encoding="utf-8"))
    written = []
    for name, pin in payload["tutor_pipeline"]["schemas"].items():
        target = path.parent / pin["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(model_schema(name), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(target)
    return written


def rehash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    words = sorted(set(payload["retrieval"]["stopwords"]["words"]))
    payload["retrieval"]["stopwords"]["words"] = words
    payload["retrieval"]["stopwords"]["sha256"] = stopwords_sha256(words)
    if payload.get("schema_version") == 2:
        from app.services.tutor_pipeline.evidential import evidential_prompt_hash
        from app.services.tutor_pipeline.render import pedagogical_prompt_hash
        from app.services.tutor_pipeline.resolve import resolver_prompt_hash

        tutor = payload["tutor_pipeline"]
        for pin in tutor["schemas"].values():
            pin["sha256"] = canonical_sha256(json.loads((path.parent / pin["path"]).read_text(encoding="utf-8")))
        parsed = parse_config_package(payload, path=path, sha256="", hash_verified=False)
        params = parsed.tutor_pipeline
        tutor["resolver"]["prompt_hash"] = resolver_prompt_hash(params, parsed.retrieval)
        tutor["evidential"]["prompt_hash"] = evidential_prompt_hash(params)
        tutor["pedagogical"]["prompt_hash"] = pedagogical_prompt_hash()
        from app.services.ledger import LEGACY_CONTAINMENT_RULE_HASH

        tutor["legacy"]["containment_rule_hash"] = LEGACY_CONTAINMENT_RULE_HASH
    return write_package(path, payload)


def check(path: Path) -> int:
    try:
        package = load_config_package(path, governed=True)
    except ConfigPackageError as exc:
        print(f"configuration package check failed: {exc}", file=sys.stderr)
        return 1
    if package.tutor_pipeline is not None:
        from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package

        problems = check_tutor_pipeline_package(package, structural=True)
        if problems:
            for problem in problems:
                print(f"configuration package check failed: {problem}", file=sys.stderr)
            return 1
    print(
        f"configuration package {package.package_version} ok: sha256 {package.sha256}; "
        f"floor {package.abstention.floor}, margin {package.abstention.margin} (provisional until {package.abstention.provisional_until})"
    )
    if package.tutor_pipeline is not None:
        params = package.tutor_pipeline
        print(
            f"tutor pipeline {params.version}: resolver {params.resolver_id}, generator {params.generator_default}, renderer "
            f"{params.renderer_id}; {len(params.schemas)} schemas pinned (sha256 {params.schemas_sha256[:16]}); "
            f"phase4_exit_passed {package.flag_policy.phase4_exit_passed}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--rehash", action="store_true")
    mode.add_argument("--write-schemas", action="store_true")
    parser.add_argument("--path", type=Path, default=DEFAULT_PACKAGE_PATH)
    args = parser.parse_args(argv)
    if args.write_schemas:
        for target in write_schemas(args.path):
            print(f"wrote {target.name}")
        args.rehash = True
    if args.rehash:
        digest = rehash(args.path)
        print(f"rehashed {args.path.name}: sha256 {digest}")
        return 0
    return check(args.path)


if __name__ == "__main__":
    sys.exit(main())
