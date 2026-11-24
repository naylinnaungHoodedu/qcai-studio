"""The ranking replay report (plan Phase 9 F "replay report", J, L "Stop: a replay mismatch."; AC-9-8; Phase 9 spec 8.3).

Run: python scripts/run_ranking_replay.py --write docs/evaluation/phase9/ranking_replay_v1.json [--allow-dirty] [--package PATH]
     python scripts/run_ranking_replay.py --check docs/evaluation/phase9/ranking_replay_v1.json [--package PATH]

Seven synthetic scenarios (app.services.ranking.synthetic: flapping, promotion, outage, drift, model_change, empty_eligible,
rating_only), numbers and identifiers only, are built from their seeds with the package's ranking block, folded by the
controller into the full event log, and replayed twice; the record holds, per scenario, the sha256 of the input events,
of the derived events and of the final state, whether the two replays equal the generated log byte for byte, and the
engineering measurements (switches per 1000 drift-free requests with the first incumbent not counted, false alarms per
1000 before an injected shift, the detection delay, fallbacks, promotions, demotions). They are engineering measurements
on synthetic streams, not E4 results (invariant 9): Table XVII's MR-1..MR-3 are never asserted as met. The research replay
over E4 logs runs only in the research environment (D-15; DI-124): this script has no database mode and refuses a path
under lqs/ or a boundary-private path.
--check, in order: a pin (the package version and sha256, the ranking parameters' sha256) differing from the record exits 6;
a replay that differs from the generated log, or the two replays from each other, exits 7 (the plan L stop); a scenario
assertion failing exits 3; scenario hashes, measurements or inputs (the LF sha256 of the ranking modules and this script)
differing from the record exit 1 (drift). Exit codes: 0 current; 1 drift; 2 usage or refusal; 3 an assertion; 4 a dirty
tree on --write; 6 a pin mismatch; 7 a replay mismatch.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, load_config_package  # noqa: E402

DEFAULT_RECORD = REPO_ROOT / "docs" / "evaluation" / "phase9" / "ranking_replay_v1.json"
REPORT = "qcai-ranking-replay"
EVIDENCE_CLASS = "engineering measurement on synthetic streams, not E4 results (invariant 9; Table XVII MR-1..MR-3 not asserted)"
EXIT_OK, EXIT_DRIFT, EXIT_USAGE, EXIT_ASSERT, EXIT_DIRTY, EXIT_PIN, EXIT_REPLAY = 0, 1, 2, 3, 4, 6, 7
SELF = "scripts/run_ranking_replay.py"
FLAPPING_MAX_PER_1000 = 2


def refuse_path(path: Path, package) -> None:
    """A path under lqs/ (R-25) or a boundary-private path (the package's private_plane_globs) is refused."""
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        relative = resolved.as_posix()
    if "lqs" in resolved.parts:
        raise SystemExit("refused: the ranking replay never reads or writes ULQS (lqs/; R-25)")
    for pattern in package.boundary.private_plane_globs:
        if fnmatch.fnmatch(relative, pattern):
            raise SystemExit("refused: the ranking replay never reads or writes the private plane (D-14, D-15)")


def text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def inputs_files() -> dict:
    root = REPO_ROOT.resolve()
    files = {path.relative_to(root).as_posix(): text_sha256(path) for path in (root / "apps" / "api" / "app" / "services" / "ranking").glob("*.py")}
    files[SELF] = text_sha256(root / SELF)
    return dict(sorted(files.items()))


def pins(package) -> dict:
    return {"config_package": {"version": package.package_version, "sha256": package.sha256},
            "ranking_parameters": {"version": package.ranking.parameters_version, "sha256": package.ranking.parameters_sha256}}


def run_scenario(block: dict, name: str) -> tuple[dict, list[str]]:
    """(the scenario's record entry, its assertion failures)."""
    from app.services.ranking import synthetic
    from app.services.ranking.replay import compare, replay
    from app.services.ranking.state import canonical, state_sha256

    inputs, meta = synthetic.build(block, name)
    log = synthetic.materialise(inputs)
    first, second = replay(log), replay(log)
    check = compare(log, canonical(first.state).decode("utf-8"))
    derived = [[seq, kind, payload] for seq, kind, payload in first.derived]
    equal = (check.ok and canonical(first.state) == canonical(second.state) and first.derived == second.derived
             and first.checkpoints == second.checkpoints)
    numbers = synthetic.measurements(log, meta)
    failures = []
    if name == "flapping" and int(numbers["switches_drift_free"]) * 1000 > FLAPPING_MAX_PER_1000 * int(numbers["drift_free_requests"]):
        failures.append("flapping: more incumbent switches per 1000 drift-free requests than the hysteresis allows")
    if name == "promotion" and numbers["promotions"] < 1:
        failures.append("promotion: the better challenger was never promoted")
    if name == "outage" and (numbers["demotions"] < 1 or numbers["promotions"] < 1):
        failures.append("outage: the down incumbent was not demoted, or recovery was not by promotion")
    if name == "drift" and (numbers["alarms"] < 1 or numbers["detection_delay"] is None):
        failures.append("drift: the injected shift raised no alarm")
    if name == "empty_eligible" and numbers["fallbacks"] < 1:
        failures.append("empty_eligible: no fallback decision")
    if name == "model_change":
        model = first.state["models"]["model-b"]
        if model["capped"] or first.state["counts"]["recommission_fails"] != 1 or first.state["counts"]["recommission_passes"] != 1:
            failures.append("model_change: the cap was not lifted by the recommission pass alone")
    if name == "rating_only":
        without = [event for event in inputs if event["kind"] != "feedback"]
        other = replay(synthetic.materialise(without)).state
        for key, context in first.state["contexts"].items():
            for model_name, entry in context["models"].items():
                other_entry = other["contexts"][key]["models"][model_name]
                if (entry["alpha"], entry["beta"], entry["T"]) != (other_entry["alpha"], other_entry["beta"], other_entry["T"]):
                    failures.append("rating_only: a learner rating changed trust")
        if first.state["models"] != other["models"] or first.state["cluster_cusum"] != other["cluster_cusum"]:
            failures.append("rating_only: a learner rating changed a CUSUM chart")
    entry = {"id": name, "seed": f"synthetic-{name}-v1", "events": len(inputs), "log_rows": len(log),
             "events_sha256": canonical_sha256(inputs), "final_state_sha256": state_sha256(first.state),
             "derived_sha256": canonical_sha256(derived), "replays_equal": bool(equal), **numbers}
    return entry, failures


def compute(package) -> tuple[dict, list[str], bool]:
    block = json.loads(json.dumps(package.ranking.block))
    from app.services.ranking import synthetic

    scenarios, failures, equal = [], [], True
    for name in synthetic.SCENARIOS:
        entry, problems = run_scenario(block, name)
        scenarios.append(entry)
        failures.extend(problems)
        equal = equal and entry["replays_equal"]
    record = {"report": REPORT, "format_version": 1, "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": _commit(),
              "evidence_class": EVIDENCE_CLASS, "pins": pins(package), "scenarios": scenarios,
              "inputs": {"files": inputs_files()}}
    record["inputs"]["sha256"] = canonical_sha256(record["inputs"]["files"])
    return record, failures, equal


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").stdout.strip()
        if not head:
            return "unknown"
        status = _git("status", "--porcelain")
        return head + ("-dirty" if status.returncode != 0 or status.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _strip(value):
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in {"created_at", "commit"}}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    import logging

    logger = logging.getLogger("qcai")
    previous = logger.level
    try:
        logger.setLevel(logging.ERROR)
        return _main(argv)
    finally:
        logger.setLevel(previous)


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="--write from a working tree that differs from HEAD")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE_PATH, help="the configuration package (default: the shipped one)")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    try:
        package = load_config_package(args.package, governed=False)
    except Exception as exc:  # noqa: BLE001 - a package that does not load is a refusal
        print(f"refused: the package does not load: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if package.ranking is None:
        print("refused: the package has no ranking block", file=sys.stderr)
        return EXIT_USAGE
    target = args.write or args.check
    try:
        refuse_path(target, package)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if args.check:
        try:
            committed = json.loads(args.check.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"refused: the replay report cannot be read: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if committed.get("pins") != pins(package):
            print("ranking replay: a pin differs from the record (the package or its ranking block changed without a replay run)", file=sys.stderr)
            return EXIT_PIN
    elif not args.allow_dirty and _commit().endswith("-dirty"):
        print("refused: the working tree differs from HEAD; commit first, or pass --allow-dirty", file=sys.stderr)
        return EXIT_DIRTY
    fresh, failures, equal = compute(package)
    if not equal:
        print("ranking replay: a replay differs from the event log it replays (the plan L stop)", file=sys.stderr)
        return EXIT_REPLAY
    if failures:
        for failure in failures:
            print(f"ranking replay: {failure}", file=sys.stderr)
        return EXIT_ASSERT
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: {len(fresh['scenarios'])} scenarios replayed twice, byte-identical; {EVIDENCE_CLASS}")
        return EXIT_OK
    if _strip(committed) != _strip(fresh):
        differing = sorted(key for key in set(committed) | set(fresh) if key not in {"created_at", "commit"}
                           and _strip(committed.get(key)) != _strip(fresh.get(key)))
        print(f"ranking replay: drift: the record differs from a fresh run in: {', '.join(differing)}", file=sys.stderr)
        return EXIT_DRIFT
    print(f"ranking replay is current: {len(fresh['scenarios'])} scenarios replayed twice, byte-identical; {EVIDENCE_CLASS}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
