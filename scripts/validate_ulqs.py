"""Validate a ULQS v1.0 item set, resolve its pointers, compute rater agreement and run the freeze check (Phase 10 spec 5).

Run: python scripts/validate_ulqs.py --items PATH [--catalog PATH] [--corpus-text DIR] [--public-spans] [--rules PATH]
         [--ratings PATH --rubric PATH --agreement-out PATH]
         [--freeze --previous PATH --corpus-text DIR --agent-check PATH] [--freeze-out PATH] [--access-log PATH --actor-role ROLE]

Public CI runs it on the synthetic fixture only. Real items are research-plane data: a non-synthetic item file inside the
checkout must be a git-ignored private-plane path, a non-synthetic run needs --access-log, and the strict freeze check
(--freeze, plan 6.5 "freeze hash") refuses synthetic items, so it runs only in the research plane. --corpus-text DIR holds
one <document_id>.txt per catalog document, for the character-for-character check; --freeze requires it, and requires
--previous PATH, the item set the freeze starts from (the review set or the last frozen set), against which every state
transition and the immutability of frozen content are checked. --agent-check PATH is the AI-agent re-check record
(`ulqs-agent-check-v1`, VBT RevB p. 15): a freeze without it fails with `agent_check_missing`, and no agent check passes
while the freeze rules pin no verifier model (D-07; DI-142). --freeze-out PATH writes the freeze record
(`ulqs-freeze-record-v1`, the keys `governance.FREEZE_RECORD_KEYS`): the dataset and content sha256s, the rules and
agreement sha256s, the canonical sha256 of the agent-check record (`agent_check_sha256`), the agent's full-report sha256
copied from that record (`agent_report_sha256`), the agent's model id, its counts, the items changed after one of its
flags, and the outcome. With --access-log (and --actor-role) every input is logged as soon as it is read, before
any check that can refuse (an input that does not parse is logged by its file's LF sha256), and every record written is
logged. Output names item ids, field paths and codes only, never a value.

Exit codes: 0 ok; 2 usage (--freeze without --previous or --corpus-text; --access-log without --actor-role), path
refused, an output or the access log that cannot be written, or an input unreadable or invalid: the items or previous set, the ratings
(including a main-round rating of a unit that is not a rated unit of the dataset item its item_id names, or one whose
rubric_sha256 is not the --rubric file's LF sha256), the rubric, the freeze rules, or an
agent-check record that does not parse or is not shaped as `ulqs-agent-check-v1` (one whose content does not match the
items is a freeze failure, exit 4); 3 schema problems; 4 freeze failed (codes printed); 5 evidence catalog invalid or
unresolved pointers; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
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

from evaluation.qcai_eval import access_log, agreement, inputs, planes, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, lf_sha256, read_jsonl, write_lf  # noqa: E402
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver, content_sha256, public_span_lookup, resolve_items  # noqa: E402

# The agent re-check counts the freeze record carries (VBT RevB p. 15).
AGENT_COUNTS = ("agent_detected_defects", "agent_false_alarms", "agent_missed_defects", "disagreements_adjudicated")


def _corpus_text(directory: Path | None, seen: dict[str, str]):
    """A reader of <document_id>.txt files that records the sha256 of each document it read (for the access log)."""
    if directory is None:
        return None

    def read(document_id: str) -> str | None:
        path = Path(directory) / f"{document_id}.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        seen[document_id] = content_sha256(text)
        return text

    return read


def _file_sha(path: Path) -> str | None:
    try:
        return lf_sha256(path)
    except (OSError, ValueError):
        return None


def _items_sha(items: list, path: Path) -> str | None:
    try:
        return ulqs.dataset_sha256(items)
    except (AttributeError, TypeError, ValueError):
        return _file_sha(path)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--items", type=planes.cli_path, required=True)
    parser.add_argument("--catalog", type=planes.cli_path)
    parser.add_argument("--corpus-text", type=planes.cli_path)
    parser.add_argument("--public-spans", action="store_true")
    parser.add_argument("--rules", type=planes.cli_path, default=ulqs.DEFAULT_FREEZE_RULES)
    parser.add_argument("--ratings", type=planes.cli_path)
    parser.add_argument("--rubric", type=planes.cli_path)
    parser.add_argument("--agreement-out", type=planes.cli_path)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--freeze-out", type=planes.cli_path)
    parser.add_argument("--previous", type=planes.cli_path)
    parser.add_argument("--agent-check", type=planes.cli_path)
    parser.add_argument("--access-log", type=planes.cli_path)
    parser.add_argument("--actor-role", choices=access_log.ROLES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.freeze and (args.previous is None or args.corpus_text is None):
        print("usage (exit 2): --freeze needs --previous (the set it starts from) and --corpus-text (the character check)",
              file=sys.stderr)
        return 2
    if args.access_log is not None and args.actor_role is None:
        print("usage (exit 2): --access-log needs --actor-role", file=sys.stderr)
        return 2
    try:
        if args.access_log is not None:
            planes.require_private_output(args.access_log)
    except planes.PathRefused as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2

    def log(action: str, kind: str, sha256: str | None) -> None:
        if args.access_log is not None and sha256 is not None:
            access_log.append(args.access_log, actor_role=args.actor_role, action=action, artifact_kind=kind, artifact_sha256=sha256,
                              purpose="validate")

    try:
        items = read_jsonl(args.items)
    except (OSError, ValueError) as error:
        log("read", "ulqs_items", _file_sha(args.items))
        print(f"refused (exit 2): items unreadable ({error})", file=sys.stderr)
        return 2
    log("read", "ulqs_items", _items_sha(items, args.items))
    synthetic = planes.all_synthetic(items)
    try:
        if not synthetic:
            for path in [args.items] + [path for path in (args.previous, args.catalog, args.corpus_text, args.ratings,
                                                          args.agent_check) if path]:
                planes.require_private_input(path)
            if args.access_log is None:
                print("refused (exit 2): non-synthetic items need --access-log", file=sys.stderr)
                return 2
        for output in (args.agreement_out, args.freeze_out):
            if output is not None:
                planes.require_private_output(output)
    except planes.PathRefused as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    if args.freeze and synthetic:
        print("refused (exit 2): --freeze refuses synthetic items (the strict freeze runs only in the research plane)", file=sys.stderr)
        return 2
    previous = None
    if args.previous is not None:
        try:
            previous = read_jsonl(args.previous)
        except (OSError, ValueError) as error:
            log("read", "ulqs_items", _file_sha(args.previous))
            print(f"refused (exit 2): previous items unreadable ({error})", file=sys.stderr)
            return 2
        log("read", "ulqs_items", _items_sha(previous, args.previous))
    agent_record = None
    if args.agent_check is not None:
        log("read", "agent_check_record", _file_sha(args.agent_check))
        try:
            agent_record = inputs.read_json(args.agent_check)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): agent check unreadable ({error})", file=sys.stderr)
            return 2
        if not ulqs.agent_check_shape_ok(agent_record):
            print("refused (exit 2): agent check invalid (not an ulqs-agent-check-v1 record)", file=sys.stderr)
            return 2
    if args.ratings and (args.rubric is None or args.agreement_out is None):
        print("usage (exit 2): --ratings needs --rubric and --agreement-out", file=sys.stderr)
        return 2
    # The counts name a stratum or status only when it is a string; a value of another type is a schema problem (exit 3).
    counts = Counter(tuple(value if isinstance(value, str) else "invalid" for value in (item.get("stratum"), item.get("status")))
                     for item in items)
    print(f"{len(items)} items: " + ", ".join(f"{stratum}/{status} {n}" for (stratum, status), n in sorted(counts.items(), key=str)))
    problems = ulqs.validate_dataset(items)
    if problems:
        for problem in problems[:200]:
            print(f"problem: {problem}")
        print(f"{len(problems)} schema problems (exit 3)", file=sys.stderr)
        return 3
    try:
        catalog = EvidenceCatalog.load(args.catalog) if args.catalog else None
    except (OSError, ValueError) as error:
        log("read", "evidence_catalog", _file_sha(args.catalog))
        print(f"refused (exit 5): catalog invalid ({error})", file=sys.stderr)
        return 5
    if catalog is not None:
        log("read", "evidence_catalog", catalog.sha256)
    corpus_versions = {item["corpus_version"] for item in items}
    documents: dict[str, str] = {}
    resolver = PointerResolver(catalog=catalog, span_lookup=public_span_lookup() if args.public_spans else None,
                               corpus_text=_corpus_text(args.corpus_text, documents),
                               corpus_version=next(iter(corpus_versions)) if len(corpus_versions) == 1 else None)
    report = resolve_items(items, resolver)
    if documents:
        log("read", "corpus_text", canonical_sha256(dict(sorted(documents.items()))))
    print(f"pointers: {report.resolved} of {report.total} resolved; {report.text_verified} of {report.evidence_resolved} "
          "EV pointers checked against the corpus text")
    agreement_value = None
    if args.ratings:
        ratings_sha = _file_sha(args.ratings)
        log("read", "ratings", ratings_sha)
        try:
            ratings = agreement.load_ratings(args.ratings)
            rules = ulqs.load_freeze_rules(args.rules)
            rubric_sha = lf_sha256(args.rubric)
            agreement_value = agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=rubric_sha,
                                                         ratings_sha256=ratings_sha)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): ratings, rules or rubric unreadable or invalid ({error})", file=sys.stderr)
            return 2
        write_lf(args.agreement_out, dumps_record(agreement_value))
        log("write", "agreement_record", canonical_sha256(agreement_value))
        print(f"agreement: alpha {agreement_value['alpha_nominal_label']}, second-rated share {agreement_value['coverage']['share']}, "
              f"gate {'passed' if agreement_value['gate']['passed'] else 'failed'}")
    if report.problems and not args.freeze:
        for item_id, path, status, _kind in report.problems[:200]:
            print(f"unresolved: {item_id}:{path}:{status}")
        print(f"{len(report.problems)} unresolved pointers (exit 5)", file=sys.stderr)
        return 5
    if args.freeze:
        try:
            rules = ulqs.load_freeze_rules(args.rules)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): freeze rules unreadable or invalid ({error})", file=sys.stderr)
            return 2
        result = ulqs.freeze_check(items, rules=rules, pointer_report=report, agreement=agreement_value, previous=previous,
                                   require_licensed=True, agent_check=agent_record)
        if args.freeze_out is not None:
            agent = agent_record if isinstance(agent_record, dict) else {}
            freeze_record = {
                "record": "ulqs-freeze-record-v1", "dataset_sha256": result.dataset_sha256,
                "dataset_content_sha256": ulqs.dataset_content_sha256(items), "rules_sha256": result.rules_sha256,
                "agreement_sha256": None if agreement_value is None else canonical_sha256(agreement_value),
                "agent_check_sha256": None if agent_record is None else canonical_sha256(agent_record),
                "agent_report_sha256": agent.get("report_sha256"), "agent_model_id": agent.get("agent_model_id"), **{key: agent.get(key) for key in AGENT_COUNTS},
                "items_changed_after_flag": agent.get("items_changed_after_flag"),
                "items_changed_without_flag": agent.get("items_changed_without_flag"),
                "passed": result.passed, "failures": list(result.failures)}
            write_lf(args.freeze_out, dumps_record(freeze_record))
            log("write", "freeze_record", lf_sha256(args.freeze_out))
        if not result.passed:
            for code in result.failures:
                print(f"freeze: {code}")
            print("freeze check failed (exit 4)", file=sys.stderr)
            return 4
        print(f"freeze check passed; dataset sha256 {result.dataset_sha256}")
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
