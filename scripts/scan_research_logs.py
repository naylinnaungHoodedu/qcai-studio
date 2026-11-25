"""Scan for licensed-passage and ULQS fingerprint matches outside the research plane (Phase 10 spec 5; AC-10-4, AC-10-6).

Run: python scripts/scan_research_logs.py (--fingerprints PATH [--ulqs-fingerprints PATH] | --synthetic-fixture PATH)
         [--repo] [--path P ...] [--research-logs DIR ...] [--include-env-files] [--require-zero] [--self-test] [--report PATH]
         [--access-log PATH --actor-role ROLE]

Targets: --repo scans the tracked tree (git ls-files only); --path scans a file or directory; --research-logs scans a run
directory, every file except the fixed research-data file responses.jsonl (model outputs). Real fingerprints are
research-plane files (they hold their salt); public CI passes --synthetic-fixture, whose fingerprints are built in memory
from invented passages with a published salt, and the fixture file itself is not a scan target. --self-test plants a
sentinel in a temporary run directory and requires the scanner to find it, and to skip it in responses.jsonl. The report
holds paths and counts only. Any file that is text is scanned, whatever its suffix (Dockerfiles, dotfiles, .puml, .sh,
...), and a file with a UTF-16 or UTF-32 byte-order mark is decoded in that encoding; every file a target does not scan
is listed as excluded with its reason (`binary`, `not_text`, `too_large`, `unreadable`, or an environment file:
`.env*`, such as the tracked `.env.example` templates, is read only with --include-env-files, which CI passes). A match
always exits 1; --require-zero also fails (exit 1) when the coverage cannot prove zero: a target that scanned no file, a
file excluded as too large or unreadable, or, in a --research-logs or --path target, a file excluded as binary or not
text. Without --require-zero an incomplete scan exits 0 and says so on stderr. The report's `result` is `fail` on a
match, `incomplete` with zero matches and incomplete coverage (`incomplete_targets` names the targets), and `pass` only
with zero matches and full coverage. --ulqs-fingerprints goes with --fingerprints only (with --synthetic-fixture it is
refused, exit 2).

Research fingerprints (--fingerprints) are research-plane material, so with them --access-log PATH (a research-plane
path) and --actor-role are required: the log records the read of each fingerprint file (`fingerprints`, before it is
parsed), of each --research-logs directory (`run_output`) and each --path target (`scan_target`), each with a digest of
the files that target actually read (never of an environment file it excluded, a binary-suffix file or a file over
20 MiB, which are not read), and the write of the report (`scan_report`). With --synthetic-fixture the log is optional.

Exit codes: 0 zero matches (with full coverage only under --require-zero: without it an incomplete scan also exits 0, the
report's `result` says `incomplete` and stderr names the targets), or the self-test detected the sentinel; 1 matches,
incomplete coverage under --require-zero (or the self-test missed); 2 usage (including research fingerprints without
--access-log and --actor-role, --ulqs-fingerprints with --synthetic-fixture, or an access log on a public path).
"""

from __future__ import annotations

import argparse
import hashlib
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

from evaluation.qcai_eval import access_log, contamination, planes  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_line, dumps_record, lf_sha256, write_lf  # noqa: E402

PURPOSE = "contamination scan"

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


def _fingerprints_digest(path: Path) -> str | None:
    """The digest the builder logs for the file it wrote (the canonical sha256 of its `fingerprints`), or the file's LF
    sha256 when it does not parse that far; None when it cannot be read."""
    try:
        return canonical_sha256(json.loads(Path(path).read_text(encoding="utf-8"))["fingerprints"])
    except (OSError, ValueError, KeyError, TypeError):
        try:
            return lf_sha256(path)
        except (OSError, ValueError):
            return None


class ReadDigests:
    """The scanner's `on_read` callback for one target: the sha256 of each file the target actually read."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def __call__(self, name: str, data: bytes) -> None:
        self.files[name] = hashlib.sha256(data).hexdigest()

    def digest(self) -> str:
        """The canonical sha256 of [[relative path, sha256 of the bytes read], ...] in path order."""
        return canonical_sha256([[name, self.files[name]] for name in sorted(self.files)])


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
    parser.add_argument("--access-log", type=Path)
    parser.add_argument("--actor-role", choices=access_log.ROLES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.synthetic_fixture and args.ulqs_fingerprints is not None:
        print("usage (exit 2): --ulqs-fingerprints goes with --fingerprints (the synthetic fixture builds its own sets)",
              file=sys.stderr)
        return 2
    if args.fingerprints and (args.access_log is None or args.actor_role is None):
        print("usage (exit 2): research fingerprints (--fingerprints) need --access-log and --actor-role", file=sys.stderr)
        return 2
    if args.access_log is not None and args.actor_role is None:
        print("usage (exit 2): --access-log needs --actor-role", file=sys.stderr)
        return 2
    if args.access_log is not None:
        try:
            planes.require_private_output(args.access_log)
        except planes.PathRefused as error:
            print(f"usage (exit 2): {error}", file=sys.stderr)
            return 2

    def log(action: str, kind: str, sha256: str | None) -> None:
        if args.access_log is not None and sha256 is not None:
            access_log.append(args.access_log, actor_role=args.actor_role, action=action, artifact_kind=kind,
                              artifact_sha256=sha256, purpose=PURPOSE)

    if args.fingerprints:  # each research fingerprint file is logged as read, before it is parsed
        for path in (args.fingerprints, args.ulqs_fingerprints):
            if path is not None:
                log("read", "fingerprints", _fingerprints_digest(path))
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
        reads = ReadDigests()
        targets.append(contamination.path_target(absolute, sets, label=label, exclude_paths=[fixture] if fixture else [],
                                                 include_env=args.include_env_files, on_read=reads))
        log("read", "scan_target", reads.digest())
    for directory in args.research_logs:
        reads = ReadDigests()
        targets.append(contamination.research_logs_target(directory, sets, label=directory.name, include_env=args.include_env_files,
                                                          on_read=reads))
        log("read", "run_output", reads.digest())
    result = contamination.report(targets, sets)
    if args.report:
        write_lf(args.report, dumps_record(result))
        log("write", "scan_report", lf_sha256(args.report))
    for target in targets:
        print(f"{target['target']} {target['root']}: {target['scanned']} of {target['files']} files scanned, "
              f"{len(target['files_with_hits'])} with matches, {len(target['excluded'])} excluded")
        for hit in target["files_with_hits"]:
            print(f"  match: {hit['path']} (licensed {hit['licensed_hits']}, ulqs {hit['ulqs_hits']})")
    print(f"matches: {result['matches_total']} ({result['result']})")
    if result["matches_total"]:
        return 1
    incomplete = contamination.incomplete_targets(targets)
    if incomplete:
        code = 1 if args.require_zero else 0
        print(f"coverage incomplete (exit {code}{'' if args.require_zero else '; --require-zero fails it'}): {', '.join(incomplete)} "
              "(no file scanned, a file too large or unreadable, or a log or path file binary or not text)", file=sys.stderr)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
