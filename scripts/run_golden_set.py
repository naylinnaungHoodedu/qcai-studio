"""The EHMF golden-set gate (plan Phase 7 D task 6 "each change passes the Stage 11 golden-set gate", K AC-7-6; plan 12.5;
Phase 7 spec 4.8; PD-47).

Run: python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json [--allow-dirty] [--package PATH] [--history PATH]
         [--base-ref REF | --base-history PATH]
     python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json [--package PATH] [--history PATH]
         [--base-ref REF | --base-history PATH]

The golden set (docs/evaluation/phase7/golden_set_v1.json, golden-set-v1) holds public-corpus or synthetic items only,
disjoint from ULQS (R-25; anything under lqs/ is refused). The runner builds its own in-memory SQLite database (never the
process's DATABASE_URL) and the all-public-approved store, and runs every item in development with V1_PIPELINE=enforce,
MODEL_GATEWAY=on, EHMF=on and V3_QUEUE=off over the development fake adapters: a Phase 4 item through
run_v1_fixtures.run_pipeline_case (its misconception items with the Phase 4 file's own fixture_library), a synthetic item
with scripted adapter verdicts (NOT_ENOUGH_INFO or CONTRADICTED on every pair, or an alignment member flagging leakage on
every render). Each outcome records whether an attacked claim was delivered, the final, the EHMF finding types of the
typed record, whether X2 was emitted and whether a conflict was disclosed, and whether it met its expectation.

The record pins the sha256 of the configuration package in use, the misconception library it pins, the routing table and
the golden set; --check, in order:
  1. pins: any of the four differing from the record exits 6 (a package, library, routing or golden-set edit without a
     golden-set run: AC-7-6);
  2. the package's own pin: ehmf.golden_set.sha256 differing from the file exits 6;
  3. the package version history (docs/evaluation/phase7/package_versions.json, committed, append-only): the package's
     package_version absent from it, or recorded there with a different sha256, exits 6 (a package edit that keeps its
     package_version fails here whatever record file is checked);
  4. append-only, when a base is given: the base branch's history (--base-ref REF reads the committed history at REF
     with git show; --base-history PATH reads a file) must be an unchanged prefix of the history, so an entry rewritten
     or removed (a same-version edit hidden by also editing the history) exits 6. A REF with no history file has no
     entries (before the first merge); an unknown REF or a malformed base exits 2. CI passes --base-ref with the pull
     request's base branch, so append-only is checked against the base branch, not only by review;
  5. a fresh run: an unmet expectation or an unresolved delivered citation exits 3 (13.9(a) "citation resolution 100%");
     outcomes or inputs differing from the record (created_at and commit aside) exit 1 (drift blocks promotion, 12.5).
--write refuses (exit 6) a package whose package_version the history records with a different sha256, or that is new but
not newer than the history's newest entry, a package whose sha256 differs from the replaced record's under the same
package_version, and (with a base) a history that is not an extension of the base's; on a passing run it appends the package's (version, sha256) to the history when absent, then writes the
record. Every package edit (a threshold, weight, routing, library or golden-set change re-pins the package) therefore
needs a new package_version, because config_version is the package version and the rising-A/B stop finds a change only
where it differs (plan Phase 7 L; docs/architecture/ehmf-change-control.md). A missing or malformed history, and a
package_version that is not MAJOR.MINOR.PATCH (the loader checks only its major part), exit 2 in both modes.
Exit codes: 0 pass; 1 drift; 2 usage or refusal; 3 an unmet expectation or an unresolved delivered citation; 4 a dirty
tree on --write; 6 a pin mismatch, or a package edit that keeps its package_version. The record is a change-control
gate, not research results (plan Phase 7 H; 12.5).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import Settings  # noqa: E402
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, load_config_package  # noqa: E402

DEFAULT_RECORD = REPO_ROOT / "docs" / "evaluation" / "phase7" / "golden_run_v1.json"
DEFAULT_HISTORY = REPO_ROOT / "docs" / "evaluation" / "phase7" / "package_versions.json"
HISTORY_REPO_PATH = "docs/evaluation/phase7/package_versions.json"
HISTORY_NAME = "qcai-config-package-versions"
EVIDENCE_CLASS = "change-control gate, not research results (plan Phase 7 H; 12.5)"
EXIT_OK, EXIT_DRIFT, EXIT_USAGE, EXIT_UNMET, EXIT_DIRTY, EXIT_PIN = 0, 1, 2, 3, 4, 6
SELF = "scripts/run_golden_set.py"
# The narrowest pin is named first: a library edit also changes the package (its pin), and is named as the library.
PIN_NAMES = ("misconception_library", "routing", "golden_set", "config_package")


def _v1_fixtures():
    """scripts/run_v1_fixtures.py, loaded by path (the script is not a package module)."""
    name = "golden_v1_fixtures"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "run_v1_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _refuse_lqs(path: Path) -> None:
    resolved = Path(path).resolve()
    parts = resolved.relative_to(REPO_ROOT.resolve()).parts if resolved.is_relative_to(REPO_ROOT.resolve()) else resolved.parts
    if "lqs" in parts:
        raise SystemExit("refused: the golden set and its record never read or write ULQS (lqs/; R-25)")


def pins(package) -> dict:
    from app.services.ehmf.routing import routing_sha256
    from app.services.ehmf.vocabulary import GOLDEN_SET_VERSION, ROUTING_VERSION

    golden_path = REPO_ROOT / package.ehmf.golden_set_path
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    return {
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "misconception_library": {"version": package.v1.library_version, "sha256": package.v1.library_sha256},
        "routing": {"version": ROUTING_VERSION, "sha256": routing_sha256()},
        "golden_set": {"version": GOLDEN_SET_VERSION, "sha256": canonical_sha256(golden), "items": len(golden["items"])},
    }


def _settings(env, package_path: Path) -> Settings:
    return Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=str(env.settings.corpus_manifest_path),
                    retrieval_gate="bm25f-v1", two_pass_tutor="shadow", v1_pipeline="enforce", model_gateway="on", ehmf="on",
                    v3_queue="off", config_package_path=str(package_path))


def _options(package, settings, sessions, *, verify=None, alignment_leakage=False) -> dict:
    from app.gateway.adapters import FakeAdapter
    from app.gateway.budget import DailyBudget
    from app.gateway.gateway import ModelGateway
    from app.gateway.registry import registry_for, registry_name
    from app.services.v2_panel.cache import ProcessEvidentialCache

    registry = registry_for(package, settings)
    script = {"*": tuple(verify)} if verify else None
    alignment = {"rating": 4, "leakage": True} if alignment_leakage else None
    adapters = {spec.adapter_id: FakeAdapter(spec, script=script, alignment=alignment) for spec in registry.members}
    gateway = ModelGateway(budget=DailyBudget(package.gateway.daily_units[registry_name(settings, package.gateway.registries)]), adapters=adapters)
    return {"gateway": gateway, "adapter_registry": registry, "cache": ProcessEvidentialCache(), "session_factory": sessions}


def _outcome(item: dict, result, delivered: bool, store) -> dict:
    verification = result.entry.verification
    ehmf = getattr(verification, "ehmf", None)
    types = set()
    if ehmf is not None:
        types = {finding.type for claim in ehmf.claims for finding in claim.findings} | {finding.type for finding in ehmf.response_findings}
    expect = item["expect"]
    citations = resolved = 0
    delivering = {verdict.claim_id for verdict in verification.verdicts if verdict.final == "deliver"}
    for claim in result.v1.locked.claims if result.v1 is not None else ():
        if claim.claim_id in delivering:
            for span_id in claim.span_ids:
                citations += 1
                resolved += int(store.span_registry.get(span_id) is not None)
    outcome = {
        "id": item["id"],
        "delivered": bool(delivered),
        "final": verification.final,
        "types": sorted(types),
        "x2": bool(ehmf is not None and ehmf.x2_emitted),
        "disclosed": bool(ehmf is not None and ehmf.disclosure is not None),
    }
    outcome["met"] = (outcome["delivered"] == expect["delivered"] and set(expect["types"]) <= types
                      and not (set(expect.get("absent_types", ())) & types) and outcome["x2"] == expect["x2"]
                      and outcome["disclosed"] == expect["disclosed"] and ehmf is not None)
    return outcome, citations, resolved


def _synthetic(item: dict, env, settings, package, sessions):
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.tutor_pipeline.contracts import PresentationPlan
    from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
    from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

    attack = item["attack"]
    options = _options(package, settings, sessions, verify=attack.get("verify"), alignment_leakage=bool(attack.get("alignment_leakage")))
    pipeline = TwoPassPipeline(RetrievalEngine(env.store, settings), settings, **options)
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", item["query"]), package=pipeline.package)
    result = pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="default"),
                                        response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}",
                                        legacy_decision=None), record=False)
    delivered = any(verdict.final == "deliver" for verdict in result.entry.verification.verdicts)
    return result, delivered


def compute(*, package_path: Path = DEFAULT_PACKAGE_PATH, commit_source=None) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades

    fixtures_module = _v1_fixtures()
    package = load_config_package(package_path, governed=False)
    if package.ehmf is None:
        raise SystemExit("refused: the package has no ehmf block (package v6 or later)")
    golden = json.loads((REPO_ROOT / package.ehmf.golden_set_path).read_text(encoding="utf-8"))
    fixtures = fixtures_module.load_fixtures(REPO_ROOT / golden["phase4_fixtures"])
    cases = {case["id"]: case for case in fixtures["cases"]}
    env = fixtures_module.gate_environment("bm25f-v1")
    settings = _settings(env, package_path)
    v1 = fixtures_module.overlay_v1(package, fixtures.get("fixture_package") or {})
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        sessions = sessionmaker(bind=engine)
        outcomes, citations, resolved = [], 0, 0
        per_type = {name: 0 for name in ("A", "B1", "B2", "C", "D", "E")}
        for item in golden["items"]:
            if item["source"].startswith("phase4:"):
                case = cases[item["source"].split(":", 1)[1]]
                row, result = fixtures_module.run_pipeline_case(case, env, v1, "deterministic_only", fixtures, settings=settings,
                                                                 pipeline_options=_options(package, settings, sessions))
                delivered = row["delivered"]
            else:
                result, delivered = _synthetic(item, env, settings, package, sessions)
            outcome, item_citations, item_resolved = _outcome(item, result, delivered, env.store)
            outcomes.append(outcome)
            citations, resolved = citations + item_citations, resolved + item_resolved
            for name in outcome["types"]:
                per_type[name] += 1
    finally:
        engine.dispose()
    problems = [f"{outcome['id']} did not meet its expectation" for outcome in outcomes if not outcome["met"]]
    if resolved != citations:
        problems.append(f"{citations - resolved} delivered citation(s) do not resolve (13.9(a): 100%)")
    commit = (commit_source or _commit)()
    return {
        "report": "qcai-ehmf-golden-run", "format_version": 1, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit, "evidence_class": EVIDENCE_CLASS, "pins": pins(package),
        "configuration": {"environment": "development", "gate": "bm25f-v1", "v1_pipeline": "enforce", "model_gateway": "on", "ehmf": "on",
                          "adapters": "development fakes", "misconception_cases": "phase 4 fixture_library"},
        "outcomes": outcomes,
        "citation_resolution": {"delivered_citations": citations, "resolved": resolved, "share": f"{resolved}/{citations}"},
        "per_type": per_type,
        "result": "pass" if not problems else "unmet",
        "problems": problems,
        "inputs": {"rule": INPUTS_RULE, "files": _inputs_files(fixtures_module)},
    }


INPUTS_RULE = "application-modules-and-runner-scripts-sha256-lf-v1"
INPUT_SCRIPTS = ("scripts/run_golden_set.py", "scripts/run_v1_fixtures.py")


def _inputs_files(fixtures_module) -> dict:
    """The LF sha256 of every application module and of the two runner scripts: a fixed set, so the same tree gives the
    same inputs whatever the calling process imported (a CLI run and an in-process --check agree)."""
    root = REPO_ROOT.resolve()
    files = {path.relative_to(root).as_posix(): fixtures_module.text_sha256(path)
             for path in (root / "apps" / "api" / "app").rglob("*.py") if "__pycache__" not in path.parts}
    for relative in INPUT_SCRIPTS:
        files[relative] = fixtures_module.text_sha256(root / relative)
    return dict(sorted(files.items()))


def _finish_inputs(record: dict) -> dict:
    record["inputs"]["sha256"] = canonical_sha256(record["inputs"]["files"])
    return record


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


def check_pins(record: dict, package) -> tuple[int, str] | None:
    current = pins(package)
    for name in PIN_NAMES:
        recorded = (record.get("pins") or {}).get(name, {}).get("sha256")
        if recorded != current[name]["sha256"]:
            return EXIT_PIN, (f"golden-set gate: the {name} sha256 differs from the golden run ({recorded} != {current[name]['sha256']}): "
                              "rerun scripts/run_golden_set.py --write and commit the record in the same change")
    if package.ehmf.golden_set_sha256 != current["golden_set"]["sha256"]:
        return EXIT_PIN, ("golden-set gate: the package's ehmf.golden_set.sha256 differs from the golden set file "
                          f"({package.ehmf.golden_set_sha256} != {current['golden_set']['sha256']}): run scripts/config_package.py --rehash")
    return None


def same_version_edit(record: dict, package) -> tuple[int, str] | None:
    """The refusal of a package edit that keeps the recorded package_version (a change the stop could never see)."""
    recorded = (record.get("pins") or {}).get("config_package") or {}
    if recorded.get("version") == package.package_version and recorded.get("sha256") != package.sha256:
        return EXIT_PIN, (f"golden-set gate: the configuration package changed (sha256 {recorded.get('sha256')} != {package.sha256}) "
                          f"but keeps package_version {package.package_version}: bump package_version (config_version is the package "
                          "version, and the rising-A/B stop sees a change only where it differs), then rehash and rerun --write")
    return None


def _version_key(version: str) -> tuple[int, ...]:
    parts = str(version).split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"package_version {version!r} is not MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in parts)


def load_history(path: Path) -> dict:
    """The append-only package version history; ValueError when it is missing or malformed."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"the package version history cannot be read: {exc}") from exc
    return parse_history(text)


