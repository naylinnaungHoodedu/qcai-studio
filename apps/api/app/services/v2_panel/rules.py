"""The V2 panel's vocabulary (plan Phase 5 D 5.3-5.11; plan 7.2, 7.7; Phase 5 spec 3.2). Standard library only, so the
ledger contracts can import it.

The rule matrix is configuration: package v4 holds it as v2.voting.matrix, versioned by routing_table_version, and the
V2 track reads it from the package (plan 7.2: the tier rules "live in versioned ThresholdSet, PanelWeights and
RoutingTable objects, not code constants"). ROUTING_TABLES holds the tables a record may name, and the loader requires
the package's matrix to equal the table its routing_table_version names (Phase 5 spec conflict 31). While D-29 is open
only degraded-matrix-v1 (option (a), PD-23) is accepted.
"""

from __future__ import annotations

import hashlib
import json

DEGRADED_MODES = ("FULL", "REDUCED-2", "REDUCED-1", "ZERO")
TIERS = (1, 2, 3)
TIER_RULES = ("1oo3", "2oo3", "1oo2", "equal-weights-share-v1", "withhold-queue-v3")
# Plan 5.6 (tier 1 1oo3, tier 2 2oo3, tier 3 equal weights), 5.9 (REDUCED-2 1oo2), 7.7, and D-29 (a): REDUCED-1 withholds
# and queues tiers 1 and 2, tier 3 follows its rule on the remaining verifier (PD-23); ZERO withholds and queues all.
RULE_MATRIX = {
    "FULL": {1: "1oo3", 2: "2oo3", 3: "equal-weights-share-v1"},
    "REDUCED-2": {1: "1oo2", 2: "1oo2", 3: "1oo2"},
    "REDUCED-1": {1: "withhold-queue-v3", 2: "withhold-queue-v3", 3: "equal-weights-share-v1"},
    "ZERO": {1: "withhold-queue-v3", 2: "withhold-queue-v3", 3: "withhold-queue-v3"},
}
ROUTING_TABLE_VERSION = "degraded-matrix-v1"
ROUTING_TABLES = {ROUTING_TABLE_VERSION: RULE_MATRIX}
MAX_MEMBERS = 3  # E-81 "M-out-of-N, N = 3"
MAX_CORRECTION_CYCLES = 2  # plan 5.8 "two cycles"
# Plan 5.8 "Correction: two cycles, then abstain and mark X2 when critical; Type E re-renders only." Package v4's
# v2.correction names these rules and the loader refuses any other; V1Track._run_v2 implements them: a failing claim
# whose objections are all type E is re-rendered (the same candidate, no revision), any other is revised through the
# generator's optional revise() or re-verified unchanged, and a claim still failing after the cycles abstains with X2.
CORRECTION_RULES = {"type_e": "re_render_only", "other": "revise_or_reverify_unchanged", "exhausted": "abstain_mark_x2"}
# The tier-3 share (equal-weights-share-v1), provisional until Q-22 (PD-25). The loader refuses another package value
# while Q-22 is unresolved, so the track and the record rule (which re-tallies every recorded claim) use one value.
TIER3_THRESHOLD = (2, 3)
PANEL_WEIGHTS_VERSION = "equal-weights-v1"  # arbitration rule 5: Dawid-Skene weights are a non-goal
TIER_RULE_ID = "context-tier-v1"
ALIGNMENT_RULE_ID = "1ooN-leakage-v1"
FAMILY_FOLD_RULE = "worst-pair-v1"
VERIFIER_PROMPT_ID, ALIGNMENT_PROMPT_ID = "blind-claim-span-v1", "alignment-item-v1"
V2_VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
OBJECTIONS = ("CONTRADICTED", "NOT_ENOUGH_INFO")  # arbitration rule 3: NOT_ENOUGH_INFO counts against a claim
from app.services.ehmf.vocabulary import EHMF_TYPES  # noqa: E402 - the one definition (Phase 7 spec 3.1)
VERIFIER_REQUEST_SCHEMA, ALIGNMENT_REQUEST_SCHEMA = "v2-verdict-request-v1", "v2-alignment-request-v1"
# Fixed text: it names no model, family, generator, learner or vote (Phase 5 spec 4.7).
VERIFIER_INSTRUCTIONS = (
    "Judge one claim against one evidence span from a public course corpus, using only the span. Answer SUPPORTED when "
    "the span states the claim, CONTRADICTED when it states the opposite, NOT_ENOUGH_INFO otherwise. When the answer is "
    "not SUPPORTED, give one EHMF type: A unsupported or contradicted content, B a citation that does not support the "
    "claim, C a misconception, D a conflict between sources, E presentation. Return the span id you relied on."
)
ALIGNMENT_INSTRUCTIONS = (
    "Rate from 1 to 5 how well this rendered answer serves the stated learning objective at the stated readability band, "
    "and flag leakage when it reveals an assessment answer key."
)
# A kill switch abstains (plan 13.6 "abstain-only, pre-verified-only"; pre-verified-only abstains while no pre-verified
# source exists, DI-83), so v2_kill_switch is an abstention reason.
V2_ABSTENTION_REASONS = ("v2_correction_exhausted", "v2_alignment_failed", "v2_kill_switch")
V2_WITHHOLD_REASONS = ("v2_degraded_withheld",)
BANNER_IDS = ("degraded-reduced-2-v1", "degraded-reduced-1-v1", "degraded-zero-v1")
BANNER_FOR_MODE = {"REDUCED-2": "degraded-reduced-2-v1", "REDUCED-1": "degraded-reduced-1-v1", "ZERO": "degraded-zero-v1"}
KILL_SWITCHES = ("none", "abstain_only", "pre_verified_only")


def _sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def verifier_prompt_hash() -> str:
    """The hash of the claim item's fixed instructions (every verifier gets the same; E-97, invariant 10)."""
    return _sha256({"id": VERIFIER_PROMPT_ID, "instructions": VERIFIER_INSTRUCTIONS, "request_schema": VERIFIER_REQUEST_SCHEMA,
                    "verdicts": list(V2_VERDICTS), "ehmf_types": list(EHMF_TYPES)})


def alignment_prompt_hash() -> str:
    return _sha256({"id": ALIGNMENT_PROMPT_ID, "instructions": ALIGNMENT_INSTRUCTIONS, "request_schema": ALIGNMENT_REQUEST_SCHEMA,
                    "ratings": [1, 2, 3, 4, 5]})


def matrix_from_package(raw: dict) -> dict[str, dict[int, str]]:
    """The package's v2.voting.matrix (string tier keys) as a table keyed by integer tiers."""
    return {mode: {int(tier): rule for tier, rule in row.items()} for mode, row in raw.items()}


def matrix_for_package(table: dict[str, dict[int, str]]) -> dict[str, dict[str, str]]:
    return {mode: {str(tier): rule for tier, rule in row.items()} for mode, row in table.items()}
