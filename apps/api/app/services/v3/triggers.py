"""The escalation triggers X1-X6 (plan Phase 6 D task 1, trigger registry x-triggers-v1; plan 6.3 "one test per trigger";
Phase 6 spec 4.1; PD-32).

Pure functions over one validated ledger entry (ENTRY_SCHEMAS[entry_schema]) and explicit counts and events; nothing
here reads a database, a learner record or a clock.
  X1 x1_claims      a claim the record marks critical (v2.critical, from the environment's registry, D-25) at tier 1 that
                    drew a family objection in the response: an objection on its final V2 verdict, or a claim-loop
                    correction cycle that listed it (a cycle numbered at most its verdict's cycle; an alignment item's
                    re-render lists shown claims, not objections). It is withheld (holds.withheld_claim_ids).
  X2 x2_claims      a claim the record escalates X2 (V2 correction exhausted) whose final verdict has an objecting family
                    verdict of EHMF type A or B ("Type A/B unresolved after two cycles"); every other exhausted claim is
                    queued with reason v2_correction_exhausted and no trigger.
  X3 x3_fires       a learner flag (feedback.record_flag; F_i = 0, never a verdict).
  X4 x4_fires       the record's V1.5 mark (a verified record), or V1.5's rule over a legacy or v1 record's sufficiency with
                    the package's X4 margin for its gate (v1.v1_5.x4_margin).
  X5 x5_model_changes, x5_active
                    a model-version change of a known model key (registry or record sightings) or a CUSUM alarm event
                    (events.record_cusum_alarm) opens a window of raised audit rate (draw.draw_trigger).
  X6 the seeded audit draw (draw.draw_trigger).
Queue reasons without a trigger (queue_reasons): v1_3_flag (only without a completed V2 vote: "after Phase 5, flags route
to V2"), v1_8_misconception, v2_degraded_withheld, and v2_correction_exhausted. The EHMF types an item's severity reads
are claim_types and response_types; a disclosed V1.7 conflict weighs nothing (plan Phase 7 A "D 0.6 (0 when disclosed)").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from app.services.v3.priority import response_k, support_share

DISCLOSED = ("V1.7", "conflict_disclosed")


@dataclass(frozen=True)
class ItemSpec:
    claim_key: str                      # a claim id, or "" for the response
    subject: Literal["claim", "response"]
    triggers: frozenset[str]
    reasons: frozenset[str]
    ehmf_types: frozenset[str]          # the types severity reads (4.3)
    k: Fraction
    held: bool                          # "X1" in triggers


@dataclass(frozen=True)
class ModelChange:
    model_key: str                      # "verifier:<model_id>", "generator:<generator_id>", "checker:V1.3"
    from_version: str
    to_version: str


@dataclass(frozen=True)
class RecordTriggers:
    record_kind: Literal["delivery", "shadow"]
    items: tuple[ItemSpec, ...]
    sightings: tuple[tuple[str, str], ...]    # sorted (model_key, model_version)


def _verdicts(entry: Any) -> tuple:
    verification = getattr(entry, "verification", None)
    return tuple(getattr(verification, "verdicts", ()) or ()) if verification is not None else ()


def _v2_block(entry: Any) -> Any:
    verification = getattr(entry, "verification", None)
    return getattr(verification, "v2", None) if verification is not None else None


def family_objection_types(v2: Any) -> tuple[str, ...]:
    """The EHMF types of a V2 claim verdict's objecting family verdicts, in family order (voting.objection_types)."""
    from app.services.v2_panel.voting import objection_types

    if v2 is None:
        return ()
    by_family: dict[str, list] = {}
    for vote in sorted(v2.votes, key=lambda item: (item.family, item.span_id)):
        by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
    return tuple(ehmf for ehmf in objection_types(by_family) if ehmf is not None)


# ----------------------------------------------------------------------------------------------------- X1 to X4


def x1_claims(entry: Any) -> frozenset[str]:
    block = _v2_block(entry)
    if block is None:
        return frozenset()
    judged = [verdict for verdict in _verdicts(entry) if getattr(verdict, "v2", None) is not None]
    loop_cycles = max((verdict.v2.cycle for verdict in judged), default=0)
    listed = {claim_id for correction in block.corrections if correction.cycle <= loop_cycles for claim_id in correction.failed_claim_ids}
    fired = set()
    for verdict in judged:
        v2 = verdict.v2
        if v2.critical is True and v2.tier == 1 and (v2.objections >= 1 or verdict.claim_id in listed):
            fired.add(verdict.claim_id)
    return frozenset(fired)


def x2_claims(entry: Any) -> frozenset[str]:
    from app.services.v3.rules import X2_TYPES

    fired = set()
    for verdict in _verdicts(entry):
        intent = getattr(verdict, "v3", None)
        if intent is None or getattr(intent, "escalation", None) != "X2":
            continue
        if set(family_objection_types(getattr(verdict, "v2", None))) & set(X2_TYPES):
            fired.add(verdict.claim_id)
    return frozenset(fired)


def x3_fires(flags: int) -> bool:
    return int(flags) >= 1


