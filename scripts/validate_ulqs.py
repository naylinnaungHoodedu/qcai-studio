"""Validate a ULQS v1.0 item set, resolve its pointers, compute rater agreement and run the freeze check (Phase 10 spec 5).

Run: python scripts/validate_ulqs.py --items PATH [--catalog PATH] [--corpus-text DIR] [--public-spans] [--rules PATH]
         [--ratings PATH --rubric PATH --agreement-out PATH] [--freeze --previous PATH --corpus-text DIR] [--freeze-out PATH]
         [--access-log PATH --actor-role ROLE]

Public CI runs it on the synthetic fixture only. Real items are research-plane data: a non-synthetic item file inside the
checkout must be a git-ignored private-plane path, a non-synthetic run needs --access-log, and the strict freeze check
(--freeze, plan 6.5 "freeze hash") refuses synthetic items, so it runs only in the research plane. --corpus-text DIR holds
one <document_id>.txt per catalog document, for the character-for-character check; --freeze requires it, and requires
--previous PATH, the item set the freeze starts from (the review set or the last frozen set), against which every state
transition and the immutability of frozen content are checked. With --access-log (and --actor-role) every input read and
every record written is logged. Output names item ids, field paths and codes only, never a value.

Exit codes: 0 ok; 2 usage (--freeze without --previous or --corpus-text; --access-log without --actor-role) or path
refused; 3 schema problems; 4 freeze failed (codes printed); 5 unresolved pointers.
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

from evaluation.qcai_eval import access_log, agreement, planes, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, lf_sha256, read_jsonl, write_lf  # noqa: E402
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver, content_sha256, public_span_lookup, resolve_items  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--corpus-text", type=Path)
    parser.add_argument("--public-spans", action="store_true")
    parser.add_argument("--rules", type=Path, default=ulqs.DEFAULT_FREEZE_RULES)
    parser.add_argument("--ratings", type=Path)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--agreement-out", type=Path)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--freeze-out", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--access-log", type=Path)
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
        items = read_jsonl(args.items)
    except (OSError, ValueError) as error:
        print(f"refused (exit 2): items unreadable ({error})", file=sys.stderr)
        return 2
    synthetic = planes.all_synthetic(items)
    try:
        if not synthetic:
            for path in [args.items] + [path for path in (args.previous, args.catalog, args.corpus_text, args.ratings) if path]:
                planes.require_private_input(path)
            if args.access_log is None:
                print("refused (exit 2): non-synthetic items need --access-log", file=sys.stderr)
                return 2
        for output in (args.agreement_out, args.freeze_out, args.access_log):
            if output is not None:
                planes.require_private_output(output)
    except planes.PathRefused as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    if args.freeze and synthetic:
        print("refused (exit 2): --freeze refuses synthetic items (the strict freeze runs only in the research plane)", file=sys.stderr)
        return 2

    def log(action: str, kind: str, sha256: str) -> None:
        if args.access_log is not None:
            access_log.append(args.access_log, actor_role=args.actor_role, action=action, artifact_kind=kind, artifact_sha256=sha256,
                              purpose="validate")

    log("read", "ulqs_items", ulqs.dataset_sha256(items))
    previous = None
    if args.previous is not None:
        try:
            previous = read_jsonl(args.previous)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): previous items unreadable ({error})", file=sys.stderr)
            return 2
        log("read", "ulqs_items", ulqs.dataset_sha256(previous))
    if args.ratings and (args.rubric is None or args.agreement_out is None):
        print("usage (exit 2): --ratings needs --rubric and --agreement-out", file=sys.stderr)
        return 2
    counts = Counter((item.get("stratum"), item.get("status")) for item in items)
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
        try:
            ratings = agreement.load_ratings(args.ratings)
            rules = ulqs.load_freeze_rules(args.rules)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): {error}", file=sys.stderr)
            return 2
        ratings_sha = lf_sha256(args.ratings)
        log("read", "ratings", ratings_sha)
        agreement_value = agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=lf_sha256(args.rubric),
                                                     ratings_sha256=ratings_sha)
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
        rules = ulqs.load_freeze_rules(args.rules)
        result = ulqs.freeze_check(items, rules=rules, pointer_report=report, agreement=agreement_value, previous=previous,
                                   require_licensed=True)
        if args.freeze_out is not None:
            freeze_record = {
                "record": "ulqs-freeze-record-v1", "dataset_sha256": result.dataset_sha256,
                "dataset_content_sha256": ulqs.dataset_content_sha256(items), "rules_sha256": result.rules_sha256,
                "agreement_sha256": None if agreement_value is None else canonical_sha256(agreement_value),
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


if __name__ == "__main__":
    raise SystemExit(main())
