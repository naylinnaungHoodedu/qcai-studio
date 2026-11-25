"""Governance records, the confirmatory gate and the pre-run scan check (spec 3.13, 4.10; AC-10-5; plan Phase 10 D task 6, H, L).

Plan task 6: "No confirmatory run without IRB letter and OSF DOI [Evidence E-108]." A confirmatory run needs a valid IRB
record and a valid OSF record (both in the research plane), the research data plane (D-14), frozen items with a passing
freeze record and a passing pre-run contamination scan bound to the run's items. A live run needs a valid, unexpired IRB
record and the plan H records (provider terms, licence ruling, research-use confirmation), each resolved by path and
sha256 and kept off public paths.

Dates (the run window, spec 3.13): every record date is judged against two days the runner supplies, never against the
spec's own `created_at`. `today` is the current UTC date when the run is planned; `start` is the day the run's data
began to flow: today for a fresh run, else the earliest of today, the `started_on` its checkpoint's start event records
(a resume) and the `started_on` a live recording's header states (a confirmatory recorded replay). The IRB must be
approved on or before `start` and not expired on `today`; the OSF registration and every plan H record must be dated on
or before `start`. A `start` earlier than today can only make these checks stricter, so a hand-written start event or
recording header cannot let a run through that a fresh start today would refuse; `created_at` is an input that may not
be a future date (`created_at_in_future`). The checkpoint, the recording header and the records' own dates are the
operator's: these are consistency checks, not proof or tamper evidence (an externally timestamped start is DI-143). A run
that is not confirmatory skips the confirmatory gate and is labelled exploratory everywhere.

Owner decisions (hold H12, the confirmatory gate's D-14, the live checks of D-07, D-08, D-12 and D-14) are judged only
from a committed package: one whose canonical sha256 is an entry of the append-only package history
(`docs/evaluation/phase7/package_versions.json`) and equals the canonical sha256 of a `vN.json` file in the checkout's
package directory (`committed_package_sha256s`). Any other package a spec pins, such as a hand-made copy with a matching
sidecar, is judged with every decision `uncommitted`, never `decided` (`judged_package`).
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
import datetime as _dt
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Mapping

from .canonical import canonical_sha256, lf_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIRECTORY = REPO_ROOT / "apps" / "api" / "app" / "config_package"
PACKAGE_HISTORY = REPO_ROOT / "docs" / "evaluation" / "phase7" / "package_versions.json"
PACKAGE_FILE = re.compile(r"^v[0-9]+\.json$")
UNCOMMITTED = "uncommitted"

PROVISIONAL_DEFAULTS = ("PD-69",)
PROTOCOL = re.compile(r"^[A-Za-z0-9-]{3,40}$")
DOI = re.compile(r"^10\.17605/OSF\.IO/[A-Z0-9]{5,}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FROZEN_STATES = ("frozen", "release")
SCAN_REPORT = "qcai-research-log-scan"
# The exclusions that leave a scan's coverage incomplete: for any target, and for a research-logs or path target
# (contamination.INCOMPLETE_REASONS, STRICT_TARGETS and STRICT_INCOMPLETE_REASONS; kept equal by a test).
INCOMPLETE_REASONS = frozenset({"too_large", "unreadable"})
STRICT_TARGETS = frozenset({"research-logs", "path"})
STRICT_INCOMPLETE_REASONS = INCOMPLETE_REASONS | {"binary", "not_text"}
# Fingerprint sets whose ids carry these prefixes are the public synthetic fixture's or the scanner's self-test's: they
# prove nothing about the research data, so a pre-run scan made only of them does not pass the gate.
NON_RESEARCH_SET_PREFIXES = ("synthetic-", "self-test-")
# The access log's observer: while a run is planned (`observe_reads`), every record `resolve_record` reads is reported as
# (access-log artifact kind, sha256 of the bytes read), so a refused run still logs the governance records it read.
_READ_OBSERVER: contextvars.ContextVar[Callable[[str, str], None] | None] = contextvars.ContextVar("governance_reads", default=None)


def committed_package_sha256s() -> frozenset[str]:
    """The canonical sha256 of every committed package: an entry of the package history that is also the canonical sha256
    of a `vN.json` file in the package directory. Empty when either cannot be read (every decision then reads open)."""
    try:
        history = json.loads(PACKAGE_HISTORY.read_text(encoding="utf-8"))
        recorded = {entry["sha256"] for entry in history["entries"] if isinstance(entry.get("sha256"), str)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return frozenset()
    found = set()
    for path in sorted(PACKAGE_DIRECTORY.glob("v*.json")):
        if not PACKAGE_FILE.match(path.name):
            continue
        try:
            sha = canonical_sha256(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if sha in recorded:
            found.add(sha)
    return frozenset(found)


def judged_package(package_raw: Mapping[str, Any], committed: bool) -> Mapping[str, Any]:
    """The package as its owner decisions are judged: itself when committed, else a copy whose every decision's state is
    `uncommitted` (so `decided` is never read from a package outside the committed history)."""
    if committed:
        return package_raw
    decisions = {name: {**(entry if isinstance(entry, Mapping) else {}), "state": UNCOMMITTED}
                 for name, entry in (package_raw.get("owner_decisions") or {}).items()}
    for name in ("D-07", "D-08", "D-12", "D-14"):
        decisions.setdefault(name, {"state": UNCOMMITTED})
    return {**package_raw, "owner_decisions": decisions}


@contextmanager
def observe_reads(callback: Callable[[str, str], None] | None) -> Iterator[None]:
    token = _READ_OBSERVER.set(callback)
    try:
        yield
    finally:
        _READ_OBSERVER.reset(token)


class GovernanceError(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def _date(value: Any, field: str, *, nullable: bool = False) -> _dt.date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not DATE.match(value):
        raise GovernanceError(field)
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        raise GovernanceError(field) from None


def _hex(raw: Mapping[str, Any], field: str) -> None:
    if not isinstance(raw[field], str) or not HEX64.match(raw[field]):
        raise GovernanceError(field)


def _load(path: Path, record: str, keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GovernanceError("file") from None
    if not isinstance(raw, dict) or raw.get("record") != record:
        raise GovernanceError("record")
    for key in keys:
        if key not in raw:
            raise GovernanceError(key)
    for key in raw:
        if key not in keys and key != "record":
            raise GovernanceError(key)
    return raw


def load_irb(path: Path) -> dict[str, Any]:
    raw = _load(path, "irb-approval-v1", ("protocol_number", "determination", "approval_date", "expiry_date", "letter_sha256"))
    if not isinstance(raw["protocol_number"], str) or not PROTOCOL.match(raw["protocol_number"]):
        raise GovernanceError("protocol_number")
    if raw["determination"] not in ("approved", "exempt"):
        raise GovernanceError("determination")
    approval = _date(raw["approval_date"], "approval_date")
    expiry = _date(raw["expiry_date"], "expiry_date", nullable=True)
    if expiry is not None and expiry < approval:
        raise GovernanceError("expiry_date")
    _hex(raw, "letter_sha256")
    return raw


def load_osf(path: Path) -> dict[str, Any]:
    raw = _load(path, "osf-registration-v1", ("doi", "registered_date", "analysis_plan_sha256"))
    if not isinstance(raw["doi"], str) or not DOI.match(raw["doi"]):
        raise GovernanceError("doi")
    _date(raw["registered_date"], "registered_date")
    _hex(raw, "analysis_plan_sha256")
    return raw


FREEZE_RECORD_KEYS = ("dataset_sha256", "dataset_content_sha256", "rules_sha256", "agreement_sha256", "agent_check_sha256",
                      "agent_report_sha256", "agent_model_id", "agent_detected_defects", "agent_false_alarms", "agent_missed_defects",
                      "disagreements_adjudicated", "items_changed_after_flag", "items_changed_without_flag", "passed",
                      "failures")


def load_freeze_record(path: Path) -> dict[str, Any]:
    """`ulqs-freeze-record-v1`: the freeze check's outcome, with the canonical sha256 of the agent re-check record
    (`agent_check_sha256`), the agent's full-report sha256 copied from it (`agent_report_sha256`), its model, its counts,
    the items changed after one of its flags and the items changed for another reason."""
    raw = _load(path, "ulqs-freeze-record-v1", FREEZE_RECORD_KEYS)
    if not isinstance(raw["passed"], bool) or not isinstance(raw["failures"], list):
        raise GovernanceError("passed")
    return raw


def load_provider_terms(path: Path) -> dict[str, Any]:
    """`provider-terms-v1` (plan H (b), A-11): the provider's retention, training and publication terms are recorded."""
    raw = _load(path, "provider-terms-v1", ("provider_id", "recorded_date", "retention_recorded", "training_recorded",
                                             "publication_recorded", "terms_sha256"))
    if not isinstance(raw["provider_id"], str) or not PROTOCOL.match(raw["provider_id"]):
        raise GovernanceError("provider_id")
    _date(raw["recorded_date"], "recorded_date")
    for field in ("retention_recorded", "training_recorded", "publication_recorded"):
        if raw[field] is not True:
            raise GovernanceError(field)
    _hex(raw, "terms_sha256")
    return raw


