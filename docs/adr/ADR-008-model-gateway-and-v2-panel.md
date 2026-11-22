# ADR-008: Model gateway and V2 panel

## Context

Phase 5 of the upgrade plan (L1357-1436) puts all model egress through one pinned gateway and adds the generator-excluded V2 panel. Before it, the tree held a dead Vertex path with a preview default model and no token, timeout or retry caps (E-42, E-66), a key that could travel in a URL (E-43), and application-default-credential discovery (E-109). The risks are R-06 (a key in URLs and logs), R-10 (provider payload leakage), R-20 (correlated verifiers), R-21 (provider outage), R-24 (model-version drift), R-47 (cost runaway) and R-48 (a zero-member panel). Holds H6 (D-12, payload register), H8 (D-07, pinned registry), H9 (A-15, approved budget) and H14 (D-21, zero-member policy) bear on the phase. D-07, D-12 and Q-09 are open, A-15 is open and D-21 is open, and the freeze (D-05) holds.

## Decision 2026-11-21 (Phase 5: provider-neutral gateway and V2)

- **An in-API gateway** (`apps/api/app/gateway/`; plan E "in-API service or sidecar") is the only module allowed model egress, through typed, pinned adapters (`AdapterSpec`); an AST guard enforces it. Every registry identifier must be pinned (`pinned-version-v1`, D-07 option (a)'s rule, PD-24); an unpinned identifier stops the configuration load and start-up (AC-5-10).
- **No real provider is registered.** Staging, production and default registries are empty; development registers four deterministic fake families (`fake-alpha` to `fake-delta`, rule `verbatim-support-v1`), which make no network call. Egress needs a per-environment opt-in (D-23, PD-22). One provider-neutral HTTP adapter exists as code, exercised only through a mock transport, to prove keys in headers and error redaction.
- **The V2 panel** is the registry's families minus the generator's (`Panel.build`; AC-5-1), one adapter per family (AC-5-2), at most three, blind: a claim item carries the claim, one bound span and the fixed instructions; objective and band go only to the alignment item (AC-5-3). Verdicts are SUPPORTED, CONTRADICTED or NOT_ENOUGH_INFO with an EHMF type; NOT_ENOUGH_INFO objects. Tier 1 (an assessment context) is 1oo3, tier 2 2oo3, tier 3 equal weights (no shipped claim is tier 3); a V1 hard fail makes no V2 call (AC-5-5).
- **Degraded modes** follow `degraded-matrix-v1`, D-29 option (a) (PD-23):

| Mode (eligible members) | Tier 1 | Tier 2 | Tier 3 | Response |
|---|---|---|---|---|
| FULL (3) | 1oo3 | 2oo3 | equal weights ≥ 2/3 | as voted |
| REDUCED-2 (2) | 1oo2 | 1oo2 | 1oo2 | label `degraded`, banner `degraded-reduced-2-v1` |
| REDUCED-1 (1) | withheld, queued for V3 | withheld, queued (D-29 (a)) | equal weights on the remaining verifier | label `degraded`, banner `degraded-reduced-1-v1` |
| ZERO (0) | withheld, queued | withheld, queued | withheld, queued | no call; no pre-verified source exists, so withhold and queue; banner `degraded-zero-v1` |

- **Correction** runs at most two cycles (plan 5.8). A failing claim whose objections are all EHMF type E (presentation) is re-rendered only, never revised, and so is a failing alignment item (type E); any other failing claim is revised through the generator (a revised claim is a new candidate judged by V1 from the start) or, when it cannot be revised, re-verified from the cache. A claim still failing is abstained and marked X2 (AC-5-7). Package v4's `v2.correction` names these rules, and the loader refuses any other.
- **The evidential cache** holds claim plans and verdicts only, shared by every instance through the application database (`evidential_cache_entries`, each key stored as a keyed digest, bounded per kind), keyed on plan 5.7's fields with the envelope's hash and plan 7.3's union; a configuration or model change misses everywhere (AC-5-8, AC-5-11).
- **Caps and a daily budget hard stop** (task 5.10): budgets are 0 outside development (A-15, hold H9), with an alert event at 4/5; each registry's budget is one row per UTC day shared by every instance, every attempt an adapter sends reserves its cost (retries included), a reply reporting more than the reservation is a budget breach, and a budget store that cannot be read or written makes members unavailable without a stop. The gateway stops on a payload violation, a secret in logs or a budget breach (plan L); the stop is shared by every instance and every new process, the stored stop lasts until an operator clears it, and a stopped instance stays stopped until it is replaced.
- **The embedding egress** of the Phase 2 semantic backend is the gateway's too (`app/gateway/embeddings.py`; the key `OPENAI_API_KEY` is no setting): its model, caps and cost are package v4's `gateway.embeddings`, and every request passes the shared stop, the payload policy and the budget; the gateway gives no embedder, because a query embedding would send the learner's query text, which plan H never lets leave.
- **`MODEL_GATEWAY`** is `off` outside development (behaviour equals Phase 4), `shadow` in development (V2 votes beside the unchanged V1 decision), and `on` is refused outside development while `phase5_exit_passed` is false (PD-28). Configuration package v4 holds every value (v3 stays readable for one release); ledger records are `ledger-entry-v3`.

## Consequences

Nothing learner-facing changes outside development: the legacy contained answers equal Phase 4's (a committed golden of body hashes), and the V2 panel runs only in the two-pass shadow. With the empty production registry, production is permanently ZERO, which is today's contained or abstaining behaviour. Every V2 record names its panel, tier, rule, votes (with each verifier's prompt hash), degraded mode, cycles and versions, so F-1 is measured over the fixture responses (`scripts/run_v2_fixtures.py`).

## Residuals

- Plan M: "Residual: correlation unmeasured until E2." Verifier correlation, V-2 and V-4 are E2 results, never claimed from fixtures (DI-75).
- Production is permanently ZERO while the registries are empty (D-07, D-12, Q-09; DI-69, DI-70, DI-73).
- An instance that adopted a stop keeps it until it is replaced, after the operator clears the shared stop; `MODEL_GATEWAY=off` stays the flag back (plan L).
- The tool names and the in-process transport are this phase's own (`mcp-tools-v1`, provisional, PD-31): plan 7.4 says "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]", and the paper's names are DI-86.
- Semantic retrieval with a provider embedding stays off: a query embedding would send the learner's query text, which plan H never lets leave, so the payload policy refuses it and the gateway gives no embedder whatever the provider decisions (DI-69, DI-70) and the Q-15 review (DI-71) say.
- The kill switches act on the two-pass shadow pipeline only, like `MODEL_GATEWAY`; no delivered answer reads them until delivery exists (DI-85).
- The paper's learner band in the alignment item and its novice-learner tier wait for the Phase 8 learner model (DI-82).

## Revision 2026-11-22 (Phase 6: critical claims, the V3 stop and the queue)

- **Critical claims.** `v2_panel.tiers.critical_for(claim_id, package, *, environment)` reads package v5's `v3.critical_claims` registry for the environment: empty outside development while D-25 is open, three synthetic entries in development (PD-33). A V2 claim verdict records `critical`; X1 is Phase 6's trigger (`app.services.v3.triggers`).
- **The sticky hold.** Under `MODEL_GATEWAY=on` the V1 track's correction loop holds a critical tier-1 claim that fails in any cycle for the rest of the response: it is never given to the generator's `revise`, it stays pending in every later cycle even when a later tally passes (a member that failed a call left the panel, so the claim's next tally runs under REDUCED-2's 1oo2), and after the last cycle it abstains with X2, or is withheld when its last outcome is V2-withheld. Its objection stays in the record (`corrections[i].failed_claim_ids`). Phase 5's record rules are unchanged.
- **The V3 stop on tier 1** (plan Phase 6 L). At a tier-1 response's first consult the V2 track reads the stop (`v3.stop.tier1_withheld`, over the pipeline's own database, `TwoPassPipeline(..., v3_stop=)`); while it holds, the response runs the `pre_verified_only` kill-switch path: no call, every claim withheld in ZERO, the record naming `kill_switch: "pre_verified_only"`, and `tutor.v2.v3_stop` logged. Tier 2 and 3 are unaffected.
- **The queue's consumption of the V3 intents.** The Phase 6 scan reads every ledger record itself (`app.services.v3.scan`): the V3 intents of Phase 4 and Phase 5 records become queue items with their reasons, X2 escalations with an A or B objection become X2 items, and the rest of the exhausted claims stay queued with reason `v2_correction_exhausted` (DI-56's consumer). `ledger.pending_v3_intents` stays a read-only helper.
