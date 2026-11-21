"""V1.3, the entailment checker interface (rule entailment-interface-v1; plan Phase 4 D: "learned checker; low score ->
flagged", EHMF A, B and C, "flag only, never HARD"; Phase 4 spec 4.4).

D-21 (hosting for the V1.3 checker) is open, so the only wired checker is the NullChecker, checker_model_id "none"
(PD-14). Plan Phase 4 E: "if none, V1.3 flags everything (before Phase 5, every tier withheld per [Decision D-20])".
With "none" no call is made and every claim is flagged no_checker. A real checker is called inline for each claim with
the texts of the claim's own cited spans:
  SUPPORTED (score None or >= v1.support_threshold)  pass / supported
  SUPPORTED below the threshold                       flag / below_support_threshold
  CONTRADICTED                                        flag / contradicted
  NOT_ENOUGH_INFO                                     flag / not_enough_info
V1.3 never hard-fails. A checker that raises, returns another type, or answers after v1.checker_timeout_ms is
unavailable: one response-level abstain / checker_unavailable (AC-4-7), logged as tutor.v1.checker_unavailable with
the cause (timeout or error) and the error class. Pre-empting a hung call belongs with a real checker (DI-54); none can
be wired while WIRED_CHECKERS holds only "none".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Literal, Protocol

from app.core.structured_logging import FIELDS
from app.services.tutor_pipeline.contracts import CheckResult, LockedClaimSet
from app.services.v1_checks.results import make_result
from app.services.v1_checks.rules import MS_PER_S, NULL_CHECKER_ID, WIRED_CHECKERS

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage, V1Params

LOGGER = logging.getLogger("qcai.tutor")
LABELS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")


@dataclass(frozen=True)
class EntailmentResult:
    label: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
    score: float | None


class EntailmentChecker(Protocol):
    checker_model_id: str

    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult: ...


class NullChecker:
    """D-21 "none": no checker exists. V1.3 never calls it; it flags every claim instead."""

    checker_model_id = NULL_CHECKER_ID

    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult:
        return EntailmentResult("NOT_ENOUGH_INFO", None)


class CheckerUnavailable(RuntimeError):
    """The package names a checker hosting that is not wired (D-21 open)."""


CHECKERS: dict[str, Callable[["ConfigPackage"], EntailmentChecker]] = {NULL_CHECKER_ID: lambda package: NullChecker()}


def get_checker(package: "ConfigPackage") -> EntailmentChecker:
    if package.v1 is None:
        raise CheckerUnavailable("the configuration package has no v1 block")
    hosting = package.v1.checker_hosting
    if hosting not in WIRED_CHECKERS or hosting not in CHECKERS:
        raise CheckerUnavailable(f"checker hosting {hosting!r} is not wired (D-21 open)")
    return CHECKERS[hosting](package)


def _mapped(result: EntailmentResult, v1: "V1Params") -> str:
    if result.label == "SUPPORTED":
        return "supported" if result.score is None or result.score >= v1.support_threshold else "below_support_threshold"
    return "contradicted" if result.label == "CONTRADICTED" else "not_enough_info"


def _valid(result: object) -> bool:
    if not isinstance(result, EntailmentResult) or result.label not in LABELS:
        return False
    score = result.score
    return score is None or (isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 1)


def check_v1_3(
    locked: LockedClaimSet,
    span_texts: Mapping[str, str],
    *,
    checker: EntailmentChecker,
    v1: "V1Params",
    attempt: int,
    clock: Callable[[], float] = time.monotonic,
    scores: dict[str, float | None] | None = None,
) -> tuple[CheckResult, ...]:
    """One result per locked claim, or one response-level abstain when the checker is unavailable. With `scores`, the
    checker's score of each claim is written into it (an enforce record's entailment_score)."""
    model_id = checker.checker_model_id
    if model_id == NULL_CHECKER_ID:
        return tuple(make_result("V1.3", "pre_render", attempt, "no_checker", claim_id=claim.claim_id, checker_model_id=model_id)
                     for claim in locked.claims)
    results = []
    for claim in locked.claims:
        cause = error = None
        started = clock()
        try:
            answer = checker.check(claim.text, tuple(span_texts.get(span_id, "") for span_id in claim.span_ids))
        except Exception as exc:  # noqa: BLE001 - an unavailable checker abstains (AC-4-7)
            cause, error, answer = "error", type(exc).__name__, None
        else:
            if (clock() - started) * MS_PER_S > v1.checker_timeout_ms:
                cause, error = "timeout", "TimeoutError"
            elif not _valid(answer):
                cause, error = "error", type(answer).__name__
        if cause is not None:
            LOGGER.warning("The V1.3 checker is unavailable; the response abstains",
                           extra={FIELDS: {"event": "tutor.v1.checker_unavailable", "cause": cause, "error": error}})
            return (make_result("V1.3", "pre_render", attempt, "checker_unavailable", checker_model_id=model_id),)
        if scores is not None:
            scores[claim.claim_id] = None if answer.score is None else float(answer.score)
        results.append(make_result("V1.3", "pre_render", attempt, _mapped(answer, v1), claim_id=claim.claim_id, checker_model_id=model_id))
    return tuple(results)
