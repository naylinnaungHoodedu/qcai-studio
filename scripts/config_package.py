"""Check or re-hash the configuration package (Phase 2 spec 2.5; Phase 3 spec 5.5; Phase 4 spec 5.4; Phase 5 spec 5.4;
Phase 6 spec 5.3; Phase 7 spec 5.3).

Run: python scripts/config_package.py --check [--path P]   (validates the package and its sidecar hash; for packages
                                                             v2 to v5 also the tutor-pipeline schema pins, prompt hashes
                                                             and schema structure, for v3 to v5 the V1 block: rule ids
                                                             and their hash, and the adversarial fixture set's pin, for
                                                             v4 and v5 the gateway, v2 and tools blocks, the committed
                                                             tool contract document included, and for v5 the v3 block:
                                                             its two schema pins and structure, its rule ids and the
                                                             development registry's fixture; exit 1 on a problem)
     python scripts/config_package.py --rehash [--path P]  (recomputes the stopword hash and, for v2 to v5, the schema
                                                             pins, the three prompt hashes and the legacy containment
                                                             rule hash from the code; for v3 to v5 also v1.rules_hash,
                                                             the misconception library sha256 and the fixture set's
                                                             sha256 and case count; for v4 and v5 the tool contract
                                                             file's sha256 and the two V2 prompt hashes; for v5 the two
                                                             V3 schema pins; rewrites the sidecar)
     python scripts/config_package.py --write-schemas      (writes the pinned contract schemas from the pydantic models,
                                                             fourteen and the tool contract document for v4 and v5, the
                                                             two V3 schemas for v5, then --rehash)
From schema EHMF_SCHEMA_VERSION (package v6, Phase 7) --check also runs the EHMF check (the routing document, the golden
set's sha256 and item count, the library with the development store) and prints its summary, and --rehash recomputes the
library pin and sidecar, the routing table and sha256, the template sha256 and the golden set's sha256 and items. What a
schema adds applies to every later schema, except the inline misconception library hash (schemas 3 to 5; from v6 the
library is a pinned file). From schema RANKING_SCHEMA_VERSION (package v7, Phase 9) --check also runs the ranking check (the
hand fixtures, the clusters, the recommission golden set's sha256 and item count, the replay report) and prints its summary,
and --rehash copies ehmf.golden_set's pin into ranking.recommission.golden_set.
The default path is the shipped package v7; v6, v5, v4, v3, v2 and v1 stay readable for one release (--path .../v6.json,
DI-126; --path .../v5.json, DI-112;
--path .../v4.json, DI-100;
--path .../v3.json, DI-84; --path .../v2.json, DI-63; --path .../v1.json, DI-42).
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
    EHMF_SCHEMA_VERSION,
    RANKING_SCHEMA_VERSION,
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
    if payload.get("schema_version", 0) >= 4:
        from app.gateway.tools import tool_contract_document

        target = path.parent / payload["tools"]["path"]
        target.write_text(json.dumps(tool_contract_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(target)
    if payload.get("schema_version", 0) >= 5:
        from app.services.v3.contracts import v3_schema_models

        models = v3_schema_models(payload["schema_version"])
        for name, pin in payload["v3"]["schemas"].items():
            target = path.parent / pin["path"]
            schema = models[name].model_json_schema(mode="validation")
            target.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            written.append(target)
    return written


def _rehash_ehmf(path: Path, payload: dict) -> None:
    """Package v6 (Phase 7 spec 5.3): the library pin and its sidecar, the routing sha256, the disclosure template's
    sha256 and the golden set's sha256 and item count."""
    from app.core.config_package import disclosure_template_sha256
    from app.services.ehmf.routing import routing_sha256, routing_table

    library = payload["v1"]["v1_8"]["library"]
    library_path = path.parent / library["path"]
    digest = canonical_sha256(json.loads(library_path.read_text(encoding="utf-8")))
    library["sha256"] = digest
    library_path.with_name(library_path.name + ".sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    ehmf = payload["ehmf"]
    ehmf["routing"]["table"] = routing_table()
    ehmf["routing"]["sha256"] = routing_sha256()
    template = ehmf["conflicts"]["disclosure_template"]
    template["sha256"] = disclosure_template_sha256(template["id"], template["text"])
    golden_path = REPO_ROOT / ehmf["golden_set"]["path"]
    if golden_path.exists():
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        ehmf["golden_set"]["sha256"] = canonical_sha256(golden)
        ehmf["golden_set"]["items"] = len(golden["items"])


def rehash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    words = sorted(set(payload["retrieval"]["stopwords"]["words"]))
    payload["retrieval"]["stopwords"]["words"] = words
    payload["retrieval"]["stopwords"]["sha256"] = stopwords_sha256(words)
    version = int(payload.get("schema_version") or 1)
    if version >= EHMF_SCHEMA_VERSION:
        _rehash_ehmf(path, payload)
    if version >= RANKING_SCHEMA_VERSION:
        # Phase 9 spec conflict 4: the recommission set is the golden set's queries, pinned with it.
        golden = payload["ehmf"]["golden_set"]
        payload["ranking"]["recommission"]["golden_set"].update({key: golden[key] for key in ("version", "path", "sha256", "items")})
    if 3 <= version < EHMF_SCHEMA_VERSION:
        from app.core.config_package import misconception_library_sha256

        library = payload["v1"]["v1_8"]["library"]
        library["sha256"] = misconception_library_sha256(library)
    if version >= 3:
        from app.services.v1_checks.package_check import fixture_set_sha256, repository_root

        v1 = payload["v1"]
        fixtures_path = repository_root() / v1["fixtures"]["path"]
        if fixtures_path.exists():
            cases = json.loads(fixtures_path.read_text(encoding="utf-8"))["cases"]
            v1["fixtures"]["set_sha256"] = fixture_set_sha256(cases)
            v1["fixtures"]["cases"] = len(cases)
    if version >= 4:
        from app.services.v2_panel.rules import alignment_prompt_hash, verifier_prompt_hash

        payload["tools"]["sha256"] = canonical_sha256(json.loads((path.parent / payload["tools"]["path"]).read_text(encoding="utf-8")))
        payload["v2"]["prompt"]["verifier_prompt_hash"] = verifier_prompt_hash()
        payload["v2"]["prompt"]["alignment_prompt_hash"] = alignment_prompt_hash()
    if version >= 5:
        for pin in payload["v3"]["schemas"].values():
            pin["sha256"] = canonical_sha256(json.loads((path.parent / pin["path"]).read_text(encoding="utf-8")))
    if version >= 2:
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
    if version >= 3:
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
        if package.schema_version >= 4:
            from app.gateway.package_check import check_gateway_package

            problems.extend(check_gateway_package(package, structural=True))
        if package.schema_version >= 5:
            from app.services.v3.package_check import check_v3_package

            problems.extend(check_v3_package(package, structural=True))
        if package.ehmf is not None:
            from app.services.ehmf.package_check import check_ehmf_package

            problems.extend(check_ehmf_package(package, structural=True))
        if package.ranking is not None:
            from app.services.ranking.package_check import check_ranking_package

            problems.extend(check_ranking_package(package, structural=True))
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
    if package.gateway is not None:
        gateway, v2 = package.gateway, package.v2
        registries = ", ".join(f"{name} {len(members)}" for name, members in gateway.registries.items())
        budgets = ", ".join(f"{name} {units}" for name, units in gateway.daily_units.items())
        print(
            f"gateway {gateway.version} (provisional): registries {registries}; daily units {budgets}; tools {package.tools.version}; "
            f"routing table {v2.routing_table_version}; phase5_exit_passed {package.flag_policy.phase5_exit_passed}"
        )
    if package.v3 is not None:
        v3 = package.v3
        registries = ", ".join(f"{name} {len(claims)}" for name, claims in v3.critical_registries.items())
        print(
            f"v3 {v3.version} (provisional): triggers {v3.trigger_registry_version}; draw {v3.draw_rule} at {v3.draw_rate} "
            f"({v3.x5_rate} under X5); double review {v3.double_review_rate}; critical registries {registries}; "
            f"phase6_exit_passed {package.flag_policy.phase6_exit_passed}"
        )
    if package.ehmf is not None:
        ehmf = package.ehmf
        factors = ", ".join(f"{name} {factor}" for name, (factor, _spans) in sorted(ehmf.penalty_registries.items()))
        weights = ", ".join(f"{key} {value}" for key, value in ehmf.weight_strings().items())
        print(
            f"ehmf {ehmf.version} (provisional): routing {ehmf.routing_version} ({ehmf.routing_sha256[:16]}); weights {weights} (provisional); "
            f"library {package.v1.library_version} ({len(package.v1.library_entries)} entries); golden set {ehmf.golden_set_items} items; "
            f"penalty factors {factors}; phase7_exit_passed {package.flag_policy.phase7_exit_passed}"
        )
    if package.ranking is not None:
        from app.services.ranking.package_check import summary

        print(summary(package))
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