def parse_history(text: str) -> dict:
    """A package version history from its JSON text; ValueError when it is malformed."""
    try:
        history = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the package version history cannot be read: {exc}") from exc
    if not isinstance(history, dict) or history.get("history") != HISTORY_NAME:
        raise ValueError(f"the package version history is not {HISTORY_NAME}")
    entries = history.get("entries")
    if not isinstance(entries, list) or not all(
            isinstance(entry, dict) and set(entry) == {"version", "sha256"} and isinstance(entry["sha256"], str)
            and len(entry["sha256"]) == 64 for entry in entries):
        raise ValueError("the package version history's entries are {version, sha256} objects")
    keys = [_version_key(entry["version"]) for entry in entries]
    if keys != sorted(set(keys)):
        raise ValueError("the package version history lists each package_version once, oldest first")
    return history


def history_problem(history: dict, package) -> tuple[int, str] | None:
    """A package whose package_version the history lacks, or records with a different sha256 (a same-version edit)."""
    recorded = {entry["version"]: entry["sha256"] for entry in history["entries"]}
    version = package.package_version
    if version not in recorded:
        return EXIT_PIN, (f"golden-set gate: package_version {version} is not in the package version history: rerun "
                          "scripts/run_golden_set.py --write (it appends the version) and commit the history with the record")
    if recorded[version] != package.sha256:
        return EXIT_PIN, (f"golden-set gate: package_version {version} is recorded in the package version history with sha256 "
                          f"{recorded[version]}, but the package's sha256 is {package.sha256}: bump package_version (config_version "
                          "is the package version, and the rising-A/B stop sees a change only where it differs), then rehash and "
                          "rerun --write")
    return None


