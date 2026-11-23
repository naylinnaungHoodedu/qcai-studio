"""The V3 vocabulary (plan Phase 6 D tasks 1-4; plan 6.3 X1-X6; Phase 6 spec 3.3). Standard library only, so the loader
and the contracts can import it.

Configuration package v5's v3 block repeats these ids, and the loader refuses a package whose rule ids, trigger rules,
queue reasons or counting rule differ from the code's (plan 7.2: rules live in versioned configuration; invariant 10).
The plan's EHMF weights (plan 6.3 "A=1.0, B=1.0, C=0.6, D=0.6, E=0.4 await expert elicitation") are configuration too;
PLAN_SEVERITY holds them as decimal strings only so that the loader can bind the package's values to them while D-06 is
open (PD-34).
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
X2_TYPES = ("A", "B")
SUBJECTS = ("claim", "response")
STORED_STATES = ("queued", "adjudicated", "applied")      # "claimed" = queued with a live lease for the current round
WORKFLOW_STATES = ("queued", "claimed", "adjudicated", "applied")
VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
EHMF_TYPES = ("A", "B", "C", "D", "E")
ABSTENTION_LABELS = ("correct", "missed_answer")
MAX_ROUNDS = 3
DRAW_RULE = "seeded-sha256-bernoulli-v1"
DRAW_PURPOSE, DOUBLE_REVIEW_PURPOSE = "x6-draw-v1", "double-review-v1"
DELIVERIES = ("delivered", "legacy")
PRIORITY_RULE, EXPOSURE_RULE, K_RULE = "severity-exposure-one-minus-k-v1", "learner-deliveries-of-claim-set-v1", "panel-support-share-v1"
CLAIM_SET_KEY_RULE = "sorted-claim-ids-sha256-v1"
TIE_BREAK = ("enqueued_at", "item_id")
PLAN_SEVERITY = {"A": "1.0", "B": "1.0", "C": "0.6", "D": "0.6", "E": "0.4"}   # plan L682, as decimal strings (exact Fractions)
GOLD_SCHEMA, GOLD_CHAIN = "v3-gold-label-v1", "v3-gold"
GOLD_RECORD_HASH_RULE = "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1"
GOLD_GENESIS = "0" * 64
STOP_POLICY = "pre_verified_only"
STOP_MEASURE = "oldest-open-item-age-v1"
REVIEWER_ROLE = "reviewer"
CUSUM_ALARM_SCHEMA = "cusum-alarm-v1"
EVENT_KINDS = ("model_change", "cusum_alarm")
