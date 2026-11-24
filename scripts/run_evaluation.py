"""The E1-E4 research harness runner (Phase 10 spec 5; plan Phase 10 D tasks 5-6; AC-10-3, AC-10-5).

Run:    python scripts/run_evaluation.py --spec SPEC --output-dir DIR [--resume] [--access-log PATH --actor-role ROLE]
Write:  python scripts/run_evaluation.py --write RECORD --spec SPEC     (a spec whose inputs are all synthetic)
Check:  python scripts/run_evaluation.py --check RECORD --spec SPEC     (CI: the stub run reproduces RECORD byte for byte)
Record: python scripts/run_evaluation.py --record-stub OUT --spec SPEC  (a synthetic recorded-responses-v1 file)

A run pins the configuration package by path and sha256, the items, the evidence catalog, the arms and the analysis plan;
its seeds are hashed. Stub and recorded runs repeat byte for byte. Hold H12 refuses every run over non-synthetic data while
D-14 is open, live runs are refused in this repository, and a confirmatory run needs a valid IRB record and OSF record.
--write and --check run in a temporary directory outside the checkout; nothing else is written there. With --access-log
(required for non-synthetic inputs, with --actor-role) the run logs the spec read, every input as the planner reads it
(also when it then refuses the run), its start and its outcome (completed, interrupted or refused). --resume continues only this run's own checkpoint.

Exit codes: 0 ok; 1 drift; 2 usage, a malformed spec, a path, an experiment or a foreign checkpoint refused; 3 invalid items, unresolved pointers, a freeze record or a
payload-log violation; 5 interrupted (provider outage; --resume continues); 6 a pin mismatch; 7 arm parity; 8 confirmatory
run refused (IRB or OSF); 9 live run or hold H12 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import access_log, planes, runner  # noqa: E402
from evaluation.qcai_eval.canonical import dumps_line, dumps_record, lf_sha256, write_lf  # noqa: E402
from evaluation.qcai_eval.payload_log import PayloadLogViolation  # noqa: E402
from evaluation.qcai_eval.providers import RecordedResponder, StubResponder, stub_response  # noqa: E402

PROVISIONAL_DEFAULTS = ("PD-68",)
RECORDED_FAILURES = ([{"status": "timeout"}, {"status": "ok"}], [{"status": "rate_limited"}, {"status": "ok"}],
                     [{"status": "server_error"}] * 4)


def _commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() or None


def _responder(plan: runner.Plan):
    mode = plan.spec["mode"]
    if mode == "stub":
        return StubResponder()
    if mode == "recorded":
        recorded = plan.spec["responder"]["recorded"]
        path = Path(recorded["path"])
        return RecordedResponder(path if path.is_absolute() else REPO_ROOT / path)
    raise runner.RunRefused(9, ["no_live_adapter"])


def _refused(error: runner.RunRefused) -> int:
    print(f"refused (exit {error.code}): {'; '.join(error.reasons)}", file=sys.stderr)
    return error.code


def _purpose(spec: dict) -> str:
    return spec.get("purpose") if spec.get("purpose") in runner.PURPOSES else "invalid"


def _run_id(spec: dict) -> str | None:
    value = spec.get("run_id")
    return value if isinstance(value, str) and runner.RUN_ID.match(value) else None


def run(spec_path: Path, out_dir: Path, *, resume: bool = False, access: Path | None = None, actor_role: str | None = None) -> int:
    """A run. With --access-log every access is logged before the outcome is known: the spec read, each input as soon as
    the planner reads it (so a run the planner refuses after reading its items still logs them), the run start, and its
    outcome (completed, interrupted or refused)."""
    if access is not None:
        if actor_role is None:
            print("usage (exit 2): --access-log needs --actor-role", file=sys.stderr)
            return 2
        try:
            planes.require_private_output(access)
        except planes.PathRefused as error:
            print(f"refused (exit 2): {error}", file=sys.stderr)
            return 2

    def log(action: str, kind: str, sha256: str, spec: dict, outcome: str | None = None) -> None:
        if access is not None:
            access_log.append(access, actor_role=actor_role, action=action, artifact_kind=kind, artifact_sha256=sha256,
                              purpose=_purpose(spec), run_id=_run_id(spec), outcome=outcome)

    try:
        spec = runner.load_spec(spec_path)
    except runner.RunRefused as error:
        return _refused(error)
    spec_sha = lf_sha256(spec_path)
    log("read", "run_spec", spec_sha, spec)
    try:
        plan = runner.plan_run(spec, out_dir=out_dir, access_log=access, on_read=lambda kind, sha256: log("read", kind, sha256, spec))
    except runner.RunRefused as error:
        log("run", "run_spec", spec_sha, spec, "refused")
        return _refused(error)
    log("run", "run_spec", spec_sha, spec, "started")
    try:
        record = runner.execute_run(plan, _responder(plan), out_dir, resume=resume, commit=_commit())
    except runner.RunInterrupted as error:
        log("run", "run_output", lf_sha256(Path(out_dir) / runner.RESPONSES), spec, "interrupted")
        print(f"interrupted (exit 5): {error}", file=sys.stderr)
        return 5
    except runner.RunRefused as error:
        log("run", "run_spec", spec_sha, spec, "refused")
        return _refused(error)
    except PayloadLogViolation as error:
        log("run", "run_spec", spec_sha, spec, "refused")
        print(f"payload-log violation (exit 3): {error}", file=sys.stderr)
        return 3
    log("run", "run_output", record["outputs"]["payload_log_sha256"], spec, "completed")
    slis = record["slis"]
    print(f"run {spec['run_id']} ({record['mode']}, {record['purpose']}): {slis['completed_requests']} of {slis['planned_requests']} "
          f"requests completed; record {Path(out_dir) / runner.RUN_RECORD}")
    return 0


def _synthetic_record(spec_path: Path) -> tuple[int, str | None, dict | None]:
    with tempfile.TemporaryDirectory(prefix="qcai-eval-") as temporary:
        out_dir = Path(temporary) / "run"
        try:
            spec = runner.load_spec(spec_path)
            plan = runner.plan_run(spec, out_dir=out_dir)
        except runner.RunRefused as error:
            return _refused(error), None, None
        if not plan.synthetic:
            print("refused (exit 2): --write and --check accept only a spec whose inputs are all synthetic", file=sys.stderr)
            return 2, None, None
        try:
            record = runner.execute_run(plan, _responder(plan), out_dir)
        except runner.RunRefused as error:
            return _refused(error), None, None
        except PayloadLogViolation as error:
            print(f"payload-log violation (exit 3): {error}", file=sys.stderr)
            return 3, None, None
        text = (out_dir / runner.RUN_RECORD).read_text(encoding="utf-8")
    return 0, text, record


def write(record_path: Path, spec_path: Path) -> int:
    code, text, _record = _synthetic_record(spec_path)
    if code:
        return code
    write_lf(record_path, text)
    print(f"wrote {record_path}")
    return 0


def check(record_path: Path, spec_path: Path) -> int:
    code, text, record = _synthetic_record(spec_path)
    if code:
        return code
    try:
        committed = record_path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        committed_record = json.loads(committed)
    except (OSError, ValueError):
        print(f"drift: {record_path} is missing or unreadable", file=sys.stderr)
        return 1
    if committed != text or committed_record.get("outputs", {}).get("payload_log_sha256") != record["outputs"]["payload_log_sha256"]:
        print(f"drift: {record_path} differs from a fresh stub run of {spec_path}", file=sys.stderr)
        return 1
    print(f"{record_path} is current ({record['requests']['planned']} requests, payload log {record['outputs']['payload_log_sha256'][:12]})")
    return 0


def record_stub(out_path: Path, spec_path: Path) -> int:
    """A synthetic recording of the stub over the spec's plan: two transient failures that recover, one that never does."""
    try:
        spec = runner.load_spec(spec_path)
        plan = runner.plan_run(spec)
    except runner.RunRefused as error:
        return _refused(error)
    if not plan.synthetic:
        print("refused (exit 2): --record-stub accepts only synthetic inputs", file=sys.stderr)
        return 2
    pins = runner.recording_pins(plan.pins["package"]["sha256"], plan.pins["items"]["sha256"],
                                 (plan.pins["evidence_catalog"] or {}).get("sha256"), plan.pins["arms"]["sha256"], plan.pins["prompt_version"])
    lines = [dumps_line({"recording": "recorded-responses-v1", "source": "synthetic", "run_pins_sha256": pins})]
    keys = sorted(request.request_key for request in plan.requests)
    scripted = dict(zip(keys, RECORDED_FAILURES))
    for request in plan.requests:
        attempts = scripted.get(request.request_key, [{"status": "ok"}])
        response = stub_response(b"stub-responder-v1", request)
        lines.append(dumps_line({"request_key": request.request_key, "attempts": list(attempts), "response": response}))
    write_lf(out_path, "".join(lines))
    print(f"wrote {out_path} ({len(lines) - 1} requests; sha256 {lf_sha256(out_path)[:12]})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--access-log", type=Path)
    parser.add_argument("--actor-role", choices=access_log.ROLES)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", type=Path, metavar="RECORD")
    group.add_argument("--check", type=Path, metavar="RECORD")
    group.add_argument("--record-stub", type=Path, metavar="OUT")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.write:
        return write(args.write, args.spec)
    if args.check:
        return check(args.check, args.spec)
    if args.record_stub:
        return record_stub(args.record_stub, args.spec)
    if args.output_dir is None:
        print("usage: --output-dir is required for a run", file=sys.stderr)
        return 2
    return run(args.spec, args.output_dir, resume=args.resume, access=args.access_log, actor_role=args.actor_role)


if __name__ == "__main__":
    raise SystemExit(main())
