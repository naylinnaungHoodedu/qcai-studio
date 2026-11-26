"""Migrate ULQS rc1 items (schema_version 1.0) to v1.0 records (schema_version 1.1) in the research plane (spec 5; PD-61).

Run: python scripts/migrate_ulqs_rc1.py --input PATH --output PATH --author-role PI|RL --access-log PATH [--mapping PATH]

Plan G: "rc1 -> v1.0 mapping table; corpus_version separate [Risk R-19]." The mapping table is
lqs/ulqs-rc1-to-v1.0-mapping.json. Fields are copied; corpus_version is copied unchanged and is never part of an id; the
author name is replaced by a role code; human_reviewed starts false and item_kind null; splits follow ulqs-split-v1; no item
moves past its rc1 state. Input and output must be research-plane paths (outside the checkout, or a git-ignored private
path), and the access log is required. The script prints counts by stratum and state only, never a value.

The rc1 read is logged as soon as the file is read, before any check that can refuse (by the file's LF sha256 when it
does not parse), so a refused migration still leaves its read in the log.

The mapping is read and shape-checked (`mapping_problem`) before the input is read; a mapping that cannot be read, is
not strict JSON or is not shaped as `ulqs-rc1-to-v1.0` format 1 is refused (exit 2, `mapping unreadable` or
`mapping invalid (<field>)`).

Exit codes: 0 ok; 2 refused path or usage, a mapping unreadable or invalid, or an output or the access log that cannot be written; 3 the input is unreadable, an input item fails rc1 validation, or a migrated
record fails v1.0 validation; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import access_log, inputs, planes, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import dumps_line, lf_sha256, read_jsonl, write_lf  # noqa: E402

PROVISIONAL_DEFAULTS = ("PD-61",)  # Phase 10 spec 12.1; ratified under DI-140

MAPPING_PATH = REPO_ROOT / "lqs" / "ulqs-rc1-to-v1.0-mapping.json"
ROLES = ("PI", "RL")


def _strings(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def mapping_problem(mapping: object) -> str | None:
    """The first field of the rc1 mapping that is not shaped as `ulqs-rc1-to-v1.0` format 1 needs, or None: the source's
    schema version and its states (strings), the target's schema and dataset versions, `fields` (each a string rule),
    `added` (`validation.human_reviewed` a boolean, `item_kind` null or a string) and `states`, which maps every source
    state to itself (no item moves past its rc1 state)."""
    if not isinstance(mapping, dict) or mapping.get("mapping") != "ulqs-rc1-to-v1.0" or mapping.get("format_version") != 1:
        return "mapping"
    source, target, fields, added, states = (mapping.get(key) for key in ("source", "target", "fields", "added", "states"))
    if not isinstance(source, dict) or not _strings(source.get("schema_version")) or not isinstance(source.get("status"), list)             or not source["status"] or not all(_strings(state) for state in source["status"]):
        return "source"
    if not isinstance(target, dict) or not all(_strings(target.get(key)) for key in ("schema_version", "dataset_version")):
        return "target"
    if not isinstance(fields, dict) or not all(isinstance(rule, str) for rule in fields.values()):
        return "fields"
    if not isinstance(added, dict) or type(added.get("validation.human_reviewed")) is not bool             or not (added.get("item_kind") is None or isinstance(added.get("item_kind"), str)) or "item_kind" not in added:
        return "added"
    if not isinstance(states, dict) or any(states.get(state) != state for state in source["status"]):
        return "states"
    return None


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


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--input", type=planes.cli_path, required=True)
    parser.add_argument("--output", type=planes.cli_path, required=True)
    parser.add_argument("--author-role", required=True, choices=ROLES)
    parser.add_argument("--access-log", type=planes.cli_path)
    parser.add_argument("--mapping", type=planes.cli_path, default=MAPPING_PATH)
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
    try:
        mapping = inputs.read_json(args.mapping)
    except (OSError, ValueError) as error:
        print(f"refused (exit 2): mapping unreadable ({type(error).__name__})", file=sys.stderr)
        return 2
    problem = mapping_problem(mapping)
    if problem is not None:
        print(f"refused (exit 2): mapping invalid ({problem})", file=sys.stderr)
        return 2

    def log(action: str, sha256: str | None) -> None:
        if sha256 is not None:
            access_log.append(args.access_log, actor_role=args.author_role, action=action, artifact_kind="ulqs_items",
                              artifact_sha256=sha256, purpose="migrate rc1 to v1.0")

    try:
        items = read_jsonl(args.input)
    except (OSError, ValueError) as error:
        try:
            log("read", lf_sha256(args.input))  # read but not parsed: logged by the file's LF sha256
        except (OSError, ValueError):
            pass
        print(f"refused (exit 3): input unreadable ({error})", file=sys.stderr)
        return 3
    try:
        log("read", ulqs.dataset_sha256(items))
    except (AttributeError, TypeError, ValueError):
        log("read", lf_sha256(args.input))
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
    log("write", ulqs.dataset_sha256(migrated))
    counts = Counter((item["stratum"], item["status"]) for item in migrated)
    print(f"migrated {len(migrated)} items: " + ", ".join(f"{s}/{st} {n}" for (s, st), n in sorted(counts.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    """An output or the access log that cannot be written is refused with exit 2; any other exception the script does not
    handle is the last-resort refusal, exit 10 (`internal_error`, `planes.internal_error`): never a traceback, never exit 1
    (spec 5)."""
    try:
        return _main(argv)
    except planes.UNWRITABLE as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    except Exception as error:  # the last-resort handler (planes.INTERNAL_ERROR)
        planes.internal_error(error)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