def load_licence_ruling(path: Path) -> dict[str, Any]:
    """`licence-ruling-v1` (plan H (a), Q-07): counsel's determination, `permits` or `negative`."""
    raw = _load(path, "licence-ruling-v1", ("determination", "ruling_date", "letter_sha256"))
    if raw["determination"] not in ("permits", "negative"):
        raise GovernanceError("determination")
    _date(raw["ruling_date"], "ruling_date")
    _hex(raw, "letter_sha256")
    return raw


def load_research_use(path: Path) -> dict[str, Any]:
    """`research-use-confirmation-v1` (plan H (d)): the paper's PENDING research-use confirmation, resolved."""
    raw = _load(path, "research-use-confirmation-v1", ("confirmation", "confirmed_date", "letter_sha256"))
    if raw["confirmation"] != "confirmed":
        raise GovernanceError("confirmation")
    _date(raw["confirmed_date"], "confirmed_date")
    _hex(raw, "letter_sha256")
    return raw


def resolve_record(reference: Any, repo_root: Path, *, kind: str = "governance_record") -> Path:
    """A spec's record reference ({"path", "sha256"}) as a path, after its sha256 (LF-normalised bytes) is checked. A
    file that was read is reported to the read observer under `kind` (an access-log artifact kind), matching or not."""
    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        raise GovernanceError("reference")
    path = Path(reference["path"])
    path = path if path.is_absolute() else Path(repo_root) / path
    try:
        digest = lf_sha256(path)
    except (OSError, ValueError):  # ValueError: a path open() refuses (an embedded NUL)
        raise GovernanceError("file") from None
    observer = _READ_OBSERVER.get()
    if observer is not None:
        observer(kind, digest)
    if digest != reference.get("sha256"):
        raise GovernanceError("sha256")
    return path


