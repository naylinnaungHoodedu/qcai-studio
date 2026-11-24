"""The V3 vocabulary (plan Phase 6 D tasks 1-4; plan 6.3 X1-X6; Phase 6 spec 3.3). Standard library only, so the loader
and the contracts can import it.

Configuration package v5's v3 block repeats these ids, and the loader refuses a package whose rule ids, trigger rules,
queue reasons or counting rule differ from the code's (plan 7.2: rules live in versioned configuration; invariant 10).
The plan's EHMF weights (plan 6.3 "A=1.0, B=1.0, C=0.6, D=0.6, E=0.4 await expert elicitation") are configuration too;
ehmf.vocabulary.PLAN_WEIGHTS holds them as decimal strings only so that the loader can bind the package's values to them
while the decisions are open (PD-34, PD-41). Package v6 (Phase 7) moves X2 to x-triggers-v2: every X2 escalation fires.
"""

from __future__ import annotations

V3_VERSION = "v3-audit-v1"
TRIGGERS = ("X1", "X2", "X3", "X4", "X5", "X6")
TRIGGER_REGISTRY_VERSION = "x-triggers-v1"
TRIGGER_RULES = {"X1": "critical-claim-objection-v1", "X2": "v2-exhausted-type-a-b-v1", "X3": "learner-flag-f0-v1",
                 "X4": "v1-5-margin-mark-v1", "X5": "model-version-change-or-cusum-alarm-v1", "X6": "seeded-sha256-bernoulli-v1"}
# X1 fires on a critical claim's objection at any tier (plan AC-5-4 "critical claims follow X1 from Phase 6"); the claim
# is withheld at tier 1 only (plan task 1 "withheld at tier 1"; the runner's sticky hold). Phase 6 spec conflict 1.
X1_TIERS = (1, 2, 3)
X1_WITHHOLD_TIER = 1
V3_COUNTED = ("X1", "X2", "X3", "X4")            # plan 15.3 "V-3 numerator counts X1-X4 only; audits are proof tests" (PD-37)
QUEUE_REASONS = ("v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld")
# Package schema 7 (Phase 9 spec conflict 24): the ranking controller's empty-eligible-set fallback enqueues a response item with
# this reason (AC-9-6). It is not an X trigger, so V3_COUNTED is unchanged; schemas 5 and 6 keep QUEUE_REASONS.
RANKING_QUEUE_REASON = "ranking_empty_eligible_set"
QUEUE_REASONS_V7 = (*QUEUE_REASONS, RANKING_QUEUE_REASON)
X2_TYPES = ("A", "B")                            # x-triggers-v1 (package v5) only
TRIGGER_REGISTRY_VERSION_V2 = "x-triggers-v2"
TRIGGER_RULES_V2 = {**TRIGGER_RULES, "X2": "v2-exhausted-any-type-v2"}   # package v6 (Phase 7 spec conflict 3; PD-44)
SUBJECTS = ("claim", "response")
STORED_STATES = ("queued", "adjudicated", "applied")      # "claimed" = queued with a live lease for the current round
WORKFLOW_STATES = ("queued", "claimed", "adjudicated", "applied")
VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
from app.services.ehmf.vocabulary import EHMF_TYPES  # noqa: E402 - the one definition (Phase 7 spec 3.1)
ABSTENTION_LABELS = ("correct", "missed_answer")
MAX_ROUNDS = 3
DRAW_RULE = "seeded-sha256-bernoulli-v1"
DRAW_PURPOSE, DOUBLE_REVIEW_PURPOSE = "x6-draw-v1", "double-review-v1"
DELIVERIES = ("delivered", "legacy")
PRIORITY_RULE, EXPOSURE_RULE, K_RULE = "severity-exposure-one-minus-k-v1", "learner-deliveries-of-claim-set-v1", "panel-support-share-v1"
CLAIM_SET_KEY_RULE = "sorted-claim-ids-sha256-v1"
TIE_BREAK = ("enqueued_at", "item_id")
GOLD_SCHEMA, GOLD_CHAIN = "v3-gold-label-v1", "v3-gold"
GOLD_RECORD_HASH_RULE = "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1"
GOLD_GENESIS = "0" * 64
STOP_POLICY = "pre_verified_only"
STOP_MEASURE = "oldest-open-item-age-v1"
REVIEWER_ROLE = "reviewer"
CUSUM_ALARM_SCHEMA = "cusum-alarm-v1"
EVENT_KINDS = ("model_change", "cusum_alarm")
