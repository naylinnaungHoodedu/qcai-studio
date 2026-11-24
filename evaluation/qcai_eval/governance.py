"""Governance records and the confirmatory gate (spec 3.13, 4.10; AC-10-5; plan Phase 10 D task 6; PD-69).

Plan task 6: "No confirmatory run without IRB letter and OSF DOI [Evidence E-108]." A confirmatory run needs a valid IRB
record and a valid OSF record (both in the research plane), the research data plane (D-14), frozen items with a passing
freeze record and a passing pre-run contamination scan. These checks are consistency checks, not proof: the dates and
`created_at` are self-declared. A run that is not confirmatory skips this gate and is labelled exploratory everywhere.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from .canonical import canonical_sha256, lf_sha256

PROTOCOL = re.compile(r"^[A-Za-z0-9-]{3,40}$")
DOI = re.compile(r"^10\.17605/OSF\.IO/[A-Z0-9]{5,}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FROZEN_STATES = ("frozen", "release")


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
    if not isinstance(raw["letter_sha256"], str) or not HEX64.match(raw["letter_sha256"]):
        raise GovernanceError("letter_sha256")
    return raw


def load_osf(path: Path) -> dict[str, Any]:
    raw = _load(path, "osf-registration-v1", ("doi", "registered_date", "analysis_plan_sha256"))
    if not isinstance(raw["doi"], str) or not DOI.match(raw["doi"]):
        raise GovernanceError("doi")
    _date(raw["registered_date"], "registered_date")
    if not isinstance(raw["analysis_plan_sha256"], str) or not HEX64.match(raw["analysis_plan_sha256"]):
        raise GovernanceError("analysis_plan_sha256")
    return raw


def load_freeze_record(path: Path) -> dict[str, Any]:
    raw = _load(path, "ulqs-freeze-record-v1", ("dataset_sha256", "dataset_content_sha256", "rules_sha256", "agreement_sha256",
                                                 "passed", "failures"))
    if not isinstance(raw["passed"], bool) or not isinstance(raw["failures"], list):
        raise GovernanceError("passed")
    return raw


def resolve_record(reference: Any, repo_root: Path) -> Path:
    """A spec's record reference ({"path", "sha256"}) as a path, after its sha256 (LF-normalised bytes) is checked."""
    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        raise GovernanceError("reference")
    path = Path(reference["path"])
    path = path if path.is_absolute() else Path(repo_root) / path
    if lf_sha256(path) != reference.get("sha256"):
        raise GovernanceError("sha256")
    return path


def _run_date(spec: Mapping[str, Any]) -> _dt.date:
    created = str(spec.get("created_at", ""))
    try:
        return _dt.date.fromisoformat(created[:10])
    except ValueError:
        raise GovernanceError("created_at") from None


def _is_public(reference: Any, repo_root: Path) -> bool:
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


def confirmatory_refusals(spec: Mapping[str, Any], *, analysis_plan_sha256: str, dataset_sha256: str, items_states: Mapping[str, int],
                          package_raw: Mapping[str, Any], repo_root: Path, recording_source: str | None = None) -> list[str]:
    reasons: list[str] = []
    run_date = _run_date(spec)
    governance = spec.get("governance") or {}
    irb_ref, osf_ref = governance.get("irb_record"), governance.get("osf_record")
    if not irb_ref:
        reasons.append("irb_missing")
    else:
        try:
            irb = load_irb(resolve_record(irb_ref, repo_root))
            if _dt.date.fromisoformat(irb["approval_date"]) > run_date:
                reasons.append("irb_not_yet_approved")
            if irb["expiry_date"] is not None and _dt.date.fromisoformat(irb["expiry_date"]) < run_date:
                reasons.append("irb_expired")
        except GovernanceError as error:
            reasons.append(f"irb_invalid:{error.field}")
        except OSError:
            reasons.append("irb_invalid:file")
    if not osf_ref:
        reasons.append("osf_missing")
    else:
        try:
            osf = load_osf(resolve_record(osf_ref, repo_root))
            if _dt.date.fromisoformat(osf["registered_date"]) > run_date:
                reasons.append("osf_registered_after_run")
            if osf["analysis_plan_sha256"] != analysis_plan_sha256:
                reasons.append("osf_plan_mismatch")
        except GovernanceError as error:
            reasons.append(f"osf_invalid:{error.field}")
        except OSError:
            reasons.append("osf_invalid:file")
    if any(_is_public(reference, repo_root) for reference in (irb_ref, osf_ref) if reference):
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
            freeze = load_freeze_record(resolve_record(freeze_ref, repo_root))
            if freeze["passed"] is not True or freeze["dataset_sha256"] != dataset_sha256:
                reasons.append("freeze_record_failed")
        except (GovernanceError, OSError):
            reasons.append("freeze_record_failed")
    scan_ref = spec.get("pre_run_scan")
    scan_ok = False
    if scan_ref:
        try:
            scan = json.loads(resolve_record(scan_ref, repo_root).read_text(encoding="utf-8"))
            scan_ok = scan.get("report") == "qcai-research-log-scan" and scan.get("result") == "pass"
        except (GovernanceError, OSError, ValueError):
            scan_ok = False
    if not scan_ok:
        reasons.append("pre_run_scan_missing")
    if spec.get("mode") == "stub":
        reasons.append("stub_not_confirmatory")
    if spec.get("mode") == "recorded" and recording_source != "live":
        reasons.append("recording_not_live")
    return reasons


def record_digest(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(raw)
