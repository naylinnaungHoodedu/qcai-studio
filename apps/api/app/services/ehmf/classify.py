"""Per-finding EHMF typing (plan Phase 7 D task 1; Phase 7 spec 4.1; PD-40).

Pure over a verification record: each failing V1 result and each objecting V2 family verdict is one finding, typed by
the routing table (routing.FINDING_RULES), never by the check's whole per-check tuple (CheckResult.ehmf_types says
which check ran). A claim's entry holds the results of its own claim id (never the response-level results the verdict
also carries), one V1.7 D finding per conflict that lists the claim, and its V2 findings; response-level results of
every attempt, dropped proposals and the alignment item's leakage are typed once, as response findings. The verifier's
own type is recorded as reported_type and never decides the finding type.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.ehmf.routing import FINDING_RULES, NO_FINDING


def finding_for_v1(result: Any) -> Any:
    """The finding a V1 result records, or None (a pass, a mark, or a detector state: V1.3 no_checker / unavailable)."""
    from app.services.tutor_pipeline.contracts import EhmfFinding

    if result.outcome in ("pass", "mark") or (result.check_id, result.reason_code) in NO_FINDING:
        return None
    finding_type = FINDING_RULES.get((result.check_id, result.reason_code))
    if finding_type is None:
        raise ValueError(f"the routing table has no type for {result.check_id} {result.reason_code}")
    return EhmfFinding(source=result.check_id, reason_code=result.reason_code, type=finding_type, attempt=result.attempt,
                       claim_id=result.claim_id)


def findings_for_v2(verdict: Any) -> tuple[Any, ...]:
    """One finding per objecting member family's folded verdict (rule F, worst-pair-v1): CONTRADICTED is A,
    NOT_ENOUGH_INFO B2. A withheld claim (no vote) has none."""
    from app.services.tutor_pipeline.contracts import EhmfFinding
    from app.services.v2_panel.voting import family_verdict

    v2 = getattr(verdict, "v2", None)
    if v2 is None or v2.outcome == "withheld":
        return ()
    by_family: dict[str, list] = {}
    for vote in sorted(v2.votes, key=lambda item: (item.family, item.span_id)):
        by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
    findings = []
    for family in sorted(by_family):
        folded, reported = family_verdict(by_family[family])
        if folded == "SUPPORTED":
            continue
        findings.append(EhmfFinding(source="V2", reason_code=folded, type=FINDING_RULES[("V2", folded)], attempt=1,
                                    claim_id=verdict.claim_id, reported_type=reported, family=family))
    return tuple(findings)


def _conflict_findings(claim_id: str, disclosure: Any, generation: int) -> list[Any]:
    from app.services.tutor_pipeline.contracts import EhmfFinding

    if disclosure is None:
        return []
    reason = "conflict_disclosed" if disclosure.policy == "disclose" else "conflict_withheld"
    return [EhmfFinding(source="V1.7", reason_code=reason, type="D", attempt=max(generation, 1), claim_id=claim_id)
            for conflict in disclosure.conflicts if claim_id in conflict.claim_ids]


def claim_entry(verdict: Any, *, disclosure: Any, generation: int, weights: Mapping[str, str]) -> Any:
    from app.services.tutor_pipeline.contracts import EhmfClaim, primary_of

    findings = [finding for result in verdict.v1 if result.claim_id == verdict.claim_id
                if (finding := finding_for_v1(result)) is not None]
    findings.extend(_conflict_findings(verdict.claim_id, disclosure, generation))
    findings.extend(findings_for_v2(verdict))
    primary, weight = primary_of(findings, dict(weights))
    return EhmfClaim(claim_id=verdict.claim_id, findings=tuple(findings), primary=primary, weight=weight)


def response_findings(record: Any) -> tuple[Any, ...]:
    """Response-level results (claim_id None) of every attempt, V1.2 results whose claim is not a verdict's (dropped
    proposals), and the alignment item's leakage (E) when it failed. Each is typed once."""
    from app.services.tutor_pipeline.contracts import EhmfFinding

    verdict_ids = {verdict.claim_id for verdict in record.verdicts}
    findings = []
    for result in record.checks:
        if result.claim_id is None or (result.check_id == "V1.2" and result.claim_id not in verdict_ids):
            finding = finding_for_v1(result)
            if finding is not None:
                findings.append(finding)
    alignment = getattr(getattr(record, "v2", None), "alignment", None)
    if alignment is not None and alignment.outcome == "fail":
        findings.append(EhmfFinding(source="alignment", reason_code="leakage", type="E", attempt=1))
    return tuple(findings)


def claim_types(entry: Any) -> tuple[str, ...]:
    """The sorted unique finding types of one EhmfClaim."""
    return tuple(sorted({finding.type for finding in entry.findings}))


def types_of(findings: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({finding.type for finding in findings}))
