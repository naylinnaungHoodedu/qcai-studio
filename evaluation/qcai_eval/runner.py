"""The E1-E4 runner: pins, holds, units, requests, checkpointed execution and the run record (spec 3.9-3.12, 4.12-4.13).

Plan task 5: "Pinned configuration package [Evidence E-97]; E1-E4 per Section 15 [Evidence E-99]; statistics with hashed
seeds [Evidence E-103]." A run pins the package (path and sha256, read-only), the items, the evidence catalog, the arms and
the analysis plan by sha256; its seeds are hashed from (run_id, arm, item_id, replicate). Stub and recorded runs repeat
byte for byte: no byte-compared output (the run record and the payload log) carries the wall clock or an absolute path,
and both depend only on the plan and the responses; only a confirmatory or live run's start event in `run_events.jsonl`,
which is not byte-compared, carries the UTC day the run was planned (`started_on`). Hold H12 refuses every run over non-synthetic data while D-14 is open; live runs are refused here.
Every run is exploratory unless its spec says confirmatory, and E1-E4 runs must be confirmatory (plan 12.7). A spec that
omits `replicates` or `retries` takes the provisional paper values in `evaluation/config/harness_parameters_v1.json`
(PD-68), and a live or confirmatory spec must keep a replicate subsample so that the record reports replicate variance.
A resumed run continues only its own checkpoint: the start event pins a run digest (and, for a confirmatory or live run,
the UTC day it was planned, `started_on`), and every reused response line must match its planned request. A confirmatory
or live run is judged in its run window (governance module docstring): `today`, and `start`, the earliest of today, its
checkpoint's `started_on` and a live recording's `started_on`; an earlier `start` only tightens the record checks. A confirmatory run covers
every live item, the calibration and the confirmation split alike (paper Sec. VIII E1: "All ULQS items run through all
seven arms"; the registered data "all ULQS items x seven arms"); the split exists for threshold calibration, which uses
the calibration split only (plan L470), and no Phase 10 code fits a threshold.
"""

from __future__ import annotations

from collections import Counter
import contextlib
from dataclasses import dataclass, field
import datetime as _dt
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from . import ablation, analysis_plans, governance, planes, statistics, ulqs
from .abstention import abstention_by_turn_depth, correct_abstention
from .canonical import canonical_json, canonical_sha256, dumps_line, dumps_record, hashed_hex, lf_sha256, read_jsonl, write_lf
from .citation import citation_existence
from .fabrication import fabrication_rate
from .faithfulness import citation_faithfulness
from .invariance import invariance_violations
from .payload_log import PayloadLogViolation, log_record, validate_log_record
from .pointers import EvidenceCatalog, PointerResolver, public_span_lookup, resolve_items
from .providers import RecordedResponder

PROVISIONAL_DEFAULTS = ("PD-61", "PD-68", "PD-73")
REPO_ROOT = planes.REPO_ROOT
HARNESS_PARAMETERS = REPO_ROOT / "evaluation" / "config" / "harness_parameters_v1.json"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9.+:-]{0,63}$")
CREATED_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_RETRIES = 10
SPEC_FORMAT = "ulqs-run-spec-v1"
RECORD_FORMAT = "ulqs-run-record"
MODES = ("stub", "recorded", "live")
PURPOSES = ("exploratory", "confirmatory")
EXPERIMENTS = ("harness-check", "E1", "E2", "E3", "E4")
SEEDS_RULE = "sha256-run-arm-item-replicate-v1"
SUBSAMPLE_RULE = "sha256-order-v1"
RESPONSES = "responses.jsonl"
PAYLOAD_LOG = "payload_log.jsonl"
RUN_EVENTS = "run_events.jsonl"
RUN_RECORD = "run_record.json"
ERROR_LABELS = frozenset({"fabricated", "attribution_error"})
SYNTHETIC_COMPARISON_NOTE = "synthetic: no arm effect by construction (R-f)"
EXPLORATORY_CLASS = ("exploratory run; not a confirmatory test; no Table XVII row or HR-1..MR-3 outcome is asserted (invariant 9)")
CONFIRMATORY_CLASS = "confirmatory run under the filed pre-registration; outcomes are reported by the PI, never asserted by the harness"
CODE_FILES = ("scripts/run_evaluation.py",)


class RunRefused(Exception):
    def __init__(self, code: int, reasons: Sequence[str]) -> None:
        super().__init__(f"exit {code}: {', '.join(reasons)}")
        self.code = code
        self.reasons = list(reasons)


class RunInterrupted(Exception):
    """A provider outage stopped the run at its checkpoint (exit 5); `--resume` continues it."""


@dataclass(frozen=True)
class Request:
    request_key: str
    arm: str
    item_id: str
    unit: str | None
    turn_depth: int | None
    replicate: int
    seed_hex: str
    evidence: tuple[str, ...]
    gold: str
    gold_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    spec: Mapping[str, Any]
    package_raw: Mapping[str, Any]
    items: tuple[Mapping[str, Any], ...]
    arms: ablation.ArmTable
    requests: tuple[Request, ...]
    pins: dict
    resolver: PointerResolver | None = None
    synthetic: bool = True
    recording_source: str | None = None
    # A confirmatory or live run (`dated`) was judged in its run window when planned: `planned_on` (today then; a fresh
    # start's event records it as `started_on`) and `checkpoint_start` (the `started_on` of the output's start event that
    # a resume was planned from, or None). `execute_run` requires the output to be the checkpoint the plan was judged on.
    dated: bool = False
    planned_on: _dt.date | None = None
    checkpoint_start: _dt.date | None = None
    extra: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------------------ helpers


def _path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(repo_root) / path


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunRefused(2, ["spec_unreadable"]) from None
    if not isinstance(spec, dict):
        raise RunRefused(2, ["spec_not_an_object"])
    return spec


def seed_hex(run_id: str, arm: str, item_id: str, replicate: int) -> str:
    return hashed_hex(run_id, arm, item_id, str(replicate))[:16]


def request_key(arm_config_sha256: str, item_id: str, unit: str | None, replicate: int, package_sha256: str, prompt_version: str,
                evidence: Sequence[str]) -> str:
    return canonical_sha256({"arm_config": arm_config_sha256, "item_id": item_id, "unit": unit, "replicate": replicate,
                             "package": package_sha256, "prompt_version": prompt_version, "evidence": sorted(evidence)})