def base_history_at(ref: str) -> dict | None:
    """The committed package version history at a git ref (CI: the pull request's base branch), or None when the ref
    has no history file (before the first merge). ValueError for an unknown ref, a failed read or a malformed file.
    git show reads file content at the ref, so a squash merge does not matter."""
    try:
        if _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
            raise ValueError(f"the base ref {ref!r} is not a commit in this clone (fetch it first)")
        if _git("cat-file", "-e", f"{ref}:{HISTORY_REPO_PATH}").returncode != 0:
            return None
        shown = _git("show", f"{ref}:{HISTORY_REPO_PATH}")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"the base history at {ref!r} cannot be read: {exc}") from exc
    if shown.returncode != 0:
        raise ValueError(f"the base history at {ref!r} cannot be read: {shown.stderr.strip()}")
    return parse_history(shown.stdout)


def base_problem(base: dict | None, history: dict) -> tuple[int, str] | None:
    """Append-only against the base: every entry of the base's history, in order and unchanged, starts the history."""
    if base is None:
        return None
    expected = base["entries"]
    if history["entries"][:len(expected)] != expected:
        changed = [entry["version"] for entry in expected if entry not in history["entries"]]
        return EXIT_PIN, (f"golden-set gate: the package version history rewrites or removes the base branch's entries "
                          f"({', '.join(changed) or 'their order'}): the history is append-only, so a package edit needs a "
                          "new package_version; restore the base entries and rerun --write")
    return None