def x4_fires(entry: Any, *, x4_margin: Mapping[str, float]) -> bool:
    verification = getattr(entry, "verification", None)
    if verification is not None:
        return any(check.check_id == "V1.5" and check.reason_code == "near_miss" for check in verification.checks)
    from app.services.v1_checks.v1_5_abstention import check_v1_5

    sufficiency = entry.retrieval.sufficiency
    if sufficiency is None or sufficiency.gate not in x4_margin:
        return False
    return check_v1_5(sufficiency, x4_margin=float(x4_margin[sufficiency.gate])).reason_code == "near_miss"


# ----------------------------------------------------------------------------------------------------------- X5


def record_sightings(entry: Any) -> tuple[tuple[str, str], ...]:
    """The (model_key, model_version) pairs a record names: every V2 claim and alignment vote's verifier, the generator,
    and the V1.3 checker."""
    sightings: set[tuple[str, str]] = set()
    for verdict in _verdicts(entry):
        v2 = getattr(verdict, "v2", None)
        for vote in (v2.votes if v2 is not None else ()):
            sightings.add(("verifier:" + vote.verifier_model_id, vote.verifier_model_version))
    block = _v2_block(entry)
    alignment = getattr(block, "alignment", None) if block is not None else None
    for vote in (alignment.votes if alignment is not None else ()):
        sightings.add(("verifier:" + vote.verifier_model_id, vote.verifier_model_version))
    generator_id = getattr(entry.versions, "generator_id", None)
    if generator_id:
        sightings.add(("generator:" + generator_id, entry.provenance.generator_model_id))
    checker = getattr(entry.provenance, "v1_3_checker_model_id", None)
    if checker:
        sightings.add(("checker:V1.3", checker))
    return tuple(sorted(sightings))


def registry_sightings(registry: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({("verifier:" + spec.model_id, spec.model_version) for spec in registry.verifiers()}))


def x5_model_changes(known: Mapping[str, str], sightings: Iterable[tuple[str, str]]) -> tuple[ModelChange, ...]:
    """A change for each sighting whose key is known with another version; an unknown key is a first sighting."""
    return tuple(ModelChange(model_key=key, from_version=known[key], to_version=version)
                 for key, version in sightings if key in known and known[key] != version)


def x5_active(windows: Iterable[tuple[int, int]], seq: int) -> bool:
    """Whether an open X5 window (from_seq, remaining) covers the delivery at seq."""
    return any(from_seq < seq and remaining > 0 for from_seq, remaining in windows)


# ------------------------------------------------------------------------------------------- reasons and types


def queue_reasons(verdict: Any) -> frozenset[str]:
    intent = getattr(verdict, "v3", None)
    if intent is None:
        return frozenset()
    reasons = set(intent.reasons)
    kept = {reason for reason in reasons if reason in ("v1_8_misconception", "v2_degraded_withheld", "v2_correction_exhausted")}
    v2 = getattr(verdict, "v2", None)
    if "v1_3_flag" in reasons and (v2 is None or v2.outcome == "withheld"):
        kept.add("v1_3_flag")
    return frozenset(kept)


def _result_types(results: Iterable[Any]) -> set[str]:
    types: set[str] = set()
    for result in results:
        if result.outcome == "pass" or (result.check_id, result.reason_code) == DISCLOSED:
            continue
        types.update(result.ehmf_types)
    return types


def claim_types(verdict: Any) -> frozenset[str]:
    types = set(family_objection_types(getattr(verdict, "v2", None)))
    types |= _result_types(getattr(verdict, "v1", ()) or ())
    return frozenset(types)


def response_types(entry: Any) -> frozenset[str]:
    types: set[str] = set()
    for verdict in _verdicts(entry):
        types |= claim_types(verdict)
    verification = getattr(entry, "verification", None)
    if verification is not None:
        types |= _result_types(check for check in verification.checks if check.claim_id is None)
    return frozenset(types)


def evaluate(entry: Any, *, x4_margin: Mapping[str, float]) -> RecordTriggers:
    kind: Literal["delivery", "shadow"] = "shadow" if entry.delivery == "shadow" else "delivery"
    x1, x2 = x1_claims(entry), x2_claims(entry)
    items = []
    for verdict in _verdicts(entry):
        triggers = frozenset(({"X1"} if verdict.claim_id in x1 else set()) | ({"X2"} if verdict.claim_id in x2 else set()))
        reasons = queue_reasons(verdict)
        if triggers or reasons:
            items.append(ItemSpec(claim_key=verdict.claim_id, subject="claim", triggers=triggers, reasons=reasons,
                                  ehmf_types=claim_types(verdict), k=support_share(getattr(verdict, "v2", None)), held="X1" in triggers))
    if x4_fires(entry, x4_margin=x4_margin):
        items.append(ItemSpec(claim_key="", subject="response", triggers=frozenset({"X4"}), reasons=frozenset(),
                              ehmf_types=response_types(entry) | {"A"}, k=response_k(entry), held=False))
    return RecordTriggers(record_kind=kind, items=tuple(items), sightings=record_sightings(entry))


def response_spec(entry: Any, trigger: str) -> ItemSpec:
    """The response item an X3, X5 or X6 trigger adds to a record (merged into its (ledger_seq, "") item)."""
    if entry is None:
        return ItemSpec(claim_key="", subject="response", triggers=frozenset({trigger}), reasons=frozenset(), ehmf_types=frozenset(),
                        k=Fraction(0), held=False)
    return ItemSpec(claim_key="", subject="response", triggers=frozenset({trigger}), reasons=frozenset(),
                    ehmf_types=response_types(entry), k=response_k(entry), held=False)
