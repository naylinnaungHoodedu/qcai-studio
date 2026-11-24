"""Validate a ULQS v1.0 item set, resolve its pointers, compute rater agreement and run the freeze check (Phase 10 spec 5).

Run: python scripts/validate_ulqs.py --items PATH [--catalog PATH] [--corpus-text DIR] [--public-spans] [--rules PATH]
         [--ratings PATH --rubric PATH --agreement-out PATH] [--freeze] [--freeze-out PATH] [--access-log PATH]

Public CI runs it on the synthetic fixture only. Real items are research-plane data: a non-synthetic item file inside the
checkout must be a git-ignored private-plane path, a non-synthetic run needs --access-log, and the strict freeze check
(--freeze, plan 6.5 "freeze hash") refuses synthetic items, so it runs only in the research plane. --corpus-text DIR holds
one <document_id>.txt per catalog document, for the character-for-character check. Output names item ids, field paths and
codes only, never a value.

Exit codes: 0 ok; 2 usage or path refused; 3 schema problems; 4 freeze failed (codes printed); 5 unresolved pointers.
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
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver, public_span_lookup, resolve_items  # noqa: E402


def _corpus_text(directory: Path | None):
    if directory is None:
        return None

    def read(document_id: str) -> str | None:
        path = Path(directory) / f"{document_id}.txt"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

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
    parser.add_argument("--access-log", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    try:
        items = read_jsonl(args.items)
    except (OSError, ValueError) as error:
        print(f"refused (exit 2): items unreadable ({error})", file=sys.stderr)
        return 2
    synthetic = planes.all_synthetic(items)
    try:
        if not synthetic:
            planes.require_private_input(args.items)
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
    if args.access_log is not None:
        access_log.append(args.access_log, actor_role="RL", action="read", artifact_kind="ulqs_items",
                          artifact_sha256=ulqs.dataset_sha256(items), purpose="validate")
    try:
        catalog = EvidenceCatalog.load(args.catalog) if args.catalog else None
    except (OSError, ValueError) as error:
        print(f"refused (exit 5): catalog invalid ({error})", file=sys.stderr)
        return 5
    corpus_versions = {item["corpus_version"] for item in items}
    resolver = PointerResolver(catalog=catalog, span_lookup=public_span_lookup() if args.public_spans else None,
                               corpus_text=_corpus_text(args.corpus_text),
                               corpus_version=next(iter(corpus_versions)) if len(corpus_versions) == 1 else None)
    report = resolve_items(items, resolver)
    print(f"pointers: {report.resolved} of {report.total} resolved")
    agreement_value = None
    if args.ratings:
        try:
            ratings = agreement.load_ratings(args.ratings)
            rules = ulqs.load_freeze_rules(args.rules)
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): {error}", file=sys.stderr)
            return 2
        agreement_value = agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=lf_sha256(args.rubric),
                                                     ratings_sha256=lf_sha256(args.ratings))
        write_lf(args.agreement_out, dumps_record(agreement_value))
        print(f"agreement: alpha {agreement_value['alpha_nominal_label']}, second-rated share {agreement_value['coverage']['share']}, "
              f"gate {'passed' if agreement_value['gate']['passed'] else 'failed'}")
    if report.problems and not args.freeze:
        for item_id, path, status, _kind in report.problems[:200]:
            print(f"unresolved: {item_id}:{path}:{status}")
        print(f"{len(report.problems)} unresolved pointers (exit 5)", file=sys.stderr)
        return 5
    if args.freeze:
        rules = ulqs.load_freeze_rules(args.rules)
        result = ulqs.freeze_check(items, rules=rules, pointer_report=report, agreement=agreement_value, require_licensed=True)
        if args.freeze_out is not None:
            write_lf(args.freeze_out, dumps_record({
                "record": "ulqs-freeze-record-v1", "dataset_sha256": result.dataset_sha256,
                "dataset_content_sha256": ulqs.dataset_content_sha256(items), "rules_sha256": result.rules_sha256,
                "agreement_sha256": None if agreement_value is None else canonical_sha256(agreement_value),
                "passed": result.passed, "failures": list(result.failures)}))
        if not result.passed:
            for code in result.failures:
                print(f"freeze: {code}")
            print("freeze check failed (exit 4)", file=sys.stderr)
            return 4
        print(f"freeze check passed; dataset sha256 {result.dataset_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
