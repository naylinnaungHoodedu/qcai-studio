# EHMF routing specification (ehmf-routing-v1)

Plan Phase 7 F "Routing spec" (task 1; PD-40). The table below is configuration package v6 `ehmf.routing.table` (its
sha256 is `ehmf.routing.sha256`) with the weights of `ehmf.weights` (provisional until the PI's expert elicitation, PD-41,
DI-108). `test_plan_f_the_routing_document_matches_the_package` compares every row with the package. The code is
`apps/api/app/services/ehmf/routing.py` (`FINDING_RULES`); a record is validated against the routing version it names.

A finding is one failure-mode observation: a failing V1 result or an objecting V2 family verdict, typed by its source
and reason (never by the check's whole per-check tuple, which `CheckResult.ehmf_types` keeps for ledger compatibility).
B1 and B2 weigh as B; a disclosed V1.7 conflict weighs `D_disclosed` (0, plan "D 0.6 (0 when disclosed)"). A claim's
primary type is its heaviest finding, ties in the order B1, A, B2, D, C, E. The verifier's own type is recorded as
`reported_type` and never decides a finding's type. Detector states are not findings: V1.3 `no_checker` (absent under
D-21), V1.3 `checker_unavailable` (down) and V1.5 `near_miss` (a mark).

| Type | Detectors (source:reason) | Mitigation | Owner | Telemetry | Weight | Final |
|---|---|---|---|---|---|---|
| A | `V1.2:negation_mismatch`, `V1.2:no_bound_claims`, `V1.2:not_quotable`, `V1.2:not_verbatim`, `V1.2:outside_bundle`, `V1.2:partial_sentence`, `V1.2:quantity_mismatch`, `V1.2:unbound`, `V1.3:contradicted`, `V1.5:below_floor`, `V1.5:corpus_version_mismatch`, `V1.5:insufficient_coverage`, `V1.5:no_match`, `V1.5:no_query_terms`, `V1.5:no_quotable_evidence`, `V2:CONTRADICTED` | revise_or_abstain | ml_engineer | `ehmf.type.A` | 1 | no |
| B1 | `V1.1:content_hash_mismatch`, `V1.1:malformed_span_id`, `V1.1:unresolvable`, `V1.2:unresolvable` | final | ml_engineer | `ehmf.type.B1` | 1 | yes |
| B2 | `V1.3:below_support_threshold`, `V1.3:not_enough_info`, `V2:NOT_ENOUGH_INFO` | recite_or_abstain | ml_engineer | `ehmf.type.B2` | 1 | no |
| C | `V1.8:misconception_match` | bind_step_or_label_analogy | content_owner | `ehmf.type.C` | 3/5 | no |
| D | `V1.4:unmapped_factual_sentence`, `V1.7:conflict_disclosed`, `V1.7:conflict_withheld` | precedence_plus_disclosure | content_owner | `ehmf.type.D` | 3/5 | no |
| E | `V1.4:citation_list_mismatch`, `V1.4:citation_marker_mismatch`, `V1.4:citation_not_on_claim`, `V1.4:citation_outside_locked_set`, `V1.4:claim_uncited`, `V1.4:duplicate_claim`, `V1.4:empty`, `V1.4:no_claim_rendered`, `V1.4:render_failed`, `V1.4:text_not_segments`, `V1.6:keyed_answer_present`, `V1.9:above_band`, `V1.9:below_band`, `V1.9:claim_plan_invalid`, `V1.9:generator_mismatch`, `V1.9:response_envelope_invalid`, `alignment:leakage` | regenerate_pedagogical_pass | ml_engineer | `ehmf.type.E` | 2/5 | no |

## Precedence (precedence-v1, recorded only)

"newer peer-reviewed over older, primary over secondary" (plan task 3, E-79). A winner is named only when both items carry
complete Content-Owner source metadata (`source_year`, `peer_reviewed`, `source_role` on the corpus manifest item, never
inferred) and a rule orders the pair; otherwise the basis is `metadata_incomplete`, `no_rule_applies` or `rules_disagree`
and no source wins. Precedence is recorded in the typed record only: it never changes which claims are delivered or
withheld (PD-42; applying it is DI-111). No item carries the metadata today (DI-107).

## Conflict disclosure template (conflict-disclosure-v2)

Every detected conflict is disclosed with both spans when the V1.7 policy is `disclose`, and weighs 0. The template
(package `ehmf.conflicts.disclosure_template`) names the conflict kinds and the public item ids, never span text:

> These course sources disagree ({kinds}) between {items}. Both passages are shown; neither is preferred unless a precedence basis is named: {basis}.

An undisclosed conflict stays a V1.7 `conflict_withheld` (weight D). A conflict with a source outside the public corpus
is not detected (plan M residual).

## Correction and X2

At most two correction cycles (plan task 4; `ehmf.correction`, `v2.correction.max_cycles`); the correction guard is the
loop's only bound and refuses a third cycle. Every claim still failing after two cycles abstains with escalation X2,
whatever its type (AC-7-5), and V3's X2 fires on every such escalation (`x-triggers-v2`; severity still ranks A and B
first). A Type E correction re-renders the same candidate and keeps its claim set and span set; a re-render that changes
either is refused and the response abstains (`ehmf_set_changed`, AC-7-4). B1 is final: never repaired, never voted on.