def run_date(spec: Mapping[str, Any]) -> _dt.date:
    """The UTC date of the spec's `created_at` (an input: part of the run digest and the record, never a record's run date)."""
    created = str(spec.get("created_at", ""))
    try:
        return _dt.date.fromisoformat(created[:10])
    except ValueError:
        raise GovernanceError("created_at") from None


def utc_today() -> _dt.date:
    """The current UTC date, read once when a run is planned (the tests replace it with a fixed date)."""
    return _dt.datetime.now(_dt.timezone.utc).date()


def created_at_refusals(spec: Mapping[str, Any], today: _dt.date) -> list[str]:
    """`created_at` must be a date (`created_at`) that is not after today (`created_at_in_future`)."""
    try:
        on = run_date(spec)
    except GovernanceError:
        return ["created_at"]
    return [] if on <= today else ["created_at_in_future"]


def iso_day(value: Any) -> _dt.date | None:
    """A `YYYY-MM-DD` string as a date, or None for anything else (a timestamp, a number, an impossible date)."""
    if not isinstance(value, str) or not DATE.match(value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def recording_start_refusals(started_on: Any, today: _dt.date) -> list[str]:
    """A confirmatory recorded run replays a live recording whose header states the day its live run started
    (`started_on`): it must be an ISO date (`recording_started_on_missing`) and not after today (`recording_after_run`).
    The header is written by whoever made the recording and no tool in this repository writes a live one (DI-143); the
    stated day only moves the run window's `start` earlier, which tightens every record check."""
    start = iso_day(started_on)
    if start is None:
        return ["recording_started_on_missing"]
    return [] if start <= today else ["recording_after_run"]


def is_public(reference: Any, repo_root: Path) -> bool:
    """True when a record's path breaks the research-plane path rule (planes): a checkout path that is not a git-ignored
    private-plane path, or a path holding a NUL character (fail closed, on every platform: `open()` raises
    ValueError for it, and `os.path.realpath` too on POSIX). A run whose record is public is refused."""
    from .planes import require_private_input

    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        return False
    path = Path(reference["path"])
    path = path if path.is_absolute() else Path(repo_root) / path
    try:
        require_private_input(Path(os.path.abspath(path)), root=Path(repo_root))
    except ValueError:  # PathRefused, or a path the path calls refuse
        return True
    return False


def irb_refusals(reference: Any, start: _dt.date, repo_root: Path, *, missing: str, today: _dt.date | None = None) -> list[str]:
    """The IRB condition, shared by the confirmatory gate and live runs: present, valid, approved on or before the run
    window's `start` and not expired on `today` (default `start`), so it covers every day the run's data flow."""
    if not reference:
        return [missing]
    try:
        irb = load_irb(resolve_record(reference, repo_root, kind="irb_record"))
    except GovernanceError as error:
        return [f"irb_invalid:{error.field}"]
    reasons = []
    if _dt.date.fromisoformat(irb["approval_date"]) > start:
        reasons.append("irb_not_yet_approved")
    if irb["expiry_date"] is not None and _dt.date.fromisoformat(irb["expiry_date"]) < (today or start):
        reasons.append("irb_expired")
    return reasons


def record_refusals(reference: Any, loader: Callable[[Path], dict[str, Any]], repo_root: Path, *, missing: str,
                    invalid: str) -> tuple[list[str], dict[str, Any] | None]:
    """A plan H record: (reasons, the loaded record or None)."""
    if not reference:
        return [missing], None
    try:
        return [], loader(resolve_record(reference, repo_root))
    except GovernanceError as error:
        return [f"{invalid}:{error.field}"], None


def scan_refusals(reference: Any, repo_root: Path, *, dataset_content_sha256: str, missing: str) -> list[str]:
    """The pre-run contamination scan (plan L "Stop: contamination"; 10.5(3)): a resolved `qcai-research-log-scan` report
    that passed with zero matches, made with a licensed and a ULQS research fingerprint set (never only the synthetic
    fixture's or the self-test's), whose ULQS set was built from this run's items (the status-free content sha256), over
    the tracked repository (tests and public artifacts) and at least one research-logs or path target (logs, prompts),
    with full coverage: every target scanned a file, none excluded a file as too large or unreadable, and no research-logs
    or path target excluded a file as binary or not text (plan 10.5(3): "pre-run scan proving no ULQS text in prompts,
    tests, logs or public artifacts"). A report whose `fingerprint_sets` or `targets` is not a list is invalid
    (`pre_run_scan_invalid:report`), never a traceback."""
    if not reference:
        return [missing]
    try:
        scan = json.loads(resolve_record(reference, repo_root, kind="scan_report").read_text(encoding="utf-8"))
    except GovernanceError as error:
        return [f"pre_run_scan_invalid:{error.field}"]
    except (OSError, ValueError):
        return ["pre_run_scan_invalid:file"]
    if not isinstance(scan, dict) or scan.get("report") != SCAN_REPORT or scan.get("format_version") != 1 \
            or not isinstance(scan.get("fingerprint_sets"), list) or not isinstance(scan.get("targets"), list):
        return ["pre_run_scan_invalid:report"]
    reasons = []
    if scan.get("result") != "pass" or scan.get("matches_total") != 0:
        reasons.append("pre_run_scan_invalid:result")
    sets = [entry for entry in scan["fingerprint_sets"] if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
            and not entry["id"].startswith(NON_RESEARCH_SET_PREFIXES)]
    if not {"licensed", "ulqs"} <= {entry.get("kind") for entry in sets}:
        reasons.append("pre_run_scan_invalid:fingerprint_sets")
    if not any(entry.get("kind") == "ulqs" and entry.get("dataset_content_sha256") == dataset_content_sha256 for entry in sets):
        reasons.append("pre_run_scan_invalid:dataset")
    targets = [target for target in scan["targets"] if isinstance(target, Mapping)]
    scanned = {target.get("target") for target in targets if _count(target.get("scanned")) > 0}
    if "repository" not in scanned or not scanned & {"research-logs", "path"}:
        reasons.append("pre_run_scan_invalid:targets")
    # Coverage: every target scanned a file and excluded none for a reason that leaves its coverage incomplete (the
    # scanner's --require-zero rule), whatever the report's own `result` or `incomplete_targets` say.
    if scan.get("incomplete_targets") or any(_count(target.get("scanned")) == 0 or any(
            not isinstance(entry, Mapping) or entry.get("reason") in _incomplete_reasons(target.get("target"))
            for entry in _list(target.get("excluded"))) for target in targets) or len(targets) != len(scan["targets"]):
        reasons.append("pre_run_scan_invalid:coverage")
    return reasons


def _incomplete_reasons(target_kind: Any) -> frozenset[str]:
    return STRICT_INCOMPLETE_REASONS if target_kind in STRICT_TARGETS else INCOMPLETE_REASONS


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [None]


def confirmatory_refusals(spec: Mapping[str, Any], *, analysis_plan_sha256: str, dataset_sha256: str, dataset_content_sha256: str,
                          items_states: Mapping[str, int], package_raw: Mapping[str, Any], repo_root: Path,
                          recording_source: str | None = None, start: _dt.date | None = None,
                          today: _dt.date | None = None) -> list[str]:
    """The confirmatory gate's reasons, in order (spec 4.10), judged in the run window (`start`, `today`; both default to
    `utc_today()`): `created_at_refusals`, then the IRB (approved by `start`, unexpired on `today`) and the OSF record
    (registered by `start`). The runner adds the window's own reasons (a checkpoint or recording start) before these."""
    today = today or utc_today()
    on = min(start, today) if start else today
    reasons: list[str] = created_at_refusals(spec, today)
    governance = spec.get("governance") or {}
    irb_ref, osf_ref = governance.get("irb_record"), governance.get("osf_record")
    reasons += irb_refusals(irb_ref, on, repo_root, missing="irb_missing", today=today)
    if not osf_ref:
        reasons.append("osf_missing")
    else:
        try:
            osf = load_osf(resolve_record(osf_ref, repo_root, kind="osf_record"))
            if _dt.date.fromisoformat(osf["registered_date"]) > on:
                reasons.append("osf_registered_after_run")
            if osf["analysis_plan_sha256"] != analysis_plan_sha256:
                reasons.append("osf_plan_mismatch")
        except GovernanceError as error:
            reasons.append(f"osf_invalid:{error.field}")
    if any(is_public(reference, repo_root) for reference in (irb_ref, osf_ref) if reference):
        reasons.append("governance_record_public")
    if ((package_raw.get("owner_decisions") or {}).get("D-14") or {}).get("state") != "decided":
        reasons.append("D-14 open")
    if any(state not in FROZEN_STATES and state != "retired" for state, count in items_states.items() if count):
        reasons.append("items_not_frozen")
    freeze_ref = spec.get("freeze_record")
    if not freeze_ref:
        reasons.append("freeze_record_missing")
    else:
        try:
            freeze = load_freeze_record(resolve_record(freeze_ref, repo_root, kind="freeze_record"))
            if freeze["passed"] is not True or freeze["dataset_sha256"] != dataset_sha256:
                reasons.append("freeze_record_failed")
        except GovernanceError:
            reasons.append("freeze_record_failed")
    reasons += scan_refusals(spec.get("pre_run_scan"), repo_root, dataset_content_sha256=dataset_content_sha256,
                             missing="pre_run_scan_missing")
    if spec.get("mode") == "stub":
        reasons.append("stub_not_confirmatory")
    if spec.get("mode") == "recorded" and recording_source != "live":
        reasons.append("recording_not_live")
    return reasons


# The exit code of a refused confirmatory run (spec 5): the first class with a reason present wins.
CONFIRMATORY_EXIT_CLASSES = ((8, ("irb_", "osf_")), (3, ("items_not_frozen", "items_split_missing", "freeze_record_")))


def confirmatory_exit_code(reasons: list[str]) -> int:
    """8 with any IRB or OSF reason; else 3 with any items or freeze-record reason; else 2 (every other reason)."""
    for code, prefixes in CONFIRMATORY_EXIT_CLASSES:
        if any(reason.startswith(prefixes) for reason in reasons):
            return code
    return 2


def record_digest(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(raw)