def append_problem(history: dict, package) -> tuple[int, str] | None:
    """--write's refusal: a recorded version with a different sha256, or a new version not newer than the newest entry."""
    if package.package_version in {entry["version"] for entry in history["entries"]}:
        return history_problem(history, package)
    newest = history["entries"][-1]["version"] if history["entries"] else None
    if newest is not None and _version_key(package.package_version) <= _version_key(newest):
        return EXIT_PIN, (f"golden-set gate: package_version {package.package_version} is not newer than the newest recorded "
                          f"package_version {newest}: the package version history is append-only")
    return None


def main(argv: list[str] | None = None) -> int:
    """The CLI; the qcai loggers are quietened for the run and restored after it (an in-process call leaves no trace)."""
    logger = logging.getLogger("qcai")
    previous = logger.level
    try:
        return _main(argv)
    finally:
        logger.setLevel(previous)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="--write from a working tree that differs from HEAD")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE_PATH, help="the configuration package (default: the shipped package)")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY, help="the append-only package version history")
    base_source = parser.add_mutually_exclusive_group()
    base_source.add_argument("--base-ref", help="a git ref whose committed history must be an unchanged prefix (CI: the base branch)")
    base_source.add_argument("--base-history", type=Path, help="a history file that must be an unchanged prefix")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    logging.getLogger("qcai").setLevel(logging.ERROR)
    target = args.write or args.check
    try:
        _refuse_lqs(target)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    try:
        package = load_config_package(args.package, governed=False)
    except Exception as exc:  # noqa: BLE001 - a package that does not load is a refusal
        print(f"refused: the package does not load: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if package.ehmf is None:
        print("refused: the package has no ehmf block", file=sys.stderr)
        return EXIT_USAGE
    try:
        _version_key(package.package_version)
    except ValueError as exc:
        print(f"refused: {exc} (the package version history orders versions as MAJOR.MINOR.PATCH)", file=sys.stderr)
        return EXIT_USAGE
    try:
        _refuse_lqs(args.history)
        history = load_history(args.history)
        if args.base_history is not None:
            _refuse_lqs(args.base_history)
            base = load_history(args.base_history)
        else:
            base = base_history_at(args.base_ref) if args.base_ref else None
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.check:
        try:
            committed = json.loads(args.check.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"refused: the golden run record cannot be read: {exc}", file=sys.stderr)
            return EXIT_USAGE
        mismatch = check_pins(committed, package) or history_problem(history, package) or base_problem(base, history)
        if mismatch is not None:
            print(mismatch[1], file=sys.stderr)
            return mismatch[0]
    else:
        if not args.allow_dirty and _commit().endswith("-dirty"):
            print("refused: the working tree differs from HEAD; commit first, or pass --allow-dirty", file=sys.stderr)
            return EXIT_DIRTY
        try:
            previous = json.loads(args.write.read_text(encoding="utf-8")) if args.write.exists() else None
        except (OSError, ValueError) as exc:
            print(f"refused: the golden run record cannot be read: {exc}", file=sys.stderr)
            return EXIT_USAGE
        refusal = ((same_version_edit(previous, package) if isinstance(previous, dict) else None) or base_problem(base, history)
                   or append_problem(history, package))
        if refusal is not None:
            print(refusal[1], file=sys.stderr)
            return refusal[0]
    fresh = _finish_inputs(compute(package_path=args.package))
    if args.write:
        if fresh["result"] == "pass" and package.package_version not in {entry["version"] for entry in history["entries"]}:
            history["entries"].append({"version": package.package_version, "sha256": package.sha256})
            args.history.write_text(json.dumps(history, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: result {fresh['result']}; {len(fresh['outcomes'])} items; citations {fresh['citation_resolution']['share']}")
        return EXIT_OK if fresh["result"] == "pass" else EXIT_UNMET
    for problem in fresh["problems"]:
        print(f"golden-set gate: {problem}", file=sys.stderr)
    if fresh["result"] != "pass":
        return EXIT_UNMET
    if _strip(committed) != _strip(fresh):
        differing = sorted(key for key in set(committed) | set(fresh) if key not in {"created_at", "commit"}
                           and _strip(committed.get(key)) != _strip(fresh.get(key)))
        print(f"golden-set gate: drift: the record differs from a fresh run in: {', '.join(differing)} (drift blocks promotion, 12.5)", file=sys.stderr)
        return EXIT_DRIFT
    print(f"golden run is current: {len(fresh['outcomes'])} items met; citations {fresh['citation_resolution']['share']}; {EVIDENCE_CLASS}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
