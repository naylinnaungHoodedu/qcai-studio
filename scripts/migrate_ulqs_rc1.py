"""Migrate ULQS rc1 items (schema_version 1.0) to v1.0 records (schema_version 1.1) in the research plane (spec 5; PD-61).

Run: python scripts/migrate_ulqs_rc1.py --input PATH --output PATH --author-role PI|RL --access-log PATH [--mapping PATH]

Plan G: "rc1 -> v1.0 mapping table; corpus_version separate [Risk R-19]." The mapping table is
lqs/ulqs-rc1-to-v1.0-mapping.json. Fields are copied; corpus_version is copied unchanged and is never part of an id; the
author name is replaced by a role code; human_reviewed starts false and item_kind null; splits follow ulqs-split-v1; no item
moves past its rc1 state. Input and output must be research-plane paths (outside the checkout, or a git-ignored private
path), and the access log is required. The script prints counts by stratum and state only, never a value.

Exit codes: 0 ok; 2 refused path or usage; 3 an input item fails rc1 validation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import access_log, planes, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import dumps_line, read_jsonl, write_lf  # noqa: E402

MAPPING_PATH = REPO_ROOT / "lqs" / "ulqs-rc1-to-v1.0-mapping.json"
ROLES = ("PI", "RL")


def migrate_item(item: dict, *, mapping: dict, author_role: str, split: str) -> dict:
    migrated = {key: value for key, value in item.items() if mapping["fields"].get(key, "").startswith(("copy", "set"))}
    migrated["schema_version"] = mapping["target"]["schema_version"]
    migrated["dataset_version"] = mapping["target"]["dataset_version"]
    migrated["status"] = mapping["states"][item["status"]]
    provenance = dict(item["provenance"])
    provenance["author"] = author_role
    migrated["provenance"] = provenance
    validation = dict(item["validation"])
    validation["human_reviewed"] = mapping["added"]["validation.human_reviewed"]
    migrated["validation"] = validation
    migrated["item_kind"] = mapping["added"]["item_kind"]
    migrated["split"] = split
    return migrated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--author-role", required=True, choices=ROLES)
    parser.add_argument("--access-log", type=Path)
    parser.add_argument("--mapping", type=Path, default=MAPPING_PATH)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.access_log is None:
        print("refused (exit 2): --access-log is required", file=sys.stderr)
        return 2
    try:
        planes.require_private_input(args.input)
        planes.require_private_output(args.output)
        planes.require_private_output(args.access_log)
    except planes.PathRefused as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    try:
        items = read_jsonl(args.input)
    except (OSError, ValueError) as error:
        print(f"refused (exit 3): input unreadable ({error})", file=sys.stderr)
        return 3
    failing = []
    for index, item in enumerate(items, start=1):
        problems = ulqs.validate_item(item)
        if item.get("schema_version") != mapping["source"]["schema_version"]:
            problems.append(ulqs.Problem(item.get("item_id"), "schema_version", "schema_version"))
        if item.get("status") not in mapping["source"]["status"]:
            problems.append(ulqs.Problem(item.get("item_id"), "status", "enum"))
        if problems:
            failing.append((index, problems))
    duplicates = [problem for problem in ulqs.validate_dataset(items) if problem.code == "duplicate"]
    if failing or duplicates:
        for index, problems in failing[:50]:
            for problem in problems[:20]:
                print(f"input line {index}: {problem}")
        for problem in duplicates:
            print(f"input: {problem}")
        print("rc1 validation failed (exit 3)", file=sys.stderr)
        return 3
    splits = ulqs.assign_splits(items)
    migrated = [migrate_item(item, mapping=mapping, author_role=args.author_role, split=splits[item["item_id"]]) for item in items]
    problems = ulqs.validate_dataset(migrated)
    if problems:
        for problem in problems[:50]:
            print(f"migrated: {problem}")
        print("migrated records fail validation (exit 3)", file=sys.stderr)
        return 3
    migrated.sort(key=lambda item: item["item_id"])
    write_lf(args.output, "".join(dumps_line(item) for item in migrated))
    access_log.append(args.access_log, actor_role=args.author_role, action="read", artifact_kind="ulqs_items",
                      artifact_sha256=ulqs.dataset_sha256(items), purpose="migrate rc1 to v1.0")
    access_log.append(args.access_log, actor_role=args.author_role, action="write", artifact_kind="ulqs_items",
                      artifact_sha256=ulqs.dataset_sha256(migrated), purpose="migrate rc1 to v1.0")
    counts = Counter((item["stratum"], item["status"]) for item in migrated)
    print(f"migrated {len(migrated)} items: " + ", ".join(f"{s}/{st} {n}" for (s, st), n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
