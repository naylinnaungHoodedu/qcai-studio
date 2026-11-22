"""V1.9, schema validation and the readability band (rules schema-forbid-v1 and fk-grade-segments-v1; plan Phase 4 D:
"invalid schema HARD; outside band", EHMF E, "HARD/regen"; Phase 4 spec 4.10 and conflict 18).

Schema (hard). A claim plan is re-validated as a ClaimPlan (extra="forbid"), whatever object the generator returned,
and must name this generator; a generator exception counts as an invalid plan. A rendering is re-validated as a
RenderedResponse the same way, so an object built with model_construct is checked too. A failure hard-fails that
candidate: claim_plan_invalid or generator_mismatch regenerates the plan, response_envelope_invalid re-renders.

Readability (flag, re-render only; provisional band, Q-22, PD-16). The Flesch-Kincaid grade of a rendering's
non-citation segments: words are ALPHA_PATTERN matches of the NFKC text, sentences the segment count (at least 1),
syllables the vowel groups of a word less a silent final e (not after "le" or "ee"; at least 1). A grade outside
[v1.readability_min, v1.readability_max] flags the rendering (below_band or above_band): the runner re-renders, and
abstains with readability_out_of_band once the render limit is spent. The provisional band holds every template
rendering of the corpus's whole sentences, so it changes no outcome until Q-22 sets it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.services.tutor_pipeline.contracts import CheckResult, ClaimPlan, GeneratorRef, RenderedResponse
from app.services.v1_checks.results import make_result
from app.services.v1_checks.rules import ALPHA_PATTERN, FK, SCORE_DIGITS, SILENT_E_EXCEPTIONS, VOWEL_GROUP_PATTERN

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import V1Params

_ALPHA = re.compile(ALPHA_PATTERN)
_VOWELS = re.compile(VOWEL_GROUP_PATTERN)


def _coerce(model: type[BaseModel], raw: object) -> BaseModel:
    if isinstance(raw, BaseException):
        raise ValueError("the component raised")
    payload = raw.model_dump(mode="json", warnings=False) if isinstance(raw, BaseModel) else raw
    return model.model_validate(payload)


def check_v1_9_plan(raw: object, *, generator_ref: GeneratorRef, attempt: int) -> tuple[CheckResult, ClaimPlan | None]:
    try:
        plan = _coerce(ClaimPlan, raw)
    except Exception:  # noqa: BLE001 - any malformed plan or generator fault is an invalid plan (R-11)
        return make_result("V1.9", "pre_render", attempt, "claim_plan_invalid"), None
    if plan.generator != generator_ref:
        return make_result("V1.9", "pre_render", attempt, "generator_mismatch"), None
    return make_result("V1.9", "pre_render", attempt, "schema_valid"), plan


def check_v1_9_envelope(raw: object, *, attempt: int) -> tuple[CheckResult, RenderedResponse | None]:
    try:
        rendered = _coerce(RenderedResponse, raw)
    except Exception:  # noqa: BLE001 - any malformed rendering is an invalid envelope
        return make_result("V1.9", "post_render", attempt, "response_envelope_invalid"), None
    return make_result("V1.9", "post_render", attempt, "schema_valid"), rendered


def syllables(word: str) -> int:
    lowered = word.lower()
    count = len(_VOWELS.findall(lowered))
    if lowered.endswith("e") and count > 1 and not lowered.endswith(SILENT_E_EXCEPTIONS):
        count -= 1
    return max(1, count)


def readability_grade(rendered: RenderedResponse) -> float:
    segments = [segment.text for segment in rendered.segments if segment.kind != "citation"]
    words = [word for text in segments for word in _ALPHA.findall(unicodedata.normalize("NFKC", text))]
    sentences = max(1, len(segments))
    per_sentence = len(words) / sentences
    per_word = sum(syllables(word) for word in words) / len(words) if words else 0.0
    return round(FK[0] * per_sentence + FK[1] * per_word - FK[-1], SCORE_DIGITS)


def check_v1_9_readability(rendered: RenderedResponse, *, v1: "V1Params", attempt: int) -> CheckResult:
    grade = readability_grade(rendered)
    if grade < v1.readability_min:
        reason = "below_band"
    elif grade > v1.readability_max:
        reason = "above_band"
    else:
        reason = "within_band"
    return make_result("V1.9", "post_render", attempt, reason)
