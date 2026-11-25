"""The research harness's committed records: pins, arm parity, analysis plans and seeded-fault known answers (spec 5).

Run: python scripts/check_research_harness.py [--check | --write] [--dir DIR]

Covers docs/evaluation/phase10/pinned_configuration_v1.json (the pinned configuration package and harness data files),
seeded_faults_report_v1.json (the reference detector over the synthetic seeded-fault fixture) and preregistration-draft.md
(generated from the analysis plans; a DRAFT, not filed). --check (the default; CI) proves each is current, LF-normalised;
--write rewrites them. --dir points at another copy of the three records (tests).

Exit codes: 0 ok; 1 drift (a record that differs from the generated one, or is missing or unreadable); 2 usage (an
unknown option, `--check` with `--write`, or a path argument holding a NUL) or a --dir the records cannot be written to
(--write); 3 a known answer not met or an
invalid analysis plan; 6 a pin (the package differs from its sidecar); 7 arm parity.
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

from evaluation.qcai_eval import ablation, analysis_plans, planes, seeded_faults, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, lf_sha256, read_jsonl, write_lf  # noqa: E402
from evaluation.qcai_eval.pointers import EvidenceCatalog  # noqa: E402

RECORD_DIR = REPO_ROOT / "docs" / "evaluation" / "phase10"
PACKAGE = "apps/api/app/config_package/v7.json"
JSON_FILES = ("evaluation/config/arms_v1.json", "evaluation/config/analysis_plans_v1.json", "evaluation/config/harness_parameters_v1.json",
              "evaluation/fixtures/seeded_faults_v1.json", "evaluation/fixtures/contamination_synthetic_v1.json",
              "lqs/ulqs-v1.0.schema.json", "lqs/ulqs-v1.0-freeze-rules.json", "lqs/ulqs-rc1-to-v1.0-mapping.json")
RECORDS = ("pinned_configuration_v1.json", "seeded_faults_report_v1.json", "preregistration-draft.md")


class Refused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


def pinned_configuration() -> dict:
    package = _json(PACKAGE)
    sha = canonical_sha256(package)
    sidecar = (REPO_ROOT / (PACKAGE + ".sha256")).read_text(encoding="utf-8").strip()
    if sidecar != sha:
        raise Refused(6, f"{PACKAGE} differs from its recorded sha256")
    items = read_jsonl(REPO_ROOT / "evaluation/fixtures/synthetic_ulqs_v1.jsonl")
    catalog = EvidenceCatalog.load(REPO_ROOT / "evaluation/fixtures/synthetic_evidence_catalog_v1.jsonl")
    decisions = package.get("owner_decisions") or {}
    return {
        "record": "pinned-configuration-v1",
        "format_version": 1,
        "provisional": True,
        "authority": "P1-D-18 (plan Phase 10 D task 5, F); ratified under DI-140 (PD-68)",
        "package": {"path": PACKAGE, "sha256": sha, "package_version": package.get("package_version"), "pinned_by": "explicit path and sha256",
                    "owner_decisions": {name: (decisions.get(name) or {}).get("state") for name in ("D-07", "D-08", "D-12", "D-14", "D-15")}},
        "harness_files": {relative: canonical_sha256(_json(relative)) for relative in JSON_FILES},
        "synthetic_fixtures": {"evaluation/fixtures/synthetic_ulqs_v1.jsonl": {"dataset_sha256": ulqs.dataset_sha256(items), "items": len(items)},
                               "evaluation/fixtures/synthetic_evidence_catalog_v1.jsonl": {"catalog_sha256": catalog.sha256},
                               "evaluation/fixtures/recorded_responses_synthetic_v1.jsonl": {
                                   "lf_sha256": lf_sha256(REPO_ROOT / "evaluation/fixtures/recorded_responses_synthetic_v1.jsonl")}},
        "models": None,
        "models_reason": "D-07 OPEN (hold H8): no pinned model identifiers, benchmark scores or prices exist (E-97; DI-132)",
        "counting_rules": "plan 15.3 windows and counting rules bind only when a research row is reported (DI-138)",
    }


def build_records() -> dict[str, str]:
    try:
        ablation.load_arms()
    except ablation.ParityError as error:
        raise Refused(7, f"arm parity: {error}") from None
    try:
        plans = analysis_plans.load_plans()
    except analysis_plans.PlanError as error:
        raise Refused(3, f"analysis plans: {error}") from None
    report = seeded_faults.reference_report()
    if not report["all_known_answers_met"]:
        raise Refused(3, "a seeded-fault known answer is not met")
    return {"pinned_configuration_v1.json": dumps_record(pinned_configuration()), "seeded_faults_report_v1.json": dumps_record(report),
            "preregistration-draft.md": analysis_plans.preregistration_markdown(plans)}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--dir", type=planes.cli_path, default=RECORD_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    try:
        records = build_records()
    except Refused as error:
        print(f"refused (exit {error.code}): {error}", file=sys.stderr)
        return error.code
    if args.write:
        for name, text in records.items():
            write_lf(args.dir / name, text)
            print(f"wrote {args.dir / name}")
        return 0
    drift = []
    for name, text in records.items():
        try:
            committed = (args.dir / name).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        except OSError:
            committed = None
        if committed != text:
            drift.append(name)
    if drift:
        print(f"drift: {', '.join(drift)} (rerun with --write after reviewing the change)", file=sys.stderr)
        return 1
    print(f"research harness records are current: {', '.join(RECORDS)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """An output or the access log that cannot be written is refused with exit 2, never a traceback (spec 5)."""
    try:
        return _main(argv)
    except planes.UNWRITABLE as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
