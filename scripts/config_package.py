"""Check or re-hash the configuration package (Phase 2 spec 2.5; Phase 3 spec 5.5; Phase 4 spec 5.4).

Run: python scripts/config_package.py --check [--path P]   (validates the package and its sidecar hash; for packages
                                                             v2 and v3 also the tutor-pipeline schema pins, prompt hashes
                                                             and schema structure, and for v3 the V1 block: rule ids and
                                                             their hash, and the adversarial fixture set's pin; exit 1 on
                                                             a problem)
     python scripts/config_package.py --rehash [--path P]  (recomputes the stopword hash and, for v2 and v3, the schema
                                                             pins, the three prompt hashes and the legacy containment
                                                             rule hash from the code; for v3 also v1.rules_hash, the
                                                             misconception library sha256 and the fixture set's sha256
                                                             and case count; rewrites the sidecar)
     python scripts/config_package.py --write-schemas      (writes the pinned contract schemas from the pydantic models,
                                                             nine for v3, then --rehash)
The default path is the shipped package v3; v2 and v1 stay readable for one release (--path .../v2.json, DI-63;
--path .../v1.json, DI-42).
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
    if payload.get("schema_version") == 3:
        from app.core.config_package import misconception_library_sha256
        from app.services.v1_checks.package_check import REPO_ROOT as V1_ROOT, fixture_set_sha256

        v1 = payload["v1"]
        library = v1["v1_8"]["library"]
        library["sha256"] = misconception_library_sha256(library)
        fixtures_path = V1_ROOT / v1["fixtures"]["path"]
        if fixtures_path.exists():
            cases = json.loads(fixtures_path.read_text(encoding="utf-8"))["cases"]
            v1["fixtures"]["set_sha256"] = fixture_set_sha256(cases)
            v1["fixtures"]["cases"] = len(cases)
    if payload.get("schema_version") in (2, 3):
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
    if payload.get("schema_version") == 3:
        from app.services.v1_checks.rules import v1_rules_hash

        payload["v1"]["rules_hash"] = v1_rules_hash(parse_config_package(payload, path=path, sha256="", hash_verified=False))
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
        if package.v1 is not None:
            from app.services.v1_checks.package_check import check_v1_package

            problems.extend(check_v1_package(package, structural=True))
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
    if package.v1 is not None:
        v1 = package.v1
        print(
            f"v1 checks {v1.version} (provisional): rules {v1.rules_hash[:16]}; checker {v1.checker_hosting}; misconception library "
            f"{v1.library_version} ({len(v1.library_entries)} entries); {v1.fixtures_cases} fixture cases (set {v1.fixtures_set_sha256[:16]}); "
            f"regenerations {v1.max_generation_regenerations}/{v1.max_render_regenerations}; p95 budget {v1.p95_budget_ms} ms"
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
