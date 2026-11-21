"""One constructor for every V1 CheckResult (Phase 4 spec 3.2): the outcome and the EHMF types come from the
contract vocabulary (REASON_OUTCOMES, EHMF_BY_CHECK), so a check names only its reason and can never record an
outcome its reason does not have."""

from __future__ import annotations

from app.services.tutor_pipeline.contracts import EHMF_BY_CHECK, REASON_OUTCOMES, CheckResult


def make_result(check_id: str, stage: str, attempt: int, reason: str, *, claim_id: str | None = None,
                checker_model_id: str | None = None) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        stage=stage,
        attempt=attempt,
        outcome=REASON_OUTCOMES[check_id][reason],
        ehmf_types=EHMF_BY_CHECK[check_id],
        reason_code=reason,
        claim_id=claim_id,
        checker_model_id=checker_model_id,
    )
