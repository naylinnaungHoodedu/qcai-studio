"""The ranking vocabulary (plan Phase 9; docs/architecture/phase9-implementation-spec.md 3.1). Standard library only, so
the configuration-package loader can import it.

Configuration package v7's ranking block repeats these ids, and the loader refuses a package whose versions, rule ids or
vocabularies differ from the code's (plan 7.2: rules live in versioned configuration; invariant 10).
"""

from __future__ import annotations

RANKING_VERSION = "ranking-v1"
PARAMETERS_VERSION = "ranking-params-v1"
EVENT_SCHEMA = "ranking-event-v1"
STATE_SCHEMA = "ranking-state-v1"
# The first package schema and major with a ranking block (Phase 9). The one constant: config_package.RANKING_SCHEMA_VERSION
# is this value, and LATEST_SCHEMA_VERSION follows it. Renumbering the Phase 9 package (spec 15) edits this line.
RANKING_FIRST_MAJOR = 7

CLUSTER_RULE = "cluster-module-v1"
UNSCOPED = "unscoped"
# The MODULE_BLUEPRINTS slugs, in order (a test keeps them equal; the loader compares the package's list with this one).
CLUSTERS = (
    "nisq-hybrid-workflows",
    "ai-for-quantum-hardware",
    "quantum-enhanced-applications",
    "representation-explainability",
    "industry-use-cases",
    "thermodynamics-roadmap",
    "hardware-constrained-introduction",
    "hardware-constrained-models",
    "intermediate-quantum-programming",
    "advanced-quantum-software",
    "quantum-finance-programming",
)
TASK_TYPE_RULE = "tier-1-quiz-item-v1"
TIER_SOURCE_RULE = "tier-source-v1"
# Paper Sec. VII-A's task types; only explanation and quiz_item occur (the other four are reserved values, PD-50).
TASK_TYPES = ("explanation", "worked_example", "hint", "quiz_item", "summary", "video_script")
ACTIVE_TASK_TYPES = ("explanation", "quiz_item")
RATINGS = ("A", "B", "C", "D")

INPUT_KINDS = ("config", "availability", "model_seen", "model_change", "commission", "recommission_pass", "recommission_fail", "outcome",
               "skipped", "feedback", "hold_release", "tick")
DERIVED_KINDS = ("select", "batch", "promote", "demote", "alarm", "hold")
CONTROL_KINDS = ("checkpoint", "stop", "clear_stop")
EVENT_KINDS = (*INPUT_KINDS, *DERIVED_KINDS, *CONTROL_KINDS)

SKIP_REASONS = ("unparsed", "no_verification", "generator_unknown", "stale_version", "not_generated", "budget_exceeded", "detector_down",
                "kill_switch", "v2_withheld", "no_v2_verdict", "panel_not_reached", "corpus_conflict")
GATEWAY_INELIGIBLE = ("stopped", "kill_switch", "disabled", "egress_refused", "budget", "budget_unavailable", "down")
INELIGIBLE = (*GATEWAY_INELIGIBLE, "rating", "capped", "family_unknown")
QUEUE_REASON = "ranking_empty_eligible_set"
STOP_REASONS = ("replay_mismatch", "state_mismatch")
CLEAR_CAUSES = ("fixed_code", "fixed_data", "restored_backup")
SCAN_REFUSALS = ("ranking_off", "stopped", "uncommissioned")
SEED_RULE = "sha256-u64-v1"
ARITHMETIC = "decimal-prec-34-half-even-quantize-1e-18-v1"
QUANTILE_RULE = "decimal-regularized-incomplete-beta-bisection-v1"
CLONE_RULE = "extractive-clone-v1"
STATIC_VERSION_RULE = "evidential-prompt-hash-16-v1"
CHAIN_RULE = "ranking-chain-v1"
GENESIS = "0" * 64
STATE_KEY = "_state"
# The advisory lock of the ranking scan, taken before V3's (V3_SCAN_LOCK_KEY = 7_401_206; spec 4.10).
RANKING_SCAN_LOCK_KEY = 7_401_209

# The rule ids the package's ranking block must name (the loader compares each).
RULES = {
    "trust.quantile_rule": QUANTILE_RULE,
    "quality.missing": "drop-and-renormalise-v1",
    "quality.h_rule": "ehmf-claim-weight-density-v1",
    "quality.v_rule": "first-pass-v1-v2-pass-share-v1",
    "quality.k_rule": "one-minus-normalised-vote-entropy-v1",
    "quality.s_rule": "missing-until-d21",
    "quality.f_rule": "shown-records-only-rating-minus-one-over-four-flag-zero-v1",
    "clean_rule": "first-pass-no-correction-no-generator-escalation-v1",
    "selection.thompson": "seeded-inverse-cdf-v1",
    "selection.tie_break": "adapter_id",
    "promotion.comparison": "strictly-greater",
    "promotion.streak": "eligible-batches-only-v1",
    "promotion.rating_condition": "rating(h) >= rating(g)",
    "promotion.demotion": "immediate",
    "micro_batch.time_trigger": "record-time-and-scan-tick-v1",
    "cusum.hold": "until-x5-window-closes-v1",
    "cusum.sustained": "second-alarm-while-held-v1",
    "recommission.pass_rule": "every-item-generated-no-failed-first-pass-v1",
    "recommission.commissioning_prior": "one-plus-clean-one-plus-failed-v1",
    "penalties.cost_rule": "cost-units-over-max-v1",
    "fallback.empty_eligible_set": "abstain_and_enqueue_v3",
    "replay.arithmetic": ARITHMETIC,
    "replay.event_schema": EVENT_SCHEMA,
    "replay.state_schema": STATE_SCHEMA,
    "replay.stop": "replay_mismatch",
    "models.static_version_rule": STATIC_VERSION_RULE,
    "models.clone_rule": CLONE_RULE,
    "models.registry_capability": "generate",
    "contexts.cluster_rule": CLUSTER_RULE,
    "contexts.task_type_rule": TASK_TYPE_RULE,
    "contexts.tier_source_rule": TIER_SOURCE_RULE,
    "contexts.unscoped": UNSCOPED,
}
