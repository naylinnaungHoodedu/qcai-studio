"""The E1-E4 runner: pins, holds, units, requests, checkpointed execution and the run record (spec 3.9-3.12, 4.12-4.13).

Plan task 5: "Pinned configuration package [Evidence E-97]; E1-E4 per Section 15 [Evidence E-99]; statistics with hashed
seeds [Evidence E-103]." The runner implements the four designs: E1, every live item through the seven arms with the
registered E1 family (H1a, H1b, H1c with Holm, `compute_registered_tests`), and E2's verifier panel, E3's two designs and
E4's model grid with its seeded replay streams from the spec's `design` block (`experiments`), each with its registered
family; no model is pinned (D-07), so the designs run on stub or recorded responses only. Every E1-E4 hypothesis the
analysis plan registers must be one the design computes, under its test (`experiments.family_refusals`). A run pins the
package (path and sha256, read-only), the items, the evidence catalog, the arms and the analysis plan by sha256; its
seeds are hashed from (run_id, arm, item_id, replicate), with a design request's role, cell and subject added. Stub and recorded runs repeat
byte for byte: no byte-compared output (the run record and the payload log) carries the wall clock or an absolute path,
and both depend only on the plan and the responses; only a confirmatory or live run's start event in `run_events.jsonl`,
which is not byte-compared, carries the UTC day the run was planned (`started_on`). Owner decisions are read only from a
committed package (`governance.committed_package_sha256s`), so hold H12 refuses every run over non-synthetic data while
no committed package the spec pins decides D-14; live runs are refused here.
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
from dataclasses import dataclass, field, replace
import datetime as _dt
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from . import ablation, analysis_plans, experiments, governance, inputs, planes, statistics, ulqs
from .abstention import abstention_by_turn_depth, correct_abstention
from .canonical import canonical_json, canonical_sha256, dumps_line, dumps_record, hashed_hex, jsonl_lines, lf_sha256, read_jsonl, write_lf
from .citation import citation_existence
from .fabrication import fabrication_rate
from .faithfulness import citation_faithfulness
from .invariance import invariance_violations
from .payload_log import log_record, validate_log_record
from .pointers import EvidenceCatalog, PointerResolver, public_span_lookup, resolve_items
from .providers import RecordedResponder, RecordingInvalid

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
# Every experiment has its design here: E1 (every live item through the seven arms, and the registered E1 family) and the
# E2, E3 and E4 designs of `experiments`.
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
    # A design request (experiments): its role (`answer` for E1 and E4 generations, `verify` for an E2 verification,
    # the E3 designs' passes), its cell (the E2 verifier or the E4 model), its subject (the claim an E2 verification
    # checks) and that claim's gold label.
    role: str = "answer"
    cell: str | None = None
    subject: str | None = None
    claim_label: str | None = None
    # An E3 `two-pass` presentation request depends on its item's `two-pass-evidential` request (`depends_on`, that
    # request's key): `execute_run` sends it only after that response, with its locked claims (`locked`: sorted
    # (claim_id, sorted cited pointers) pairs), and records it as a provider failure (`evidential_pass_failed`) without
    # sending it when the evidential pass failed.
    depends_on: str | None = None
    locked: tuple[tuple[str, tuple[str, ...]], ...] = ()


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
    # A recorded run's responder: the RecordedResponder the planner read, whose bytes matched the pinned sha256 and the run
    # pins and whose every entry passed its check. The run replays this object, never a second read of the path.
    recorded_responder: Any = None


# ------------------------------------------------------------------------------------------------------------ helpers


def _path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(repo_root) / path


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = inputs.read_json(path)
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
    raw = inputs.read_json(path)
    if not isinstance(raw, Mapping) or raw.get("parameters") != "harness-parameters-v1" or raw.get("provisional") is not True:
        raise ValueError("not a provisional harness-parameters-v1 file")
    if _replicate_problems(raw.get("replicates")) or not _integer(raw.get("retries"), 0, MAX_RETRIES):
        raise ValueError("harness parameters: replicates or retries out of range")
    variance = raw.get("replicate_variance_required")
    if not isinstance(variance, Mapping) or not _integer(variance.get("min_replicates"), 2):
        raise ValueError("harness parameters: replicate_variance_required.min_replicates")
    designs = raw.get("designs")
    if (not isinstance(designs, Mapping) or designs.get("provisional") is not True
            or any(not isinstance(designs.get(name), Mapping) for name in experiments.DESIGN_EXPERIMENTS)):
        raise ValueError("harness parameters: a provisional designs block for E2, E3 and E4")
    if not _integer(designs["E4"].get("min_stream_items"), 1):
        raise ValueError("harness parameters: designs.E4.min_stream_items")
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


# The paper's execution protocol (VBT RevB Sec. VIII-C: "Within-model variability is estimated from three replicates on a
# 40-item S1 subsample"; "API failures are retried three times, then logged and counted"): every other item runs once.
# The harness parameters' defaults are these values (PD-68; a test keeps them equal). A registered experiment (E1-E4)
# whose effective values depart from them is refused in a live run or over non-synthetic data
# (`design_departs_from_registration:<field>`, exit 2); a synthetic E1-E4 run may depart, and its record names each
# departure (`pins.execution.departures`) and files its family as `departs_from_registration`. A harness-check run
# files no registered family (it is never confirmatory) and its record pins the effective values it ran.
REGISTERED_EXECUTION = {"replicates.default": 1, "replicates.subsample.stratum": "A", "replicates.subsample.size": 40,
                        "replicates.subsample.replicates": 3, "retries": 3}


def execution_applies(spec: Mapping[str, Any]) -> bool:
    """Whether the registered execution protocol binds the run: an E1-E4 experiment (each files a registered family)."""
    return spec["experiment"] in analysis_plans.FAMILIES


def execution_departures(experiment: str, replicates: Mapping[str, Any], retries: int) -> list[dict[str, Any]]:
    """Each effective execution value that differs from `REGISTERED_EXECUTION`, as {field, registered, effective}. E3
    sends each request once, except its single-pass repeats (its replicate variance, `_design_requests`), so only its
    retries are judged; every other experiment is judged on its default replicates, its subsample and its retries."""
    block = replicates.get("subsample") or {}
    effective: dict[str, Any] = {"retries": retries}
    if experiment != "E3":
        effective = {"replicates.default": replicates.get("default"),
                     **{f"replicates.subsample.{key}": block.get(key) for key in ("stratum", "size", "replicates")}, **effective}
    return [{"field": field, "registered": REGISTERED_EXECUTION[field], "effective": value}
            for field, value in effective.items() if value != REGISTERED_EXECUTION[field]]


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
    # Human claim labels reach a run only inside its responses (a labelled recording replayed as a recorded run; the
    # research-plane runbook): the spec's `labels` is null, and any other value is refused, never accepted unread.
    if spec.get("labels") is not None:
        reasons.append("labels")
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
    if spec["experiment"] in experiments.DESIGN_EXPERIMENTS:
        shape = experiments.shape_refusals(spec["experiment"], spec.get("design"))
        if shape:
            raise RunRefused(2, shape)  # the design block, every nested value the planner reads (the field named)
    if spec["experiment"] in analysis_plans.FAMILIES and spec["analysis_plan"].get("family") != spec["experiment"]:
        raise RunRefused(2, ["analysis_plan_family_mismatch"])  # each experiment runs under its own analysis-plan family
    if spec["experiment"] == "E1":
        # E1 runs every live item through all seven arms (paper Sec. VIII E1).
        if spec["arms"].get("selected") is not None and sorted(spec["arms"]["selected"]) != sorted(ablation.ARM_IDS):
            raise RunRefused(2, ["experiment_requires_seven_arms"])
    # AC-10-3: live runs report replicate variance; confirmatory runs too (PD-68). Both need a subsample with at least
    # `min_replicates` replicates, except E3, whose replicate variance is its single-pass repeats at the fixed level
    # (VBT RevB Sec. VIII-D) and which uses no subsample.
    if (spec["mode"] == "live" or spec["purpose"] == "confirmatory") and spec["experiment"] != "E3":
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


def package_problem(package_raw: Any) -> str | None:
    """The first field of a package the harness reads that is not shaped as it reads it, or None: the package is an object,
    `owner_decisions` is absent, null or an object of objects (each decision's `state` is read), `semantic` is absent,
    null or an object (its `enabled_by_default` is read by the live checks), and `ranking` is absent, null or an object
    shaped as E4's replay reads it (`experiments.ranking_problem`, which names the field as `ranking.<field>`)."""
    if not isinstance(package_raw, Mapping):
        return "package"
    decisions = package_raw.get("owner_decisions")
    if decisions is not None and (not isinstance(decisions, Mapping) or not all(isinstance(entry, Mapping) for entry in decisions.values())):
        return "owner_decisions"
    if package_raw.get("semantic") is not None and not isinstance(package_raw["semantic"], Mapping):
        return "semantic"
    return experiments.ranking_problem(package_raw.get("ranking"))


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
        package_raw = inputs.read_json(package_path)
    except (OSError, ValueError):
        raise RunRefused(6, ["package_unreadable"]) from None
    package_sha = canonical_sha256(package_raw)
    if package_sha != spec["package"].get("sha256") or _sidecar(package_path) != package_sha:
        raise RunRefused(6, ["package_sha256"])
    if package_problem(package_raw) is not None:
        raise RunRefused(6, [f"package_invalid:{package_problem(package_raw)}"])
    # Owner decisions are judged only from a committed package (governance module docstring): a hand-made copy with a
    # matching sidecar reads every decision `uncommitted`, so it releases no hold.
    committed = package_sha in governance.committed_package_sha256s()
    judged = governance.judged_package(package_raw, committed)
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
        arms_raw = inputs.read_json(_path(spec["arms"]["path"], repo_root))
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
        plans_raw = inputs.read_json(_path(spec["analysis_plan"]["path"], repo_root))
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
    design = None
    synthetic = planes.all_synthetic(items) and (catalog is None or all(r.volume == "synthetic" for r in catalog.records.values()))
    # The registered execution protocol (`REGISTERED_EXECUTION`): an E1-E4 run that is live or over non-synthetic data
    # keeps the paper's replicates and retries; a synthetic E1-E4 run may depart, and its record names each departure. A
    # design's own departures (`experiments.departures`) are listed before these.
    execution = execution_departures(spec["experiment"], replicates, retries) if execution_applies(spec) else None
    refuse_departures = spec["mode"] == "live" or not synthetic
    execution_fields = [f"design_departs_from_registration:{entry['field']}" for entry in execution or []]
    if spec["experiment"] in analysis_plans.FAMILIES:
        # Every hypothesis of the experiment's family must be one its design computes, under that test (E1: comparing
        # two of the selected arms), so a valid plans file that registers another test refuses the run before it
        # starts, never after it completed.
        refusals = experiments.family_refusals(spec["experiment"], plans_raw["families"][spec["experiment"]], selected)
        if refusals:
            raise RunRefused(2, refusals)
    if spec["experiment"] in experiments.DESIGN_EXPERIMENTS:
        needed = {"E3": {experiments.effective_design("E3", spec["design"], parameters_raw)["arm"]}, "E4": {"GATE", "VLOOP"}}.get(
            spec["experiment"], set())
        if not needed <= set(selected):
            raise RunRefused(2, ["experiment_requires_arms"])
        try:
            design = experiments.load_design(spec["experiment"], spec, items, parameters_raw, repo_root, note)
        except experiments.DesignRefused as refused:
            raise RunRefused(refused.code, refused.reasons) from None
        # E4's replay reads the package's ranking block only after every request was sent: a dry run of its controller
        # policies on that block (`experiments.ranking_replay_problem`) refuses a block the ranking arithmetic refuses now.
        if spec["experiment"] == "E4":
            problem = experiments.ranking_replay_problem(package_raw.get("ranking"), design["design"]["models"])
            if problem is not None:
                raise RunRefused(6, [f"package_invalid:{problem}"])
        # The registered protocol (`experiments.departures`): a live run or a run over non-synthetic data runs it as
        # registered; a synthetic run may depart, and its record names each departure and never files the family as the
        # registered result.
        design["departures"] = experiments.departures(spec["experiment"], design["design"], plans_raw["families"][spec["experiment"]])
        if (design["departures"] or execution_fields) and refuse_departures:
            fields = [f"design_departs_from_registration:{entry['field']}" for entry in design["departures"]] + execution_fields
            raise RunRefused(2, list(dict.fromkeys(fields)))
        # E4's commissioning hold-out costs the streams its items: a live run or a run over research data must keep the
        # streams' floor (`experiments.stream_floor_refusals`); a synthetic replay below it is flagged in its record.
        if spec["experiment"] == "E4" and (spec["mode"] == "live" or not synthetic):
            floor = experiments.stream_floor_refusals(design["design"], items)
            if floor:
                raise RunRefused(2, floor)
    if design is None and execution_fields and refuse_departures:
        raise RunRefused(2, execution_fields)
    # 7. Hold H12: no run over non-synthetic data while the research data plane (D-14) is not decided in a committed package.
    if not synthetic:
        if not _decided(judged, "D-14"):
            raise RunRefused(9, ["hold_h12_data_plane"])
        missing = []
        if access_log is None:
            missing.append("access_log_required")
        missing += governance.scan_refusals(spec.get("pre_run_scan"), repo_root, dataset_content_sha256=items_content_sha,
                                            corpus_version=next(iter(corpus_versions)) if len(corpus_versions) == 1 else None,
                                            missing="pre_run_scan_required")
        if missing:
            raise RunRefused(2, missing)
    # The recorded responder and its pins.
    recording_source = recording_started_on = None
    responder = None
    dated = spec["mode"] == "live" or spec["purpose"] == "confirmatory"
    if spec["mode"] == "recorded":
        recorded = (spec.get("responder") or {}).get("recorded") or {}
        recording_path = _path(recorded["path"], repo_root) if "path" in recorded else None
        recording_sha = None if recording_path is None else _file_sha256(recording_path)
        note("recording", recording_sha)
        invalid = False
        try:
            if recording_path is None:
                raise KeyError("path")
            responder = RecordedResponder(recording_path)
        except RecordingInvalid:
            invalid = True  # refused after the sha256 check: a file that is not the pinned one is a pin mismatch first
        except (KeyError, OSError, ValueError):
            raise RunRefused(6, ["recording_unreadable"]) from None
        if recording_sha != recorded.get("sha256"):
            raise RunRefused(6, ["recording_sha256"])
        if invalid:
            raise RunRefused(3, ["recording_invalid"])
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
    # E4 prices at "the list prices in force on the run date" (VBT RevB Sec. VIII-D): a model's base list price must be in
    # force at the run's start, so a later list price must take effect after it.
    if design is not None and spec["experiment"] == "E4" and any(
            entry.get("later_price") and governance.iso_day(entry["later_price"]["from"]) <= start for entry in design["design"]["models"]):
        raise RunRefused(2, ["e4_later_price_in_force"])
    # 8. The confirmatory gate (AC-10-5).
    if spec["purpose"] == "confirmatory":
        reasons = window + governance.confirmatory_refusals(
            spec, analysis_plan_sha256=plans_sha, dataset_sha256=items_sha, dataset_content_sha256=items_content_sha,
            corpus_version=next(iter(corpus_versions)) if len(corpus_versions) == 1 else None,
            items_states=states, package_raw=judged, repo_root=repo_root, recording_source=recording_source, start=start,
            today=today)
        # Plan 10.5(2) "calibration and confirmation items split [Risk R-25]": every live item of a confirmatory run
        # carries its split, so that a threshold fitted on ULQS uses the calibration split only (plan L470). The run itself
        # covers every live item (`_requests`).
        if any(item.get("split") not in ulqs.SPLITS for item in items if item.get("status") != "retired"):
            reasons.append("items_split_missing")
        # The replicate subsample (PD-68, the paper's "three replicates on a 40-item S1 subsample") must be met in full:
        # a confirmatory run whose subsample stratum holds fewer live items than its size is refused, never replicated
        # over fewer items than its record pins. E3 uses no subsample (`_check_shape`).
        if spec["experiment"] != "E3" and len(subsample(items, replicates)) < int((replicates.get("subsample") or {}).get("size", 0)):
            reasons.append("replicate_subsample_short")
        if reasons:
            raise RunRefused(governance.confirmatory_exit_code(reasons), reasons)
    # 9. Live runs.
    if spec["mode"] == "live":
        from .providers import live_refusal_reasons

        reasons = live_refusal_reasons(spec, judged, environ, table, out_dir=out_dir, repo_root=repo_root, start=start,
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
                planes.require_private_output(out_dir, root=repo_root, boundary=planes.boundary_policy(package_path))
            except planes.PathRefused:
                raise RunRefused(2, ["output_not_private"]) from None
    if design is None:
        requests = _requests(spec, items, table, selected, package_sha, prompt_version, replicates)
    else:
        requests = _design_requests(spec, items, table, package_sha, prompt_version, replicates, design, resolver)
    pins = {
        "package": {"path": spec["package"]["path"] if not Path(spec["package"]["path"]).is_absolute() else package_path.name,
                    "sha256": package_sha, "package_version": package_raw.get("package_version"), "committed": committed,
                    "owner_decisions": {name: ((judged.get("owner_decisions") or {}).get(name) or {}).get("state")
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
            [key for key in ("replicates", "retries") if key not in spec]
            + (["designs"] if design is not None and experiments.defaults_taken(spec["experiment"], spec["design"]) else []))},
        "code": code_pins(repo_root),
    }
    if execution is not None:
        pins["execution"] = {"registered": dict(REGISTERED_EXECUTION), "departures": execution}
    if design is not None:
        pins["design"] = experiments.design_pins(spec["experiment"], design)
    return Plan(spec=dict(spec), package_raw=judged, items=items, arms=table, requests=tuple(requests), pins=pins,
                resolver=resolver, synthetic=synthetic, recording_source=recording_source, dated=dated,
                planned_on=today if dated else None, checkpoint_start=checkpoint_start, extra={"analysis_plans": plans_raw, "design": design},
                recorded_responder=responder)


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


def _design_requests(spec, items, table, package_sha, prompt_version, replicates, loaded, resolver) -> list[Request]:
    """The requests of an E2, E3 or E4 design (`experiments`). E2: one `verify` request per claim and verifier outside the
    claim's family, the claims of the subsample's items replicated; E3: the live G items only, each request at replicate
    1 except the single-pass repeats at the fixed level (its replicate variance; the subsample is not used), and each
    `two-pass` request depending on its item's `two-pass-evidential` request (`depends_on`: it is sent with that
    response's locked claims, `locked`); E4: every live unit for each model in GATE and VLOOP, the subsample's items
    replicated, as in E1."""
    experiment = spec["experiment"]
    design = loaded["design"]
    run_id = spec["run_id"]
    default = int(replicates.get("default", 1))
    sampled = set(subsample(items, replicates))
    extra = int((replicates.get("subsample") or {}).get("replicates", default))
    live = sorted((item for item in items if item.get("status") != "retired"), key=lambda item: item["item_id"])
    requests: list[Request] = []

    def add(*, arm, item_id, unit, turn_depth, replicate, evidence, gold, gold_claims, role, cell, subject=None, claim_label=None,
            depends_on=None) -> str:
        configuration = ablation.arm_configuration(table, arm)
        key = experiments.design_request_key(role=role, arm_config_sha256=canonical_sha256(configuration), item_id=item_id, unit=unit,
                                             replicate=replicate, package_sha256=package_sha, prompt_version=prompt_version,
                                             evidence=evidence, cell=cell, subject=subject)
        requests.append(Request(request_key=key, arm=arm, item_id=item_id, unit=unit, turn_depth=turn_depth, replicate=replicate,
                                seed_hex=experiments.design_seed(run_id, arm, item_id, replicate, role, cell, subject or unit),
                                evidence=tuple(sorted(evidence)), gold=gold, gold_claims=tuple(gold_claims), role=role, cell=cell,
                                subject=subject, claim_label=claim_label, depends_on=depends_on))
        return key

    if experiment == "E2":
        for claim in loaded["claims"]:
            count = max(default, extra) if claim.item_id in sampled else default
            evidence = tuple(pointer for pointer in claim.cited if resolver.resolve(pointer).status == "resolved")
            arm = claim.arm if claim.arm in ablation.ARM_IDS else "GATE"
            for verifier in design["verifiers"]:
                if verifier["family"] == claim.family:
                    continue  # each model verifies every claim generated outside its own provider family
                for replicate in range(1, count + 1):
                    add(arm=arm, item_id=claim.item_id, unit=claim.unit, turn_depth=None, replicate=replicate, evidence=evidence,
                        gold="answer", gold_claims=(claim.claim_id,), role="verify", cell=verifier["model_id"], subject=claim.key,
                        claim_label=claim.label)
    elif experiment == "E3":
        arm = design["arm"]
        for item in (item for item in live if item.get("stratum") == "G"):
            units = {unit["unit"]: unit for unit in _units(item)}
            first = units[ulqs.REPLAY_LEVELS[0]]
            evidence = () if ablation.arm_configuration(table, arm)["retrieval"] == "none" else tuple(sorted(first["evidence"]))
            common = {"arm": arm, "item_id": item["item_id"], "turn_depth": None, "evidence": evidence, "gold": "answer",
                      "gold_claims": first["gold_claims"], "cell": None}
            evidential = add(unit=None, replicate=1, role="two-pass-evidential", **common)
            for level in ulqs.REPLAY_LEVELS:
                add(unit=level, replicate=1, role="two-pass", depends_on=evidential, **common)
            for level in ulqs.REPLAY_LEVELS:
                for replicate in range(1, (int(design["repeats"]) if level == design["fixed_level"] else 1) + 1):
                    add(unit=level, replicate=replicate, role="single-pass", **common)
    else:  # E4: all four models answer every unit in GATE and VLOOP
        for model in design["models"]:
            for arm in ("GATE", "VLOOP"):
                configuration = ablation.arm_configuration(table, arm)
                for item in live:
                    count = max(default, extra) if item["item_id"] in sampled else default
                    for unit in _units(item):
                        evidence = () if configuration["retrieval"] == "none" else tuple(sorted(unit["evidence"]))
                        for replicate in range(1, count + 1):
                            add(arm=arm, item_id=item["item_id"], unit=unit["unit"], turn_depth=unit["turn_depth"], replicate=replicate,
                                evidence=evidence, gold=unit["gold"], gold_claims=unit["gold_claims"], role="answer",
                                cell=model["model_id"])
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


CHECKPOINT_REASON = re.compile(r"^[a-z][a-z_]{0,63}$")
CHECKPOINT_FIELDS = ("attempts", "outcome", "failure_reason", "claims", "text", "usage", "model_id")


def checkpoint_line_problem(line: Mapping[str, Any]) -> str | None:
    """The first field of a checkpoint line that is not a response record as `_response_line` writes it, or None: `attempts`
    a list of {status} (a lowercase reason), every field `_response_line` writes present, `outcome` answered, abstained or
    provider_failure (with a lowercase `failure_reason`; else `failure_reason` null), `usage` an object, and the response
    fields as `providers.response_problem` checks a recorded response (claims, cited pointers, text, usage, model id,
    verdict, features, signals, latency), so that a line the metrics or the payload log could not read refuses the run
    before any request is sent."""
    from .providers import response_problem

    attempts = line.get("attempts")
    if not isinstance(attempts, list) or not all(
            isinstance(attempt, Mapping) and set(attempt) == {"status"} and isinstance(attempt["status"], str)
            and CHECKPOINT_REASON.match(attempt["status"]) for attempt in attempts):
        return "attempts"
    for name in CHECKPOINT_FIELDS:
        if name not in line:
            return name
    if line["outcome"] == "provider_failure":
        if not isinstance(line["failure_reason"], str) or not CHECKPOINT_REASON.match(line["failure_reason"]):
            return "failure_reason"
        response = {**line, "outcome": "abstained"}  # the rest of a failure line is checked as a response's fields
    else:
        if line["failure_reason"] is not None:
            return "failure_reason"
        response = line
    if not isinstance(line["usage"], Mapping):
        return "usage"
    return response_problem(response)


def _read_checkpoint(path: Path, *, resume: bool) -> dict[str, dict]:
    """The completed responses of a checkpoint. Only the bytes after the last newline (a line an interrupted append left
    without its newline) are a partial line: `resume` truncates them and a run without it is refused
    (`partial_checkpoint`). Every newline-terminated line must be a response record (a JSON object with a 64-hex
    `request_key` whose fields pass `checkpoint_line_problem`), else the checkpoint is refused (`checkpoint_invalid`,
    exit 2) before any request is sent and nothing is deleted: a corrupt line never costs the lines after it. A file
    that cannot be read is `checkpoint_invalid` too; a path that is a directory is `output_unwritable` (`_require_file`)."""
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
            record = inputs.loads(line)
        except ValueError:  # UnicodeDecodeError included
            raise RunRefused(2, ["checkpoint_invalid"]) from None
        if (not isinstance(record, dict) or not isinstance(record.get("request_key"), str) or not HEX64.match(record["request_key"])
                or checkpoint_line_problem(record) is not None):
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
    for line in jsonl_lines(text):
        try:
            event = inputs.loads(line)
        except ValueError:
            raise RunRefused(2, ["checkpoint_mismatch"]) from None
        if not isinstance(event, dict):
            raise RunRefused(2, ["checkpoint_mismatch"])
        events.append(event)
    return events


def verify_responses(plan: Plan, responses: Mapping[str, Mapping[str, Any]]) -> None:
    """Every response line belongs to a planned request and carries that request's arm, item, unit, replicate and seed (and,
    for a design request, its role and cell)."""
    planned = {request.request_key: request for request in plan.requests}
    for key, line in responses.items():
        request = planned.get(key)
        if request is None or any(line.get(name) != getattr(request, name) for name in ("arm", "item_id", "unit", "replicate", "seed_hex")) \
                or line.get("role", "answer") != request.role or line.get("cell") != request.cell:
            raise RunRefused(2, ["checkpoint_mismatch"])


def _prompt_envelope(plan: Plan, request: Request) -> bytes:
    envelope = {"prompt_version": plan.pins["prompt_version"], "item_id": request.item_id, "unit": request.unit, "arm": request.arm,
                "evidence": list(request.evidence)}
    if request.role != "answer" or request.cell is not None:
        envelope.update(role=request.role, cell=request.cell, subject=request.subject)
    if request.depends_on is not None:  # a two-pass presentation request carries its item's locked claims
        envelope["locked"] = [[claim_id, list(cited)] for claim_id, cited in request.locked]
    return canonical_json(envelope)


def locked_claims(response: Mapping[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """An evidential response's locked claims: its (claim_id, sorted cited pointers) pairs, sorted (a claim without a
    string id, and a pointer that is not a string, are left out)."""
    pairs = set()
    for claim in response.get("claims") or []:
        if isinstance(claim, Mapping) and isinstance(claim.get("claim_id"), str):
            cited = claim.get("cited") if isinstance(claim.get("cited"), list) else []
            pairs.add((claim["claim_id"], tuple(sorted({pointer for pointer in cited if isinstance(pointer, str)}))))
    return tuple(sorted(pairs))


def with_dependency(request: Request, responses: Mapping[str, Mapping[str, Any]]) -> Request | None:
    """`request` as it is sent: unchanged without `depends_on`; with it, carrying the locked claims of the response it
    depends on, or None when that response failed or is missing (the request is then not sent)."""
    if request.depends_on is None:
        return request
    source = responses.get(request.depends_on)
    if source is None or source.get("outcome") not in ("answered", "abstained"):
        return None
    return replace(request, locked=locked_claims(source))


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
    # The run events are read once here; every check below uses this read.
    events = _read_events(out_dir / RUN_EVENTS)
    if plan.dated:
        # The output must be the checkpoint the plan's run window was judged on: a resume planned from a start event
        # continues that event's run, and a plan judged as a fresh start writes into an output without run events.
        resumed = events if resume else []
        recorded = governance.iso_day(resumed[0].get("started_on")) if resumed else None
        if recorded != plan.checkpoint_start or (resumed and recorded is None):
            raise RunRefused(2, ["checkpoint_mismatch"])
    with _writing():
        out_dir.mkdir(parents=True, exist_ok=True)
    responses_path = out_dir / RESPONSES
    responder_rule = getattr(responder, "rule", "unknown")
    digest = run_digest(plan, responder_rule)
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
            sent = with_dependency(request, completed)
            for _attempt in range(1 + retries if sent is not None else 0):  # never sent when its evidential pass failed
                try:
                    response = responder.respond(sent)
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
            if sent is None:
                line["failure_reason"] = "evidential_pass_failed"
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
        sent = with_dependency(request, completed) or request
        record = log_record(request, response, run_id=spec["run_id"], purpose=spec["purpose"], prompt_version=plan.pins["prompt_version"],
                            prompt_bytes=_prompt_envelope(plan, sent), resolver=plan.resolver)
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


# A design response's own fields (an E2 verdict, E3 presentation features, delivered-quality signals), kept when present.
DESIGN_RESPONSE_KEYS = ("verdict", "features", "signals", "latency")


def _response_line(request: Request, response: Mapping[str, Any] | None, attempts: list[dict[str, str]]) -> dict[str, Any]:
    base = {"request_key": request.request_key, "arm": request.arm, "item_id": request.item_id, "unit": request.unit,
            "replicate": request.replicate, "seed_hex": request.seed_hex, "attempts": attempts}
    if request.role != "answer" or request.cell is not None:
        base.update(role=request.role, cell=request.cell)
    if response is None:
        return {**base, "outcome": "provider_failure", "failure_reason": attempts[-1]["status"] if attempts else "server_error",
                "claims": [], "text": None, "usage": {"input_units": 0, "output_units": 0}, "model_id": None}
    line = {**base, "outcome": response["outcome"], "failure_reason": None, "claims": list(response.get("claims", [])),
            "text": response.get("text"), "usage": dict(response.get("usage") or {"input_units": 0, "output_units": 0}),
            "model_id": response.get("model_id")}
    line.update({key: response[key] for key in DESIGN_RESPONSE_KEYS if key in response})
    return line


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


def _item_answer_rates(plan: Plan, responses, arm: str) -> dict[str, float]:
    """Per item, the share of its answerable units (gold `answer`) the arm answered (eq. 17), replicate 1, provider failures
    excluded."""
    units: dict[str, list[int]] = {}
    for request, response in _pairs(plan, responses):
        if (request.arm == arm and request.replicate == 1 and request.gold == "answer"
                and response["outcome"] != "provider_failure"):
            units.setdefault(request.item_id, []).append(int(response["outcome"] == "answered"))
    return {item: sum(values) / len(values) for item, values in units.items()}


def compute_registered_tests(plan: Plan, responses, metrics) -> dict[str, Any] | None:
    """The registered E1 family (analysis plan family E1; plan 12.7, Holm per family): H1a and H1b exact McNemar paired by
    item on answerable items (VBT RevB Table I: an item's error is 1 when a response to one of its answerable units holds a
    Fabricated or Attribution-error claim, an abstention scoring as no error; `experiments.answerable_item_errors`), H1c
    the one-sided paired bootstrap of the item answer rate (eq. 17) against its margin, then Holm over the family's
    p-values. None unless the experiment is E1; the planner has checked that the family registers only these tests
    (`experiments.family_refusals`). The record carries the computation only; outcomes are reported by the PI, never
    asserted by the harness (invariant 9)."""
    if plan.spec.get("experiment") != "E1":
        return None
    family = plan.extra["analysis_plans"]["families"]["E1"]
    arms = {arm for hypothesis in family["hypotheses"] for arm in hypothesis.get("comparison", [])}
    if any(isinstance(metrics.get(arm), dict) and metrics[arm].get("status") == "awaiting_labels" for arm in arms):
        return {"status": "awaiting_labels"}
    settings = plan.spec.get("bootstrap") or {}
    results: dict[str, Any] = {}
    for hypothesis in family["hypotheses"]:
        left_arm, right_arm = hypothesis["comparison"]
        if hypothesis["test"] == "mcnemar_exact":
            pairs = _pairs(plan, responses)
            result = experiments.paired_by_item(experiments.answerable_item_errors(pairs, lambda request: request.arm == left_arm),
                                                experiments.answerable_item_errors(pairs, lambda request: request.arm == right_arm))
        else:  # paired_bootstrap_one_sided (experiments.family_refusals admits no other E1 test)
            left, right = _item_answer_rates(plan, responses, left_arm), _item_answer_rates(plan, responses, right_arm)
            items = sorted(set(left) & set(right))
            if not items:
                results[hypothesis["id"]] = {"status": "no_paired_items"}
                continue
            result = statistics.paired_bootstrap_one_sided(
                [left[item] for item in items], [right[item] for item in items], resamples=int(settings.get("resamples", 1000)),
                seed=hashed_hex(plan.spec["run_id"], "registered", hypothesis["id"]), margin=hypothesis["margin"])
        results[hypothesis["id"]] = {"endpoint": hypothesis["endpoint"], "comparison": [left_arm, right_arm],
                                     "test": hypothesis["test"], **result}
    tested = {name: value["p_value"] for name, value in results.items() if "p_value" in value}
    found = list((plan.pins.get("execution") or {}).get("departures") or [])
    return {"family": "E1", "correction": "holm", "hypotheses": results, "holm": statistics.holm(tested) if tested else {},
            "protocol": "departs_from_registration" if found else "registered", "departures": found,
            "note": "the registered E1 family; HR-3 is reported without a family test (criteria_only)"}


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
            "provider_failures": dict(sorted(failures.items())),
            "retries": sum(max(0, len(response.get("attempts", [])) - 1) for response in responses), "attempts": attempts,
            "cost_units": cost, "cost_unit": "provider usage units (not USD; D-06, A-15)"}


def build_record(plan: Plan, responses: Sequence[Mapping[str, Any]], *, responder_rule: str, payload_log_sha256: str) -> dict[str, Any]:
    spec = plan.spec
    confirmatory = spec["purpose"] == "confirmatory"
    if plan.extra.get("design") is not None:
        # E2, E3 or E4: the design's metrics, its registered family and its replicate variance (`experiments.compute`); the
        # E1 arm comparisons and the VLOOP - GATE bootstrap belong to E1's design only.
        metrics, registered, variance = experiments.compute(plan, responses)
        comparisons = bootstrap = None
    else:
        metrics = compute_metrics(plan, responses)
        comparisons, registered = compute_comparisons(plan, responses, metrics), compute_registered_tests(plan, responses, metrics)
        bootstrap, variance = compute_bootstrap(plan, responses, metrics), compute_replicate_variance(plan, responses)
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
        "comparisons": comparisons,
        "registered_tests": registered,
        "bootstrap": bootstrap,
        "replicate_variance": variance,
        "slis": compute_slis(plan, responses),
        "governance": {"confirmatory": confirmatory,
                       "irb": "supplied" if governance_block.get("irb_record") else "not supplied",
                       "osf": "supplied" if governance_block.get("osf_record") else "not supplied"},
        "outputs": {"payload_log_sha256": payload_log_sha256, "responses_sha256": canonical_sha256(list(responses))},
    }