def _units(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A-E: one unit; F: one unit per turn (with its depth); G: one unit per level, with identical evidence."""
    stratum = item["stratum"]
    claims = lambda record: tuple(claim["claim_id"] for claim in record.get("atomic_claims", []) or [])  # noqa: E731
    if stratum == "F":
        return [{"unit": turn["turn_id"], "turn_depth": depth, "evidence": tuple(turn.get("evidence_ids", []) or []),
                 "gold": turn["expected_behavior"], "gold_claims": claims(turn)}
                for depth, turn in enumerate(item.get("conversation", []), start=1)]
    if stratum == "G":
        return [{"unit": level, "turn_depth": None, "evidence": tuple(item.get("evidence_ids", []) or []), "gold": "answer",
                 "gold_claims": claims(item)} for level in ulqs.REPLAY_LEVELS]
    return [{"unit": None, "turn_depth": None, "evidence": tuple(item.get("evidence_ids", []) or []),
             "gold": item["expected_behavior"], "gold_claims": claims(item)}]


def load_harness_parameters(path: Path = HARNESS_PARAMETERS) -> dict[str, Any]:
    """The provisional run defaults (PD-68): the paper's replicate subsample and retries, and the replicate-variance rule."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("parameters") != "harness-parameters-v1" or raw.get("provisional") is not True:
        raise ValueError("not a provisional harness-parameters-v1 file")
    if _replicate_problems(raw.get("replicates")) or not _integer(raw.get("retries"), 0, MAX_RETRIES):
        raise ValueError("harness parameters: replicates or retries out of range")
    if not _integer((raw.get("replicate_variance_required") or {}).get("min_replicates"), 2):
        raise ValueError("harness parameters: replicate_variance_required.min_replicates")
    return raw


def _integer(value: Any, low: int, high: int | None = None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= low and (high is None or value <= high)


def _replicate_problems(value: Any) -> list[str]:
    if not isinstance(value, Mapping) or not _integer(value.get("default"), 1, 100):
        return ["replicates"]
    block = value.get("subsample")
    if block is None:
        return []
    if (not isinstance(block, Mapping) or block.get("stratum") not in ulqs.STRATA or not _integer(block.get("size"), 1)
            or not _integer(block.get("replicates"), 1, 100) or block.get("rule", SUBSAMPLE_RULE) != SUBSAMPLE_RULE):
        return ["replicates.subsample"]
    return []


def effective_replicates(spec: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(spec["replicates"] if "replicates" in spec else parameters["replicates"]))


def effective_retries(spec: Mapping[str, Any], parameters: Mapping[str, Any]) -> int:
    return int(spec["retries"] if "retries" in spec else parameters["retries"])


def subsample(items: Sequence[Mapping[str, Any]], replicates: Mapping[str, Any]) -> list[str]:
    block = replicates.get("subsample")
    if not block:
        return []
    members = sorted((item["item_id"] for item in items if item.get("stratum") == block["stratum"] and item.get("status") != "retired"),
                     key=lambda item_id: hashed_hex(SUBSAMPLE_RULE, item_id))
    return members[: int(block["size"])]


def _decided(package_raw: Mapping[str, Any], name: str) -> bool:
    return ((package_raw.get("owner_decisions") or {}).get(name) or {}).get("state") == "decided"


def _sidecar(path: Path) -> str | None:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        return None
    return sidecar.read_text(encoding="utf-8").strip() or None


def arm_manifest(table: ablation.ArmTable, arm: str, common: Mapping[str, Any]) -> dict[str, Any]:
    return {**ablation.arm_configuration(table, arm), **common}


def code_pins(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    package = Path(repo_root) / Path(__file__).resolve().parent.relative_to(REPO_ROOT)
    modules = sorted(package.glob("*.py"))
    pins = {path.relative_to(repo_root).as_posix(): lf_sha256(path) for path in modules}
    for name in CODE_FILES:
        path = Path(repo_root) / name
        if path.exists():
            pins[name] = lf_sha256(path)
    return pins


def recording_pins(package_sha: str, items_sha: str, catalog_sha: str | None, arms_sha: str, prompt_version: str) -> str:
    return canonical_sha256({"package": package_sha, "items": items_sha, "catalog": catalog_sha, "arms": arms_sha,
                             "prompt_version": prompt_version})


# ------------------------------------------------------------------------------------------------------------ planning


def _created_at_ok(value: Any) -> bool:
    if not isinstance(value, str) or not CREATED_AT.match(value):
        return False
    try:
        _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _type_problems(spec: Mapping[str, Any]) -> list[str]:
    """Every nested shape the planner reads, so that a malformed spec is refused (exit 2), never a traceback."""
    reasons = []
    for key in ("package", "items", "arms", "analysis_plan", "evidence_catalog"):
        if key not in spec or (key == "evidence_catalog" and spec[key] is None):
            continue
        value = spec[key]
        if not isinstance(value, Mapping) or not isinstance(value.get("path"), str) or not value["path"]:
            reasons.append(f"{key}.path")
    items = spec.get("items")
    if isinstance(items, Mapping):
        if not _integer(items.get("count"), 0):
            reasons.append("items.count")
        if items.get("required_state", "any") not in ("any", "frozen"):
            reasons.append("items.required_state")
    arms = spec.get("arms")
    if isinstance(arms, Mapping) and arms.get("selected") is not None and (
            not isinstance(arms["selected"], list) or not all(isinstance(arm, str) for arm in arms["selected"])):
        reasons.append("arms.selected")
    plan = spec.get("analysis_plan")
    if isinstance(plan, Mapping) and not isinstance(plan.get("family"), str):
        reasons.append("analysis_plan.family")
    seeds = spec.get("seeds", {})
    if not isinstance(seeds, Mapping):
        reasons.append("seeds")
    elif seeds.get("rule", SEEDS_RULE) != SEEDS_RULE:
        reasons.append("seeds.rule")
    if "created_at" in spec and not _created_at_ok(spec["created_at"]):
        reasons.append("created_at")
    if "replicates" in spec:
        reasons += _replicate_problems(spec["replicates"])
    if "retries" in spec and not _integer(spec["retries"], 0, MAX_RETRIES):
        reasons.append("retries")
    for key in ("responder", "governance"):
        if key in spec and not isinstance(spec[key], Mapping):
            reasons.append(key)
    responder = spec.get("responder")
    if isinstance(responder, Mapping):
        recorded, live = responder.get("recorded"), responder.get("live")
        if recorded is not None and not (isinstance(recorded, Mapping) and isinstance(recorded.get("path"), str) and recorded["path"]
                                         and isinstance(recorded.get("sha256"), str)):
            reasons.append("responder.recorded")
        if live is not None and not (isinstance(live, Mapping) and isinstance(live.get("adapter"), (str, type(None)))
                                     and isinstance(live.get("providers", []), list)
                                     and all(isinstance(provider, str) for provider in live.get("providers", []))):
            reasons.append("responder.live")
        if not isinstance(responder.get("rule", ""), str):
            reasons.append("responder.rule")
    bootstrap = spec.get("bootstrap")
    if bootstrap is not None:
        ok = isinstance(bootstrap, Mapping) and _integer(bootstrap.get("resamples", 1000), 1)
        if ok:
            level = bootstrap.get("level", "0.95")
            try:
                ok = isinstance(level, str) and 0 < Fraction(level) < 1
            except (ValueError, ZeroDivisionError):
                ok = False
        if not ok:
            reasons.append("bootstrap")
    for key in ("freeze_record", "pre_run_scan", "licence_ruling", "research_use_confirmation"):
        if spec.get(key) is not None and not isinstance(spec[key], Mapping):
            reasons.append(key)
    terms = spec.get("provider_terms")  # one reference, or one per provider the live run queries
    if terms is not None and not (isinstance(terms, Mapping) or (isinstance(terms, list) and terms
                                                                 and all(isinstance(entry, Mapping) for entry in terms))):
        reasons.append("provider_terms")
    return reasons


def _check_shape(spec: Mapping[str, Any], parameters: Mapping[str, Any]) -> None:
    reasons = []
    if spec.get("run_spec") != SPEC_FORMAT:
        reasons.append("run_spec")
    for key in ("run_id", "created_at", "package", "items", "arms", "analysis_plan", "responder", "governance"):
        if key not in spec:
            reasons.append(f"missing:{key}")
    if spec.get("mode") not in MODES:
        reasons.append("mode")
    if spec.get("purpose") not in PURPOSES:
        reasons.append("purpose")
    if spec.get("experiment") not in EXPERIMENTS:
        reasons.append("experiment")
    run_id = spec.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.match(run_id):
        reasons.append("run_id")
    reasons += _type_problems(spec)
    if reasons:
        raise RunRefused(2, reasons)
    if spec["experiment"] in ("E1", "E2", "E3", "E4") and spec["purpose"] != "confirmatory":
        raise RunRefused(2, ["experiment_requires_confirmatory"])
    if spec["experiment"] == "harness-check" and spec["purpose"] == "confirmatory":
        raise RunRefused(2, ["harness_check_not_confirmatory"])
    # AC-10-3: live runs report replicate variance; confirmatory runs too (PD-68). Both need a subsample with at least
    # `min_replicates` replicates.
    if spec["mode"] == "live" or spec["purpose"] == "confirmatory":
        block = effective_replicates(spec, parameters).get("subsample") or {}
        if int(block.get("replicates", 0)) < int(parameters["replicate_variance_required"]["min_replicates"]):
            raise RunRefused(2, ["replicate_subsample_required"])


def _file_sha256(path: Path) -> str | None:
    """The LF sha256 of a file, or None when it cannot be opened: an OSError, or a ValueError for a path open() refuses
    (an embedded NUL), so that the refusal the caller raises next is never replaced by a traceback."""
    try:
        return lf_sha256(path)
    except (OSError, ValueError):
        return None


def plan_run(spec: Mapping[str, Any], *, repo_root: Path = REPO_ROOT, environ: Mapping[str, str] = os.environ,
             out_dir: Path | None = None, access_log: Path | None = None, on_read: Callable[[str, str], None] | None = None,
             resume: bool = False) -> Plan:
    """The run's plan, or RunRefused. `on_read(kind, sha256)` is told of each research-plane input as soon as it is read
    (the items, the catalog, the recording and every governance record), before any later check can refuse the run, so
    that the access log holds every read of a refused run too. With `resume` and `out_dir`, a confirmatory or live run's
    window starts on the day its checkpoint's start event records (`checkpoint_start_refusals`); that read of
    `run_events.jsonl` is reported as `run_output` (the sha256 of its bytes) before it can refuse the run."""
    def note(kind: str, sha256: str | None) -> None:
        if on_read is not None and sha256 is not None:
            on_read(kind, sha256)

    with governance.observe_reads(note if on_read is not None else None):
        return _plan_run(spec, repo_root=Path(repo_root), environ=environ, out_dir=out_dir, access_log=access_log, note=note,
                         resume=resume)


def _plan_run(spec: Mapping[str, Any], *, repo_root: Path, environ: Mapping[str, str], out_dir: Path | None,
              access_log: Path | None, note: Callable[[str, str | None], None], resume: bool = False) -> Plan:
    try:
        parameters_raw = load_harness_parameters()
    except (OSError, ValueError):
        raise RunRefused(6, ["harness_parameters_invalid"]) from None
    _check_shape(spec, parameters_raw)
    replicates = effective_replicates(spec, parameters_raw)
    retries = effective_retries(spec, parameters_raw)
    # 2. The package, by explicit path and sha256 (never the application's default path).
    package_path = _path(spec["package"]["path"], repo_root)
    try:
        package_raw = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunRefused(6, ["package_unreadable"]) from None
    package_sha = canonical_sha256(package_raw)
    if package_sha != spec["package"].get("sha256") or _sidecar(package_path) != package_sha:
        raise RunRefused(6, ["package_sha256"])
    # 3. The items.
    items_path = _path(spec["items"]["path"], repo_root)
    try:
        items = tuple(read_jsonl(items_path))
    except (OSError, ValueError):
        note("ulqs_items", _file_sha256(items_path))
        raise RunRefused(3, ["items_unreadable"]) from None
    problems = ulqs.validate_dataset(items)
    note("ulqs_items", _file_sha256(items_path) if problems else ulqs.dataset_sha256(items))
    if problems:
        raise RunRefused(3, ["items_invalid"] + [str(problem) for problem in problems[:20]])
    items_sha = ulqs.dataset_sha256(items)
    items_content_sha = ulqs.dataset_content_sha256(items)
    if items_sha != spec["items"].get("sha256") or len(items) != spec["items"].get("count"):
        raise RunRefused(6, ["items_sha256"])
    states = Counter(item["status"] for item in items)
    if spec["items"].get("required_state", "any") == "frozen" and any(
            item["status"] not in ulqs.FROZEN_STATES for item in items if item["status"] != "retired"):
        raise RunRefused(3, ["items_not_frozen"])
    # 4. The evidence catalog and every pointer.
    catalog = None
    catalog_sha = None
    if spec.get("evidence_catalog"):
        catalog_path = _path(spec["evidence_catalog"]["path"], repo_root)
        try:
            catalog = EvidenceCatalog.load(catalog_path)
        except (OSError, ValueError):
            note("evidence_catalog", _file_sha256(catalog_path))
            raise RunRefused(3, ["catalog_invalid"]) from None
        catalog_sha = catalog.sha256
        note("evidence_catalog", catalog_sha)
        if catalog_sha != spec["evidence_catalog"].get("sha256"):
            raise RunRefused(6, ["catalog_sha256"])
    corpus_versions = {item["corpus_version"] for item in items}
    needs_spans = any(pointer.startswith("span-") for item in items for _p, pointer in ulqs.pointers_of(item))
    resolver = PointerResolver(catalog=catalog, span_lookup=public_span_lookup() if needs_spans else None,
                               corpus_version=next(iter(corpus_versions)) if len(corpus_versions) == 1 else None)
    report = resolve_items(items, resolver)
    if report.problems:
        raise RunRefused(3, ["unresolved_pointers"] + [f"{item}:{path}:{status}" for item, path, status, _kind in report.problems[:20]])
    # 5. The arms and parity.
    try:
        arms_raw = json.loads(_path(spec["arms"]["path"], repo_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunRefused(6, ["arms_unreadable"]) from None
    arms_sha = canonical_sha256(arms_raw)
    if arms_sha != spec["arms"].get("sha256"):
        raise RunRefused(6, ["arms_sha256"])
    selected = list(spec["arms"].get("selected") or ablation.ARM_IDS)
    try:
        table = ablation.table_from_raw(arms_raw)
        ablation.check_table(table)
        if any(arm not in ablation.ARM_IDS for arm in selected) or "GATE" not in selected or len(set(selected)) != len(selected):
            raise ablation.ParityError("arms.selected: a subset of the seven arms that includes GATE")
        prompt_version = str(table.gate_configuration.get("prompt_version"))
        responder_rule = _responder_rule(spec)
        common = {"package_sha256": package_sha, "items_sha256": items_sha, "catalog_sha256": catalog_sha,
                  "prompt_version": prompt_version, "seeds_rule": SEEDS_RULE, "replicates": replicates,
                  "retries": retries, "responder_rule": responder_rule}
        manifests = {arm: arm_manifest(table, arm, common) for arm in selected}
        manifests = _manifest_hook(manifests)
        ablation.assert_arm_parity(manifests, table=table, required=selected)
    except ablation.ParityError as error:
        raise RunRefused(7, [str(error)]) from None
    # 6. The analysis plan.
    try:
        plans_raw = json.loads(_path(spec["analysis_plan"]["path"], repo_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunRefused(6, ["analysis_plan_unreadable"]) from None
    plans_sha = canonical_sha256(plans_raw)
    if plans_sha != spec["analysis_plan"].get("sha256"):
        raise RunRefused(6, ["analysis_plan_sha256"])
    try:
        analysis_plans.validate_plans(plans_raw)
    except analysis_plans.PlanError as error:
        raise RunRefused(2, [f"analysis_plan_invalid:{error}"]) from None
    if spec["analysis_plan"].get("family") not in analysis_plans.FAMILIES:
        raise RunRefused(2, ["analysis_plan.family"])
    # 7. Hold H12: no run over non-synthetic data while the research data plane (D-14) is not decided.
    synthetic = planes.all_synthetic(items) and (catalog is None or all(r.volume == "synthetic" for r in catalog.records.values()))
    if not synthetic:
        if not _decided(package_raw, "D-14"):
            raise RunRefused(9, ["hold_h12_data_plane"])
        missing = []
        if access_log is None:
            missing.append("access_log_required")
        missing += governance.scan_refusals(spec.get("pre_run_scan"), repo_root, dataset_content_sha256=items_content_sha,
                                            missing="pre_run_scan_required")
        if missing:
            raise RunRefused(2, missing)
    # The recorded responder and its pins.
    recording_source = recording_started_on = None
    dated = spec["mode"] == "live" or spec["purpose"] == "confirmatory"
    if spec["mode"] == "recorded":
        recorded = (spec.get("responder") or {}).get("recorded") or {}
        recording_path = _path(recorded["path"], repo_root) if "path" in recorded else None
        recording_sha = None if recording_path is None else _file_sha256(recording_path)
        note("recording", recording_sha)
        try:
            if recording_path is None:
                raise KeyError("path")
            responder = RecordedResponder(recording_path)
        except (KeyError, OSError, ValueError):
            raise RunRefused(6, ["recording_unreadable"]) from None
        if recording_sha != recorded.get("sha256"):
            raise RunRefused(6, ["recording_sha256"])
        if responder.header.get("run_pins_sha256") != recording_pins(package_sha, items_sha, catalog_sha, arms_sha, prompt_version):
            raise RunRefused(6, ["recording_pins_mismatch"])
        recording_source = responder.source
        recording_started_on = responder.header.get("started_on")
    # The run window (governance module docstring): `today`, and `start`, the earliest of today, the checkpoint's start
    # day (a resume) and the live recording's start day (a confirmatory replay). Each earlier day only tightens.
    today = governance.utc_today()
    window: list[str] = []
    checkpoint_start = None
    if dated and resume and out_dir is not None:
        note("run_output", checkpoint_sha256(Path(out_dir) / RUN_EVENTS))
        window, checkpoint_start = checkpoint_start_refusals(Path(out_dir), today)
    starts = [today] + ([checkpoint_start] if checkpoint_start else [])
    if dated and spec["mode"] == "recorded" and recording_source == "live":
        recording_reasons = governance.recording_start_refusals(recording_started_on, today)
        window += recording_reasons
        if not recording_reasons:
            starts.append(governance.iso_day(recording_started_on))
    start = min(starts)
    # 8. The confirmatory gate (AC-10-5).
    if spec["purpose"] == "confirmatory":
        reasons = window + governance.confirmatory_refusals(
            spec, analysis_plan_sha256=plans_sha, dataset_sha256=items_sha, dataset_content_sha256=items_content_sha,
            items_states=states, package_raw=package_raw, repo_root=repo_root, recording_source=recording_source, start=start,
            today=today)
        # Plan 10.5(2) "calibration and confirmation items split [Risk R-25]": every live item of a confirmatory run
        # carries its split, so that a threshold fitted on ULQS uses the calibration split only (plan L470). The run itself
        # covers every live item (`_requests`).
        if any(item.get("split") not in ulqs.SPLITS for item in items if item.get("status") != "retired"):
            reasons.append("items_split_missing")
        # The replicate subsample (PD-68, the paper's "three replicates on a 40-item S1 subsample") must be met in full:
        # a confirmatory run whose subsample stratum holds fewer live items than its size is refused, never replicated
        # over fewer items than its record pins.
        if len(subsample(items, replicates)) < int((replicates.get("subsample") or {}).get("size", 0)):
            reasons.append("replicate_subsample_short")
        if reasons:
            raise RunRefused(governance.confirmatory_exit_code(reasons), reasons)
    # 9. Live runs.
    if spec["mode"] == "live":
        from .providers import live_refusal_reasons

        reasons = live_refusal_reasons(spec, package_raw, environ, table, out_dir=out_dir, repo_root=repo_root, start=start,
                                       today=today)
        if spec["purpose"] != "confirmatory":
            reasons = window + reasons
        if reasons:
            raise RunRefused(9, reasons)
    # 10. The output directory.
    if out_dir is not None:
        if synthetic:
            if planes.inside_checkout(out_dir, repo_root):
                raise RunRefused(2, ["output_inside_checkout"])
        else:
            try:
                planes.require_private_output(out_dir, root=repo_root)
            except planes.PathRefused:
                raise RunRefused(2, ["output_not_private"]) from None
    requests = _requests(spec, items, table, selected, package_sha, prompt_version, replicates)
    pins = {
        "package": {"path": spec["package"]["path"] if not Path(spec["package"]["path"]).is_absolute() else package_path.name,
                    "sha256": package_sha, "package_version": package_raw.get("package_version"),
                    "owner_decisions": {name: ((package_raw.get("owner_decisions") or {}).get(name) or {}).get("state")
                                        for name in ("D-07", "D-08", "D-12", "D-14")}},
        "models": None,
        "items": {"sha256": items_sha, "count": len(items), "states": dict(sorted(states.items())),
                  "corpus_version": sorted(corpus_versions)[0] if len(corpus_versions) == 1 else sorted(corpus_versions)},
        "evidence_catalog": None if catalog is None else {"sha256": catalog_sha, "corpus_version": catalog.corpus_version},
        "arms": {"sha256": arms_sha, "selected": selected, "parity": "pass"},
        "analysis_plan": {"sha256": plans_sha, "family": spec["analysis_plan"]["family"]},
        "seeds": {"rule": SEEDS_RULE},
        "replicates": replicates,
        "bootstrap": spec.get("bootstrap"),
        "prompt_version": prompt_version,
        "retries": retries,
        "harness_parameters": {"sha256": canonical_sha256(parameters_raw), "used_for": sorted(
            key for key in ("replicates", "retries") if key not in spec)},
        "code": code_pins(repo_root),
    }
    return Plan(spec=dict(spec), package_raw=package_raw, items=items, arms=table, requests=tuple(requests), pins=pins,
                resolver=resolver, synthetic=synthetic, recording_source=recording_source, dated=dated,
                planned_on=today if dated else None, checkpoint_start=checkpoint_start)


def _manifest_hook(manifests: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The per-arm manifests as the run will use them (a seam the parity tests replace)."""
    return manifests


def _responder_rule(spec: Mapping[str, Any]) -> str:
    responder = spec.get("responder") or {}
    if spec.get("mode") == "stub":
        return str(responder.get("rule", "stub-responder-v1"))
    if spec.get("mode") == "recorded":
        return "recorded-responses-v1"
    return "live:" + str((responder.get("live") or {}).get("adapter"))


def _requests(spec, items, table, selected, package_sha, prompt_version, replicates) -> list[Request]:
    default = int(replicates.get("default", 1))
    sampled = set(subsample(items, replicates))
    extra = int((replicates.get("subsample") or {}).get("replicates", default))
    requests = []
    # Every live item, whatever its split: E1-E4 run all ULQS items (paper Sec. VIII; analysis_plans_v1.json "data").
    ordered_items = sorted((item for item in items if item.get("status") != "retired"), key=lambda item: item["item_id"])
    for arm in [arm for arm in ablation.ARM_IDS if arm in selected]:
        configuration = ablation.arm_configuration(table, arm)
        config_sha = canonical_sha256(configuration)
        for item in ordered_items:
            count = max(default, extra) if item["item_id"] in sampled else default
            for unit in _units(item):
                evidence = () if configuration["retrieval"] == "none" else tuple(sorted(unit["evidence"]))
                for replicate in range(1, count + 1):
                    key = request_key(config_sha, item["item_id"], unit["unit"], replicate, package_sha, prompt_version, evidence)
                    requests.append(Request(request_key=key, arm=arm, item_id=item["item_id"], unit=unit["unit"],
                                            turn_depth=unit["turn_depth"], replicate=replicate,
                                            seed_hex=seed_hex(spec["run_id"], arm, item["item_id"], replicate), evidence=evidence,
                                            gold=unit["gold"], gold_claims=unit["gold_claims"]))
    return requests


# ------------------------------------------------------------------------------------------------------------ execution


@contextlib.contextmanager
def _writing():
    """Every write into a run's output (the directory, each event, response line and record, the truncation of a partial
    checkpoint line on resume, the close of the responses file): one that fails (the output directory is a file or lies
    under one, an output file is a directory or cannot be opened for writing, a full disk) refuses the run
    (`output_unwritable`, exit 2), never a traceback. A checkpoint file that is a directory is refused the same way
    before it is read (`_require_file`)."""
    try:
        yield
    except OSError:
        raise RunRefused(2, ["output_unwritable"]) from None


def _append_event(out_dir: Path, event: Mapping[str, Any]) -> None:
    with _writing(), (Path(out_dir) / RUN_EVENTS).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps_line(event))


def requests_digest(plan: Plan) -> str:
    """sha256 of the sorted "request_key seed_hex" lines of the plan: the run record's `requests.digest`."""
    return hashlib.sha256("".join(f"{line}\n" for line in sorted(f"{r.request_key} {r.seed_hex}" for r in plan.requests)).encode()).hexdigest()


def run_digest(plan: Plan, responder_rule: str) -> str:
    """What a checkpoint belongs to: the run id, mode, purpose, `created_at`, responder rule, every pin and the planned
    keys and seeds (a resume therefore needs the spec the run started with)."""
    return canonical_sha256({"run_id": plan.spec["run_id"], "mode": plan.spec["mode"], "purpose": plan.spec["purpose"],
                             "created_at": plan.spec.get("created_at"), "responder_rule": responder_rule, "pins": plan.pins,
                             "requests": requests_digest(plan)})


def _require_file(path: Path) -> None:
    """A checkpoint path that exists but is not a file (a directory) is an output the run can never write: refused
    (`output_unwritable`, exit 2) before it is read, like every other output file that is a directory."""
    if path.exists() and not path.is_file():
        raise RunRefused(2, ["output_unwritable"])


def _read_checkpoint(path: Path, *, resume: bool) -> dict[str, dict]:
    """The completed responses of a checkpoint. Only the bytes after the last newline (a line an interrupted append left
    without its newline) are a partial line: `resume` truncates them and a run without it is refused
    (`partial_checkpoint`). Every newline-terminated line must be a response record, else the checkpoint is refused
    (`checkpoint_invalid`, exit 2) and nothing is deleted: a corrupt line never costs the lines after it. A file that
    cannot be read is `checkpoint_invalid` too; a path that is a directory is `output_unwritable` (`_require_file`)."""
    _require_file(path)
    if not path.exists():
        return {}
    try:
        data = path.read_bytes()
    except OSError:
        raise RunRefused(2, ["checkpoint_invalid"]) from None
    lines = data.split(b"\n")
    tail = lines.pop()  # the bytes after the last newline: empty when the file ends with one
    completed: dict[str, dict] = {}
    for line in lines:
        try:
            record = json.loads(line.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError included
            raise RunRefused(2, ["checkpoint_invalid"]) from None
        if not isinstance(record, dict) or not isinstance(record.get("request_key"), str) or not HEX64.match(record["request_key"]):
            raise RunRefused(2, ["checkpoint_invalid"])
        completed[record["request_key"]] = record
    if tail:
        if not resume:
            raise RunRefused(2, ["partial_checkpoint"])
        with _writing(), path.open("r+b") as handle:
            handle.truncate(len(data) - len(tail))
    elif completed and not resume:
        raise RunRefused(2, ["output_exists"])
    return completed


def _read_events(path: Path) -> list[dict]:
    """The run events of a checkpoint. A file that cannot be read, is not UTF-8 or holds a line that is not a JSON object
    is refused (`checkpoint_mismatch`, exit 2), never a traceback; a path that is a directory is `output_unwritable`
    (`_require_file`)."""
    _require_file(path)
    if not path.exists():
        return []
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise RunRefused(2, ["checkpoint_mismatch"]) from None
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            raise RunRefused(2, ["checkpoint_mismatch"]) from None
        if not isinstance(event, dict):
            raise RunRefused(2, ["checkpoint_mismatch"])
        events.append(event)
    return events


def verify_responses(plan: Plan, responses: Mapping[str, Mapping[str, Any]]) -> None:
    """Every response line belongs to a planned request and carries that request's arm, item, unit, replicate and seed."""
    planned = {request.request_key: request for request in plan.requests}
    for key, line in responses.items():
        request = planned.get(key)
        if request is None or any(line.get(name) != getattr(request, name) for name in ("arm", "item_id", "unit", "replicate", "seed_hex")):
            raise RunRefused(2, ["checkpoint_mismatch"])


def _prompt_envelope(plan: Plan, request: Request) -> bytes:
    return canonical_json({"prompt_version": plan.pins["prompt_version"], "item_id": request.item_id, "unit": request.unit,
                           "arm": request.arm, "evidence": list(request.evidence)})


def checkpoint_sha256(path: Path) -> str | None:
    """The sha256 of the bytes of a checkpoint file (`run_events.jsonl`, `responses.jsonl`) as the runner reads it, for the
    access log (`run_output`); None when it is not a file or cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
    except OSError:
        return None


def checkpoint_start_refusals(out_dir: Path, today: _dt.date) -> tuple[list[str], _dt.date | None]:
    """The start day a resumed confirmatory or live run's window takes from its checkpoint: none when the output holds no
    run events (the resume is a fresh start, judged on today); else the events must read as UTF-8 JSON objects and the
    first must be a `start` whose `started_on` is an ISO date not after today (`run_start_invalid`). Whoever can write the output can write a start event, but an
    earlier day only tightens the record checks, so a forged one gains nothing (DI-143 is an externally timestamped
    start). `execute_run` then checks the event's run digest (`checkpoint_mismatch`). A run_events.jsonl that is a
    directory is not a start that fails to read but an output the run cannot write: `output_unwritable` (RunRefused, exit 2)."""
    try:
        events = _read_events(Path(out_dir) / RUN_EVENTS)
    except RunRefused as refused:
        if refused.reasons == ["output_unwritable"]:
            raise
        return ["run_start_invalid"], None
    if not events:
        return [], None
    start = governance.iso_day(events[0].get("started_on")) if events[0].get("event") == "start" else None
    if start is None or start > today:
        return ["run_start_invalid"], None
    return [], start


def execute_run(plan: Plan, responder: Any, out_dir: Path, *, resume: bool = False, commit: str | None = None,
                on_read: Callable[[str, str], None] | None = None) -> dict:
    """Run the plan into `out_dir` (spec 4.12). `on_read("run_output", sha256)` is told of each checkpoint file the run
    reads (`run_events.jsonl`, `responses.jsonl`; the sha256 of their bytes) before any check that can refuse it."""
    out_dir = Path(out_dir)
    if on_read is not None:
        for name in (RUN_EVENTS, RESPONSES):
            digest = checkpoint_sha256(out_dir / name)
            if digest is not None:
                on_read("run_output", digest)
    if plan.dated:
        # The output must be the checkpoint the plan's run window was judged on: a resume planned from a start event
        # continues that event's run, and a plan judged as a fresh start writes into an output without run events.
        events = _read_events(out_dir / RUN_EVENTS) if resume else []
        recorded = governance.iso_day(events[0].get("started_on")) if events else None
        if recorded != plan.checkpoint_start or (events and recorded is None):
            raise RunRefused(2, ["checkpoint_mismatch"])
    with _writing():
        out_dir.mkdir(parents=True, exist_ok=True)
    responses_path = out_dir / RESPONSES
    responder_rule = getattr(responder, "rule", "unknown")
    digest = run_digest(plan, responder_rule)
    events = _read_events(out_dir / RUN_EVENTS)
    if resume:
        # The checkpoint must be this run's: the first event is its start, which pins the run digest (run id, mode,
        # responder rule, pins and the planned keys and seeds). Nothing in another run's directory is touched before this.
        if events and (events[0].get("event") != "start" or events[0].get("run_digest") != digest):
            raise RunRefused(2, ["checkpoint_mismatch"])
        if not events and responses_path.exists() and responses_path.stat().st_size:
            raise RunRefused(2, ["checkpoint_mismatch"])
    completed = _read_checkpoint(responses_path, resume=resume)
    if not resume and events:
        raise RunRefused(2, ["output_exists"])
    verify_responses(plan, completed)
    spec = plan.spec
    base = {"run_id": spec["run_id"], "purpose": spec["purpose"], "planned_requests": len(plan.requests)}
    start = {"event": "resumed" if events else "start", **base, "completed_requests": len(completed), "run_digest": digest}
    if plan.dated and not events:
        start["started_on"] = plan.planned_on.isoformat()
    if commit:
        start["commit"] = commit
    _append_event(out_dir, start)
    retries = int(plan.pins["retries"])
    from .providers import ProviderOutage, TransientFailure

    with _writing():
        handle = responses_path.open("a", encoding="utf-8", newline="\n")
    try:
        for request in plan.requests:
            if request.request_key in completed:
                continue
            attempts: list[dict[str, str]] = []
            response = None
            for _attempt in range(1 + retries):
                try:
                    response = responder.respond(request)
                except TransientFailure as failure:
                    attempts.append({"status": failure.reason})
                    continue
                except ProviderOutage:
                    _append_event(out_dir, {"event": "interrupted", **base, "completed_requests": len(completed),
                                            "reason": "provider_outage"})
                    raise RunInterrupted(f"provider outage after {len(completed)} of {len(plan.requests)} requests") from None
                attempts.append({"status": "ok"})
                break
            line = _response_line(request, response, attempts)
            with _writing():
                handle.write(dumps_line(line))
                handle.flush()
                os.fsync(handle.fileno())
            completed[request.request_key] = line
    finally:
        with _writing():  # the close flushes: a flush that fails is an unwritable output too
            handle.close()
    responses = [completed[request.request_key] for request in plan.requests]
    verify_responses(plan, {line["request_key"]: line for line in responses})
    log_lines = []
    for request, response in zip(plan.requests, responses):
        record = log_record(request, response, run_id=spec["run_id"], purpose=spec["purpose"], prompt_version=plan.pins["prompt_version"],
                            prompt_bytes=_prompt_envelope(plan, request), resolver=plan.resolver)
        validate_log_record(record)
        log_lines.append(dumps_line(record))
    payload_text = "".join(log_lines)
    with _writing():
        write_lf(out_dir / PAYLOAD_LOG, payload_text)
    record = build_record(plan, responses, responder_rule=responder_rule,
                          payload_log_sha256=hashlib.sha256(payload_text.encode("utf-8")).hexdigest())
    with _writing():
        write_lf(out_dir / RUN_RECORD, dumps_record(record))
    _append_event(out_dir, {"event": "completed", **base, "completed_requests": len(responses)})
    return record


def _response_line(request: Request, response: Mapping[str, Any] | None, attempts: list[dict[str, str]]) -> dict[str, Any]:
    base = {"request_key": request.request_key, "arm": request.arm, "item_id": request.item_id, "unit": request.unit,
            "replicate": request.replicate, "seed_hex": request.seed_hex, "attempts": attempts}
    if response is None:
        return {**base, "outcome": "provider_failure", "failure_reason": attempts[-1]["status"] if attempts else "server_error",
                "claims": [], "text": None, "usage": {"input_units": 0, "output_units": 0}, "model_id": None}
    return {**base, "outcome": response["outcome"], "failure_reason": None, "claims": list(response.get("claims", [])),
            "text": response.get("text"), "usage": dict(response.get("usage") or {"input_units": 0, "output_units": 0}),
            "model_id": response.get("model_id")}


# ------------------------------------------------------------------------------------------------------------ metrics


def _unit_error(response: Mapping[str, Any], request: Request) -> int:
    if any(claim.get("label") in ERROR_LABELS for claim in response.get("claims", [])):
        return 1
    return int(request.gold == "abstain" and response["outcome"] == "answered")


def _pairs(plan: Plan, responses: Sequence[Mapping[str, Any]]):
    return list(zip(plan.requests, responses))


def compute_metrics(plan: Plan, responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    resolvable = set()
    if plan.resolver is not None:
        cited = {pointer for response in responses for claim in response.get("claims", []) for pointer in claim.get("cited", [])}
        resolvable = {pointer for pointer in cited if plan.resolver.resolve(pointer).status == "resolved"}
    metrics: dict[str, Any] = {}
    pairs = _pairs(plan, responses)
    for arm in plan.pins["arms"]["selected"]:
        rows = [(request, response) for request, response in pairs if request.arm == arm and request.replicate == 1]
        done = [(request, response) for request, response in rows if response["outcome"] != "provider_failure"]
        claims = [claim for _request, response in done for claim in response.get("claims", [])]
        unlabelled = sum(1 for claim in claims if claim.get("label") is None)
        if unlabelled:
            metrics[arm] = {"status": "awaiting_labels", "units": len(rows)}
            continue
        adapted = [{"cited_span_ids": list(claim.get("cited", [])), "category": claim.get("label")} for claim in claims]
        errors = sum(_unit_error(response, request) for request, response in done)
        citations = [(claim, pointer) for claim in claims for pointer in claim.get("cited", [])]
        supporting = [(claim, pointer) for claim, pointer in citations if pointer in resolvable and claim.get("label") == "supported"]
        covered = [claim for claim in claims if any(pointer in resolvable for pointer in claim.get("cited", [])) and claim.get("label") == "supported"]
        abstain_units = [{"expected_answerable": False, "abstained": response["outcome"] == "abstained"}
                         for request, response in done if request.gold == "abstain"]
        answer_units = [{"expected_answerable": True, "abstained": response["outcome"] == "abstained"}
                        for request, response in done if request.gold == "answer"]
        turns = [{"expected_answerable": request.gold == "answer", "abstained": response["outcome"] == "abstained",
                  "turn_depth": request.turn_depth} for request, response in done if request.turn_depth is not None]
        decay = {str(depth): value for depth, value in abstention_by_turn_depth(turns).items()} if turns else {}
        slope = statistics.least_squares_slope([(int(depth), value["rate"]) for depth, value in decay.items()])
        by_item: dict[str, dict[str, Mapping]] = {}
        for request, response in rows:
            if request.unit in ulqs.REPLAY_LEVELS:
                by_item.setdefault(request.item_id, {})[request.unit] = response
        complete = {item: levels for item, levels in sorted(by_item.items())
                    if len(levels) == 3 and all(r["outcome"] != "provider_failure" for r in levels.values())}
        replays = {item: [{"factual_claims": sorted(c["claim_id"] for c in levels[level].get("claims", [])),
                           "cited_span_ids": sorted({p for c in levels[level].get("claims", []) for p in c.get("cited", [])})}
                          for level in ulqs.REPLAY_LEVELS] for item, levels in complete.items()}
        metrics[arm] = {
            "units": len(rows),
            "provider_failures_excluded": len(rows) - len(done),
            "ER": statistics.wilson_interval(errors, len(done)),
            "CF": citation_faithfulness(adapted),
            "CP": {**statistics.wilson_interval(len(supporting), len(citations)), "proxy": "claim-level: resolving citations of supported claims"},
            "CR": {**statistics.wilson_interval(len(covered), len(claims)), "proxy": "claim-level: supported claims with a resolving citation"},
            "fabrication": fabrication_rate(adapted),
            "citation_existence": citation_existence(adapted, resolvable),
            "CA": correct_abstention(abstain_units),
            "AR": correct_abstention(answer_units),
            "abstention_decay": {"by_turn_depth": decay, "slope": slope},
            "IV": {**invariance_violations(replays), "items": len(replays), "excluded_items": len(by_item) - len(complete)},
        }
    return metrics


def _paired_errors(plan: Plan, responses, arm: str) -> dict[tuple, int]:
    return {(request.item_id, request.unit): _unit_error(response, request) for request, response in _pairs(plan, responses)
            if request.arm == arm and request.replicate == 1 and response["outcome"] != "provider_failure"}


def compute_comparisons(plan: Plan, responses, metrics) -> dict[str, Any]:
    selected = plan.pins["arms"]["selected"]
    if any(isinstance(metrics.get(arm), dict) and metrics[arm].get("status") == "awaiting_labels" for arm in selected):
        return {"status": "awaiting_labels"}
    gate = _paired_errors(plan, responses, "GATE")
    tests: dict[str, Any] = {}
    for arm in selected:
        if arm == "GATE":
            continue
        other = _paired_errors(plan, responses, arm)
        keys = sorted(set(gate) & set(other), key=lambda key: (key[0], key[1] or ""))
        tests[f"GATE-vs-{arm}"] = statistics.mcnemar_exact([bool(gate[key]) for key in keys], [bool(other[key]) for key in keys])
    corrected = statistics.holm({name: value["p_value"] for name, value in tests.items()}) if tests else {}
    return {"test": "mcnemar_exact", "correction": "holm", "pairs": tests, "holm": corrected,
            "note": SYNTHETIC_COMPARISON_NOTE if plan.synthetic else "exploratory comparison; not a pre-registered test"}


def compute_bootstrap(plan: Plan, responses, metrics) -> dict[str, Any] | None:
    selected = plan.pins["arms"]["selected"]
    settings = plan.spec.get("bootstrap")
    if not settings or "VLOOP" not in selected:
        return None
    if any(isinstance(metrics.get(arm), dict) and metrics[arm].get("status") == "awaiting_labels" for arm in ("VLOOP", "GATE")):
        return {"status": "awaiting_labels"}
    gate, vloop = _paired_errors(plan, responses, "GATE"), _paired_errors(plan, responses, "VLOOP")
    per_item: dict[str, list[int]] = {}
    for key in sorted(set(gate) & set(vloop), key=lambda key: (key[0], key[1] or "")):
        per_item.setdefault(key[0], []).append(vloop[key] - gate[key])
    clusters = [sum(values) / len(values) for _item, values in sorted(per_item.items())]
    if not clusters:
        return None
    seed = hashed_hex(plan.spec["run_id"], "bootstrap", "VLOOP-GATE-ER")
    result = statistics.bootstrap(clusters, lambda sample: sum(sample) / len(sample), resamples=int(settings.get("resamples", 1000)),
                                  seed=seed, level=str(settings.get("level", "0.95")))
    return {"quantity": "VLOOP - GATE item-level error difference", "clusters": "items", **result}


def compute_replicate_variance(plan: Plan, responses) -> dict[str, Any]:
    sampled = set(subsample(plan.items, plan.pins["replicates"]))
    variance: dict[str, Any] = {}
    if not sampled:
        return variance
    for arm in plan.pins["arms"]["selected"]:
        rates = []
        by_replicate: dict[int, list[int]] = {}
        for request, response in _pairs(plan, responses):
            if request.arm == arm and request.item_id in sampled and response["outcome"] != "provider_failure":
                if any(claim.get("label") is None for claim in response.get("claims", [])):
                    by_replicate = {}
                    break
                by_replicate.setdefault(request.replicate, []).append(_unit_error(response, request))
        for replicate in sorted(by_replicate):
            values = by_replicate[replicate]
            rates.append(sum(values) / len(values))
        variance[arm] = {"er_by_replicate": rates, "variance": statistics.sample_variance(rates), "rule": "sample-variance-v1"}
    return variance


def compute_slis(plan: Plan, responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = Counter(response["failure_reason"] for response in responses if response["outcome"] == "provider_failure")
    attempts = sum(len(response.get("attempts", [])) for response in responses)
    cost: dict[str, int] = {arm: 0 for arm in plan.pins["arms"]["selected"]}
    for response in responses:
        usage = response.get("usage") or {}
        cost[response["arm"]] = cost.get(response["arm"], 0) + int(usage.get("input_units", 0)) + int(usage.get("output_units", 0))
    completed = sum(1 for response in responses if response["outcome"] != "provider_failure")
    planned = len(plan.requests)
    return {"planned_requests": planned, "completed_requests": completed, "completion_rate": completed / planned if planned else 0.0,
            "provider_failures": dict(sorted(failures.items())), "retries": attempts - len(responses), "attempts": attempts,
            "cost_units": cost, "cost_unit": "provider usage units (not USD; D-06, A-15)"}


def build_record(plan: Plan, responses: Sequence[Mapping[str, Any]], *, responder_rule: str, payload_log_sha256: str) -> dict[str, Any]:
    spec = plan.spec
    confirmatory = spec["purpose"] == "confirmatory"
    metrics = compute_metrics(plan, responses)
    digest = requests_digest(plan)
    pins = dict(plan.pins)
    pins["responder"] = {"rule": responder_rule}
    model_ids = sorted({response["model_id"] for response in responses if response.get("model_id")})
    pins["models"] = None if spec["mode"] != "live" else {"model_ids": model_ids, "prices": None}
    governance_block = spec.get("governance") or {}
    return {
        "report": RECORD_FORMAT,
        "format_version": 1,
        "run_id": spec["run_id"],
        "purpose": spec["purpose"],
        "experiment": spec["experiment"],
        "evidence_class": CONFIRMATORY_CLASS if confirmatory else EXPLORATORY_CLASS,
        "synthetic": plan.synthetic,
        "mode": spec["mode"],
        "created_at": spec["created_at"],
        "pins": pins,
        "requests": {"planned": len(plan.requests), "completed": sum(r["outcome"] != "provider_failure" for r in responses), "digest": digest},
        "metrics": metrics,
        "comparisons": compute_comparisons(plan, responses, metrics),
        "bootstrap": compute_bootstrap(plan, responses, metrics),
        "replicate_variance": compute_replicate_variance(plan, responses),
        "slis": compute_slis(plan, responses),
        "governance": {"confirmatory": confirmatory,
                       "irb": "supplied" if governance_block.get("irb_record") else "not supplied",
                       "osf": "supplied" if governance_block.get("osf_record") else "not supplied"},
        "outputs": {"payload_log_sha256": payload_log_sha256, "responses_sha256": canonical_sha256(list(responses))},
    }
