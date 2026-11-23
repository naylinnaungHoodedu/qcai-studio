"""The EHMF SLIs (plan Phase 7 I "Per-type rate, Type D disclosure share, correction cycles, config_version"; Phase 7 spec
4.11, 10.4).

Over the last window_records typed records (ledger-entry-v4), grouped by config_version: the per-type rate per 100 claims
and per 100 responses (as exact "k/n" strings, never a float), the Type D disclosure share, the correction-cycle
distribution, X2 emissions, set-changed refusals and detector-down records, the stop and the config_version in force.
Counts and versions only. Served on the reviewer-only GET /v3/metrics and logged by `python -m app.workers.ehmf status`;
/ready carries no count. Telemetry, not E2 results (plan Phase 7 H).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.ehmf.vocabulary import EHMF_SET_CHANGED, FINDING_TYPES

EVIDENCE_CLASS = "telemetry, not E2 results (plan Phase 7 H: per-type rates are not E2 results)"


def _share(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}"


def _empty() -> dict[str, Any]:
    return {"claims": 0, "responses": 0, "claim_types": Counter(), "response_types": Counter(), "conflicts": 0, "disclosed": 0,
            "cycles": Counter(), "x2": 0, "set_changed": 0, "detector_down": 0}


def slis(db: Session, package: Any, *, window_records: int = 1000, stop: Any = None) -> dict[str, Any]:
    from app.db_models import ResponseLedgerRecord
    from app.services.ledger import config_version_of

    rows = db.execute(select(ResponseLedgerRecord.entry).where(ResponseLedgerRecord.entry_schema == "ledger-entry-v4")
                      .order_by(ResponseLedgerRecord.seq.desc()).limit(int(window_records))).scalars().all()
    groups: dict[str, dict[str, Any]] = {}
    for raw in rows:
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        verification = entry.get("verification") or {}
        ehmf = verification.get("ehmf") or {}
        group = groups.setdefault(config_version_of(entry.get("versions")), _empty())
        group["responses"] += 1
        for claim in ehmf.get("claims") or []:
            group["claims"] += 1
            for name in {finding.get("type") for finding in claim.get("findings") or []}:
                group["claim_types"][name] += 1
        for name in {finding.get("type") for finding in ehmf.get("response_findings") or [] if finding.get("claim_id") is None}:
            group["response_types"][name] += 1
        conflicts = ehmf.get("conflicts") or []
        group["conflicts"] += len(conflicts)
        group["disclosed"] += sum(1 for conflict in conflicts if conflict.get("disclosed"))
        cycles = int((verification.get("v2") or {}).get("cycles") or 0)
        x2 = ehmf.get("x2_emitted") or []
        group["cycles"]["exhausted" if x2 else str(cycles)] += 1
        group["x2"] += len(x2)
        group["set_changed"] += int(verification.get("final_reason") == EHMF_SET_CHANGED)
        group["detector_down"] += int(bool(ehmf.get("detector_down")))
    by_version = {}
    for version, group in sorted(groups.items()):
        by_version[version] = {
            "per_100_claims": {**{name: _share(group["claim_types"][name], group["claims"]) for name in FINDING_TYPES}, "claims": group["claims"]},
            "per_100_responses": {**{name: _share(group["response_types"][name], group["responses"]) for name in FINDING_TYPES},
                                  "responses": group["responses"]},
            "type_d_disclosure_share": {"disclosed": group["disclosed"], "conflicts": group["conflicts"],
                                        "share": _share(group["disclosed"], group["conflicts"])},
            "correction_cycles": {key: group["cycles"][key] for key in ("0", "1", "2", "exhausted")},
            "x2_emissions": group["x2"],
            "set_changed_refusals": group["set_changed"],
            "detector_down": group["detector_down"],
        }
    from app.services.ledger import config_version_of as version_of

    return {
        "window_records": int(window_records),
        "by_config_version": by_version,
        "stop": asdict(stop) if stop is not None else None,
        "config_version": version_of({"config_package_version": package.package_version}),
        "evidence_class": EVIDENCE_CLASS,
    }
