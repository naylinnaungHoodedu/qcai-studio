"""Scan for licensed-passage and ULQS fingerprint matches outside the research plane (Phase 10 spec 5; AC-10-4, AC-10-6).

Run: python scripts/scan_research_logs.py (--fingerprints PATH [--ulqs-fingerprints PATH] | --synthetic-fixture PATH)
         [--repo] [--path P ...] [--research-logs DIR ...] [--include-env-files] [--require-zero] [--self-test] [--report PATH]

Targets: --repo scans the tracked tree (git ls-files only); --path scans a file or directory; --research-logs scans a run
directory, every file except the fixed research-data file responses.jsonl (model outputs). Real fingerprints are
research-plane files (they hold their salt); public CI passes --synthetic-fixture, whose fingerprints are built in memory
from invented passages with a published salt, and the fixture file itself is not a scan target. --self-test plants a
sentinel in a temporary run directory and requires the scanner to find it, and to skip it in responses.jsonl. The report
holds paths and counts only. Any file that is text is scanned, whatever its suffix (Dockerfiles, dotfiles, .puml, .sh,
...); environment files (`.env*`, such as the tracked `.env.example` templates) are read only with --include-env-files
(CI passes it) and are otherwise listed as excluded. A match always exits 1; --require-zero also fails (exit 1) when the
coverage cannot prove zero: a target that scanned no file, or a file excluded as too large or unreadable.

Exit codes: 0 zero matches with full coverage (or the self-test detected the sentinel); 1 matches, incomplete coverage
under --require-zero (or the self-test missed); 2 usage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import contamination  # noqa: E402
from evaluation.qcai_eval.canonical import dumps_line, dumps_record, write_lf  # noqa: E402

SELF_TEST_PASSAGE = ("the harness self test plants this invented passage of more than twelve words so that the licensed shingle "
                     "family must find it in a payload log")
SELF_TEST_QUESTION = "invented self test question for the exact family"


def self_test(sets: list) -> int:
    salt = secrets.token_bytes(32)
    planted = [contamination.set_from_payload(contamination.build_licensed([SELF_TEST_PASSAGE], salt, set_id="self-test-licensed")),
               contamination.set_from_payload(contamination.build_ulqs([{"question": SELF_TEST_QUESTION}], salt, set_id="self-test-ulqs"))]
    with tempfile.TemporaryDirectory(prefix="qcai-scan-self-test-") as temporary:
        run_dir = Path(temporary)
        write_lf(run_dir / "payload_log.jsonl", dumps_line({"log": "payload-log-v1", "leaked": SELF_TEST_PASSAGE}))
        write_lf(run_dir / "run_events.jsonl", dumps_line({"event": "start", "leaked": SELF_TEST_QUESTION}))
        write_lf(run_dir / "responses.jsonl", dumps_line({"text": SELF_TEST_PASSAGE + " " + SELF_TEST_QUESTION}))
        target = contamination.research_logs_target(run_dir, planted, label="self-test")
        hits = {hit["path"]: hit for hit in target["files_with_hits"]}
        licensed_found = hits.get("payload_log.jsonl", {}).get("licensed_hits", 0) >= 1
        ulqs_found = hits.get("run_events.jsonl", {}).get("ulqs_hits", 0) >= 1
        excluded = "responses.jsonl" not in hits and any(entry["path"] == "responses.jsonl" for entry in target["excluded"])
    if licensed_found and ulqs_found and excluded:
        print("self-test: the planted sentinel was found in both families and responses.jsonl was excluded")
        return 0
    print(f"self-test FAILED: licensed {licensed_found}, ulqs {ulqs_found}, research-data exclusion {excluded}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fingerprints", type=Path)
    source.add_argument("--synthetic-fixture", type=Path)
    parser.add_argument("--ulqs-fingerprints", type=Path)
    parser.add_argument("--repo", action="store_true")
    parser.add_argument("--path", type=Path, action="append", default=[])
    parser.add_argument("--research-logs", type=Path, action="append", default=[])
    parser.add_argument("--include-env-files", action="store_true")
    parser.add_argument("--require-zero", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    try:
        if args.synthetic_fixture:
            sets = contamination.synthetic_sets(args.synthetic_fixture)
            fixture = args.synthetic_fixture.resolve()
        else:
            sets = [contamination.load_fingerprint_file(args.fingerprints)]
            if args.ulqs_fingerprints:
                sets.append(contamination.load_fingerprint_file(args.ulqs_fingerprints))
            fixture = None
    except (OSError, ValueError, KeyError) as error:
        print(f"usage (exit 2): fingerprints unreadable ({error})", file=sys.stderr)
        return 2
    if args.self_test:
        return self_test(sets)
    if not (args.repo or args.path or args.research_logs):
        print("usage (exit 2): name at least one target (--repo, --path or --research-logs)", file=sys.stderr)
        return 2
    targets = []
    if args.repo:
        exclude = []
        if fixture is not None:
            try:
                exclude.append(fixture.relative_to(REPO_ROOT.resolve()).as_posix())
            except ValueError:
                pass
        targets.append(contamination.repository_target(REPO_ROOT, sets, exclude=exclude, include_env=args.include_env_files))
    for path in args.path:
        absolute = path if path.is_absolute() else REPO_ROOT / path
        label = path.as_posix() if not path.is_absolute() else path.name
        targets.append(contamination.path_target(absolute, sets, label=label, exclude_paths=[fixture] if fixture else [],
                                                 include_env=args.include_env_files))
    for directory in args.research_logs:
        targets.append(contamination.research_logs_target(directory, sets, label=directory.name, include_env=args.include_env_files))
    result = contamination.report(targets, sets)
    if args.report:
        write_lf(args.report, dumps_record(result))
    for target in targets:
        print(f"{target['target']} {target['root']}: {target['scanned']} of {target['files']} files scanned, "
              f"{len(target['files_with_hits'])} with matches, {len(target['excluded'])} excluded")
        for hit in target["files_with_hits"]:
            print(f"  match: {hit['path']} (licensed {hit['licensed_hits']}, ulqs {hit['ulqs_hits']})")
    print(f"matches: {result['matches_total']} ({result['result']})")
    if result["matches_total"]:
        return 1
    incomplete = contamination.incomplete_targets(targets)
    if args.require_zero and incomplete:
        print(f"coverage incomplete (exit 1): {', '.join(incomplete)} (no file scanned, or a file too large or unreadable)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
