"""Governance records, the confirmatory gate and the pre-run scan check (spec 3.13, 4.10; AC-10-5; plan Phase 10 D task 6, H, L).

Plan task 6: "No confirmatory run without IRB letter and OSF DOI [Evidence E-108]." A confirmatory run needs a valid IRB
record and a valid OSF record (both in the research plane), the research data plane (D-14), frozen items with a passing
freeze record and a passing pre-run contamination scan bound to the run's items. A live run needs a valid, unexpired IRB
record and the plan H records (provider terms, licence ruling, research-use confirmation), each resolved by path and
sha256 and kept off public paths. Every record date is judged against the run date, the date of the spec's
`created_at`. A confirmatory or live run, the replay of a recording included, that is planned as a new run is refused
unless that date is the current UTC date (`created_at_not_today`; `run_date_refusals`). A resume (`--resume`) is not
compared with today when it is planned: the runner judges it against the output's checkpoint (`runner.start_date_refusals`:
with no run events it is a fresh start and must be dated today; with events `created_at` may not be in the future and
must be the date the run's start event was written, and the event must carry this run's digest), and its IRB must also
be valid today. The checkpoint is the operator's own file and the records' dates are self-declared: these checks are
consistency checks, not proof or tamper evidence (an externally timestamped start is DI-143). A run that is not
confirmatory skips the confirmatory gate and is labelled exploratory everywhere.
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
    created = str(spec.get("created_at", ""))
    try:
        return _dt.date.fromisoformat(created[:10])
    except ValueError:
        raise GovernanceError("created_at") from None


def utc_today() -> _dt.date:
    """The current UTC date, read when a run is planned (the tests replace it with a fixed date)."""
    return _dt.datetime.now(_dt.timezone.utc).date()


def run_date_refusals(spec: Mapping[str, Any]) -> list[str]:
    """A confirmatory or live run that starts now, a recorded replay included, is run on the day its spec declares: the
    date of `created_at` must be the current UTC date, so the IRB and every record date are judged against the day the run
    really starts. A resume is judged by the runner against the output's checkpoint instead (`runner.start_date_refusals`,
    which applies this rule when the output holds no run events)."""
    try:
        on = run_date(spec)
    except GovernanceError:
        return ["created_at"]
    return [] if on == utc_today() else ["created_at_not_today"]


def recording_start_refusals(spec: Mapping[str, Any], started_on: Any) -> list[str]:
    """A confirmatory recorded run replays a live recording whose header states the day its live run started
    (`started_on`, an ISO date; the recording is pinned by its sha256): that date must be stated
    (`recording_started_on_missing`) and may not be after the replay's run date (`recording_after_run`). The header is
    written by whoever made the recording and no tool in this repository writes a live one (DI-143), so the replay is
    dated by its own `created_at`, which must be today like every confirmatory run (`run_date_refusals`): the IRB and
    the records are judged against the day of the replay, never against the self-declared `started_on`."""
    try:
        start = _dt.date.fromisoformat(started_on) if isinstance(started_on, str) and len(started_on) == 10 else None
    except ValueError:
        start = None
    if start is None:
        return ["recording_started_on_missing"]
    try:
        on = run_date(spec)
    except GovernanceError:
        return ["created_at"]
    return [] if start <= on else ["recording_after_run"]


def is_public(reference: Any, repo_root: Path) -> bool:
    from .planes import PathRefused, require_private_input

    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        return False
    path = Path(reference["path"])
    path = path if path.is_absolute() else Path(repo_root) / path
    try:
        require_private_input(Path(os.path.abspath(path)), root=Path(repo_root))
    except PathRefused:
        return True
    return False


def irb_refusals(reference: Any, on: _dt.date, repo_root: Path, *, missing: str) -> list[str]:
    """The IRB condition, shared by the confirmatory gate and live runs: present, valid, approved on or before the run
    date and not expired on it."""
    if not reference:
        return [missing]
    try:
        irb = load_irb(resolve_record(reference, repo_root, kind="irb_record"))
    except GovernanceError as error:
        return [f"irb_invalid:{error.field}"]
    reasons = []
    if _dt.date.fromisoformat(irb["approval_date"]) > on:
        reasons.append("irb_not_yet_approved")
    if irb["expiry_date"] is not None and _dt.date.fromisoformat(irb["expiry_date"]) < on:
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
                          recording_source: str | None = None, recording_started_on: Any = None,
                          resuming: bool = False) -> list[str]:
    """The confirmatory gate's reasons, in order (spec 4.10). The run date: every run, a recorded replay included, must be
    dated today (`run_date_refusals`), except a resume (`resuming`), which the runner judges against the output's
    checkpoint (`runner.start_date_refusals`) and whose IRB must also be valid today, since the resumed run continues
    today. A recorded run's live recording must state its start, on or before the run date (`recording_start_refusals`)."""
    on = run_date(spec)
    reasons: list[str] = [] if resuming else run_date_refusals(spec)
    if spec.get("mode") == "recorded" and recording_source == "live":
        reasons += recording_start_refusals(spec, recording_started_on)
    governance = spec.get("governance") or {}
    irb_ref, osf_ref = governance.get("irb_record"), governance.get("osf_record")
    reasons += irb_refusals(irb_ref, on, repo_root, missing="irb_missing")
    if resuming:
        reasons += [reason for reason in irb_refusals(irb_ref, utc_today(), repo_root, missing="irb_missing") if reason not in reasons]
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


def record_digest(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(raw)
