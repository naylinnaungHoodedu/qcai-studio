"""The EHMF routing table ehmf-routing-v1 (plan Phase 7 D task 1 and F "Routing spec"; Phase 7 spec 3.2; PD-40).

FINDING_RULES maps (source, reason) to the finding type of the failure mode it observes; a source is a V1 check id, "V2"
or "alignment". A record is validated against the table its own routing_version names, so a later routing version never
invalidates a stored record. Detector states that are not failure modes have no rule: V1.3 no_checker (detector absent,
D-21), V1.3 checker_unavailable (detector down) and V1.5 near_miss (a mark). Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.ehmf.vocabulary import FINDING_TYPES, MITIGATIONS, OWNERS, ROUTING_VERSION, TELEMETRY

# The V1 reason vocabularies, named here (standard library only) and compared with contracts.REASON_OUTCOMES by a test.
_V1_2_BINDING = ("unbound", "outside_bundle", "not_quotable", "partial_sentence", "not_verbatim")
_V1_4_PRESENTATION = ("empty", "text_not_segments", "duplicate_claim", "citation_outside_locked_set", "citation_not_on_claim",
                      "citation_marker_mismatch", "no_claim_rendered", "claim_uncited", "citation_list_mismatch", "render_failed")
_V1_5_ABSTAIN = ("no_query_terms", "no_match", "insufficient_coverage", "below_floor", "corpus_version_mismatch", "no_quotable_evidence")

FINDING_RULES: dict[tuple[str, str], str] = {
    **{("V1.1", reason): "B1" for reason in ("unresolvable", "malformed_span_id", "content_hash_mismatch")},
    ("V1.2", "unresolvable"): "B1",
    **{("V1.2", reason): "A" for reason in (*_V1_2_BINDING, "negation_mismatch", "quantity_mismatch", "no_bound_claims")},
    ("V1.3", "contradicted"): "A",
    ("V1.3", "not_enough_info"): "B2",
    ("V1.3", "below_support_threshold"): "B2",
    ("V1.4", "unmapped_factual_sentence"): "D",
    **{("V1.4", reason): "E" for reason in _V1_4_PRESENTATION},
    **{("V1.5", reason): "A" for reason in _V1_5_ABSTAIN},
    ("V1.6", "keyed_answer_present"): "E",
    ("V1.7", "conflict_withheld"): "D",
    ("V1.7", "conflict_disclosed"): "D",
    ("V1.8", "misconception_match"): "C",
    **{("V1.9", reason): "E" for reason in ("claim_plan_invalid", "generator_mismatch", "response_envelope_invalid", "below_band", "above_band")},
    ("V2", "CONTRADICTED"): "A",
    ("V2", "NOT_ENOUGH_INFO"): "B2",
    ("alignment", "leakage"): "E",
}
FINDING_RULES_BY_VERSION: dict[str, dict[tuple[str, str], str]] = {ROUTING_VERSION: FINDING_RULES}
# Detector states with no finding (spec 3.2).
NO_FINDING = {("V1.3", "no_checker"): "detector_absent", ("V1.3", "checker_unavailable"): "detector_down", ("V1.5", "near_miss"): "mark"}


def finding_type(source: str, reason: str, *, routing_version: str = ROUTING_VERSION) -> str | None:
    return FINDING_RULES_BY_VERSION.get(routing_version, {}).get((source, reason))


def routing_table() -> dict[str, Any]:
    """Per finding type: its detectors ("source:reason", sorted), mitigation, owner, telemetry key and whether it is final."""
    table: dict[str, Any] = {}
    for name in FINDING_TYPES:
        detectors = sorted(f"{source}:{reason}" for (source, reason), value in FINDING_RULES.items() if value == name)
        table[name] = {"detectors": detectors, "mitigation": MITIGATIONS[name], "owner": OWNERS[name], "telemetry": TELEMETRY[name],
                       "final": name == "B1"}
    return table


def routing_sha256() -> str:
    canonical = json.dumps(routing_table(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def mitigation_for(name: str) -> str:
    return MITIGATIONS[name]
