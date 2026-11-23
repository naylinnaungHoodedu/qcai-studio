# QC+AI Studio — Phase 5 Implementation Spec
## Provider-neutral gateway and V2 (plan L1357-1436)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Branch:** `phase5/gateway-v2`, cut from `origin/main` `98f7cc4` (Phase 4 merged, PR #36; tree identical to `aa9f1ef`).
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`.
  - Phase 5 block: L1357-1436.
  - Section 7: L811-983. This covers 7.1 (L828-829), the pipeline (L832-852), 7.3 (L866-875), VerificationVerdict (L894-902), 7.7 degraded modes (L940-958) and 7.8 invariants (L960-981).
  - Flags and kill switches (13.6): L2371-2380; required checks (13.2): L2328-2335.
  - 18.3/18.4: L2960-3026.
  - Holds (9.4): L1904-1926 (H6, H8, H9, H14, H15).
- **Paper:** `D:\QC_AI_Studio\Verify_Before_You_Teach_RevB.pdf` (VBT RevB). pp. 8-10 were read for the five MCP server names and the V2 rules, and p. 14 (Sec. VII-C, VII-D) for the arbitration rules and trigger X2 (M9, M24).
- **Fixed decisions:** E1-E15 (`BEP-2-12/00_meta/workflows/p5/p5_design.txt`). Every one is implemented. Each refinement is listed in section 1.

Sections 0-17 describe the behaviour the code has. They are authoritative and are kept current in place (P2-12-D-03). Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (unchanged from Phase 4 0.1, plus Phase 5's)

**Git and files**
- Stay on the branch. No branch switch, no `git stash`, no push, no history rewrite, no git-config change.
- Commit messages end with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only in the scratchpad. Nothing is written to the repository root. `git status --short` is checked after every script run.

**Forbidden reads and calls**
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local`, `apps/api/.env.example` or any `.env*` file. The `*.env.example.yaml` files may be read and edited. A recursive search over `infra/` passes `--exclude='*.env.yaml'`, or uses `git grep` (the real env files are untracked).
- No cloud, gcloud, gh, provider or LLM call. No deploy.
- No test makes a network call. The guard of 13.2 (`network_guard.py`) enforces this.

**Freeze (D-05, P1-D-18)**
- Nothing is deployed, and nothing learner-facing changes outside development.
- `MODEL_GATEWAY` is `off` outside development.
- Outside development, the learner-facing answer bodies of `POST /assistant/chat` (through `TutorOrchestrator.chat`, legacy guard included) and `POST /qa/ask` (through `QAEngine.ask`) equal Phase 4's for the same inputs (13.1 test 33, the 12.2 golden). `/ready` is an operations route, not a learner payload: it gains the 10.2 fields in every environment, because plan 7.7 says "/ready MUST report build SHA, corpus_version, threshold_set_version and gateway state [Evidence E-62]".
- D-31: zero assets are approved.
- D-19 containment and the R1.2 withholding are unchanged. `contained_answers.contain_answer` stays byte-for-byte.
- The Phase 4 legacy guard is unchanged.

**Privacy**
- No learner text, user id, email, response id, turn id, thread id or message id goes into a log line, a gateway payload, a V2 verdict, a cache key or a cache value. A cache key may hold a sha256 of the evidential envelope (plan 5.7 keys on the resolved question); the shared cache stores each key only as a keyed digest (an HMAC with the guest-token secret), and no key is logged or exported (4.15).
- Tests use uuid4 demo ids.
- No new source literal matches the cookie-name pattern of the privacy guard.

**Tests**
- No existing test or guard is weakened.
- No new skip or xfail.
- Each changed test keeps its intent, and its commit message says why.
- Each fix is mutation-checked: revert it, see the test fail, restore it byte for byte.
- One test module per feature. AC tests go in `test_phase5_acceptance.py`.
- No test reads outside the repository (`test_no_test_reads_outside_the_repository`): the plan quotes a doc test checks are literal strings in the test.
- A test that reads security events orders them by `seq` (`test_no_test_reads_one_security_event_without_an_order` and its sibling).

**Doc-text guards that Phase 5 text must pass.** These are the Phase 3 and 4 guards:
- `test_phase3_docs.py::test_k3_the_authoritative_text_states_the_current_code_only` (the NARRATIVE regex over every `apps/api/app/**/*.py`, `scripts/*.py`, the ADR revisions, the `## Phase 3`-onward runbook text and CI);
- `test_phase4_acceptance.py::test_phase4_spec_section_3_lists_the_code_s_fields`;
- `test_phase4_docs_*` (13.3 item 2 lists the ones Phase 5 changes, with their intent).

Phase 5 therefore:
- changes no field of a class that the Phase 4 spec's section 3 lists in full (it adds classes; see 3.3). `V1Passed` keeps its fields, so the V2 track computes what it needs itself (4.8);
- uses no phrase that the NARRATIVE regex names, and no review-round name in sections 0-17.

### 0.2 Measured facts (measured on the branch at `98f7cc4`, 2026-11-21)

**M1. Baseline.**
- SQLite: 1329 passed, 2 skipped, 1 deselected, 3 xfailed.
- PostgreSQL 17: 1331 passed, 1 deselected, 3 xfailed, under psycopg and under pg8000.
- Frontend: lint, typecheck and 154 integration tests pass.
- Main CI run 44971066403 was green on every job.

**M2. Legacy provider code.** On `98f7cc4`, `app/services/teaching_assistant.py` held a dead Vertex path (L86-278): `vertex_enabled`, `vertex_api_key` (which also read the `VERTEX_AI_API_KEY` environment variable) and `_google_auth_bundle` (`google.auth.default`, E-109); `vertex_project_id`, `_sanitize_history` and `_ask_vertex` (1024 tokens, httpx timeout 35 s, no retry cap: E-42, E-66); `_vertex_client`, `_vertex_endpoint` (`aiplatform.googleapis.com`), `_vertex_provider_label`, `_access_token`, `_vertex_headers`, `_format_context`, `_format_page_context` and `_extract_text`. `git grep` over `apps/api/app`, `apps/api/alembic`, `scripts`, `evaluation`, `tools`, `infra` and the Dockerfile showed no caller outside the file; only two Phase 1 tests of `test_api.py` (AC-1-8) called `_ask_vertex`. `TeachingAssistantService.chat` returns `provider="none"` (D-19 since Phase 1), and `/assistant/chat` reaches it through `TutorOrchestrator.chat`, which re-contains the candidate's citations and applies the legacy guard before the body is built. Phase 5 retires that code (4.18).

**M3. Provider settings.** `Settings` held `openai_api_key`, `openai_chat_model`, `openai_embedding_model`, `vertex_ai_api_key`, `vertex_ai_project_id`, `vertex_ai_location` and `vertex_ai_chat_model` (default `gemini-3.1-flash-lite-preview`, a preview id: R-24). `openai_chat_model` was read nowhere; `vertex_ai_*` only by `teaching_assistant.py` and the redaction installs in `main.py` and `workers/common.py`. `openai_api_key` and `openai_embedding_model` were live: `retrieval_engine.PineconeSemanticBackend` used them through `langchain_openai.OpenAIEmbeddings` (Phase 2 task 2.5; off by default, active only in a process that aligned span-id vectors), so the OpenAI key was a provider credential read outside any gateway (conflict 29; 4.19 moves the key and the embedding egress into the gateway). `qa_engine.py` holds no provider code (`QA_PROVIDER = "none"`, D-19); plan A's "OpenAI in qa_engine with no token, timeout or retry caps [Evidence E-66]" describes `1098a6ae`, not the tree. `pydantic-settings` with `extra="ignore"` ignores unknown init kwargs as well as environment keys. `test_deployment_artifacts.py::test_api_cloud_run_example_disables_demo_auth_and_documents_secret_injection` requires `OPENAI_API_KEY` and `PINECONE_API_KEY` in the env example.

**M4. Egress-capable imports.** In `apps/api/app`, `httpx` was imported only by `teaching_assistant.py` (now only by `app/gateway/adapters.py` and `app/gateway/embeddings.py`). `urllib.parse` is imported by `main.py` and `request_protection.py` (parsing only). `socket` is imported by `core/db.py` (TCP keepalive on the Cloud SQL socket), which also imports `google.cloud.sql.connector` (the database connector, not a model provider). `langchain_openai` and `pinecone` were imported only by `retrieval_engine.py` (now `pinecone` only; nothing in the API image imports `langchain_openai`); `langchain_text_splitters` (no network) by `retrieval_legacy_p1.py` and `spans.py`. In `scripts`, `urllib.request` is imported by `deployment_record.py` and `domain_monitor.py` for non-model egress, and `socket` by `domain_monitor.py`.

**M5. No test touches the network.** The full SQLite suite was run with a socket-probe pytest plugin kept in the scratchpad (never in the repository) that records every `socket.connect`/`connect_ex` to a non-loopback address and every `getaddrinfo` of a non-local name: 0 connects and 0 lookups. Subprocess start-up tests open no socket (SQLite files or the local PostgreSQL). `evaluation/tests` has no `conftest.py`, and the repository root has no pytest configuration.

**M6. Package v3.** Package 3.0.0, schema 3, sha256 `116504d45d14b1048eeed5ccba0a62f16c92ccdb9b72618bd4ca65b97813a153`. `tutor_pipeline.ledger.entry_schemas` is `[ledger-entry-v1, ledger-entry-v2]`; `unused_provenance_fields` is `[panel_weights_version, routing_table_version, tool_contract_version]`; `Q-22.provisional_values` is `[v1.v1_5.x4_margin, abstention, v1.v1_3.support_threshold, v1.v1_7, v1.v1_9.readability, v1.stop]` with `record` `PD-15, PD-16, PD-18; DI-52`; `flag_policy` holds `two_pass_tutor`, `v1_pipeline`, `phase4_exit_passed: false` and `phase4_exit_evidence: null`.

**M7. Ledger storage.** `response_ledger.entry_schema` is `VARCHAR(32)`, so `ledger-entry-v3` fits; the CHECK constraints name only `delivery` and `decision`; the `entry` column is text. The v3 record needs no migration (the gateway's shared controls add one, section 8).

**M8. Package checks dispatch on schema.** `tutor_pipeline/package_check.py` required `entry_schemas == sorted(ENTRY_SCHEMAS)` for schema 3 or later, so a v3 package would fail once `ENTRY_SCHEMAS` gained v3: the comparison is per schema (5.3).

**M9. The paper (VBT RevB pp. 8-10), summarised.** The tutor reaches tools through five MCP servers: corpus, citation, learner, verification and analytics; the learner server is visible only to the L3 planner and the pedagogical pass. V2 panel = M \ {g}, blind to the generator's identity and to each other's votes. Each verifier receives the locked claims, quoted: "the resolved text of each cited span and the resolved question"; the objective and the learner band go to the alignment item only. Per claim a verifier returns SUPPORTED, CONTRADICTED or NOT-ENOUGH-INFO, an EHMF type when not supported, the span relied on and a rationale; per response a 1-5 alignment rating and a leakage flag. NOT-ENOUGH-INFO counts against a claim. Tiers: tier 1 (novice learners, assessment items, module content) 1oo3; tier 2 (default tutor answers) 2oo3; tier 3 (expert mode, opt-in) a Dawid-Skene posterior above a threshold. Degraded modes: two verifiers vote 1oo2; a single verifier forces V3 for tier-1 content; with zero, claims are withheld and queued. Correction: a failed claim is revised against its span or deleted, then re-verified; after two failed cycles the tutor abstains on that claim and escalates when it is critical.

**M10. Objective and band sources.** `CourseStore.lessons: dict[str, LessonDetail]`, and `LessonDetail.summary` is authored curriculum text served on the lesson pages. The package's readability band is `v1.v1_9.readability` ([−4.0, 64.0], PD-16). No learner model exists before Phase 8. `TemplateRenderer` emits fixed template segments (integer parameters only) and locked claim texts; it never echoes the learner's question.

**M11. Test helpers.** The package-copy helpers use `DEFAULT_PACKAGE_PATH.name` (`v1_fakes.temp_package` and `test_v1_5_abstention.py` included since Phase 5). `v1_fakes.dev_pipeline(settings=None, **kwargs)` builds `Settings(model_gateway="off")` when no settings are given.

**M12. Tests that pinned the Phase 4 record or package** (13.3): `"3.0.0"` in `test_config_package.py` and `test_phase4_acceptance.py`; `ledger-entry-v2` in the Phase 4 mixed chain, the route turns, `test_response_ledger.py` and `test_v1_aggregate_and_runner.py`; `LedgerEntryV2.model_validate` on payloads built by `dev_pipeline(...)` with default settings; a `SupportedVoter` passed as `TwoPassPipeline(v2_hook=...)`. Each ran with development settings, where Phase 5's development default (`MODEL_GATEWAY=shadow`) changes the record.

**M13. Runbooks.** The runbooks are `infra/cloudrun/deployment.md`, `observability.md`, `retention-job.md`, `provider-key-rotation.md` and `FREEZE.md`. `api-production.env.example.yaml` sets no VERTEX variable.

**M14. Libraries.** `hypothesis` is not installed, so property tests enumerate or use a seeded `random.Random`. `httpx==0.28.1` (with `MockTransport`) is installed.

**M15. Generator.** The only wired generator is `extractive-d19-v1` (D-12 open, `WIRED_GENERATORS`). It has no model family, and it proposes deterministically. Claim ids are content-addressed (`bind.claim_id_for(text, span_ids)`), and binding is sentence-verbatim, so a claim can only be bound to a whole corpus sentence of its spans.

**M16. V1 run state.** `V1Track.run` keeps one `_RunState` per candidate; `accepted_results` selects a candidate's results by `attempt` number, and the attempt numbers restart at 1 in every `_decide` loop and every `render_checked` call. So every candidate and every rendering is judged with its own state (4.13).

**M17. The evidential envelope.** `EvidentialEnvelope` holds `question` (the resolved text), `corpus_version`, the lesson-scoped evidence spans and the instructions with the evidential prompt hash. The same resolved text under another lesson scope gives another envelope.

**M18. Record rules the V2 record meets.** `LedgerEntryV2._v1_rules`, in V1 enforce: "the record abstains exactly when V1 does" (`decision == "abstain"` iff `verification.final == "abstain"`), and the verdicts name the recorded claims in order. `VerificationRecord` refuses any `final_reason` outside `PHASE4_FINAL_REASONS`.

**M19. Phase 4 doc tests that read the shipped package** (`test_phase4_docs_the_phase3_spec_states_what_phase4_changed`, `test_phase4_docs_the_code_texts_name_the_shipped_package`, `test_phase4_docs_name_every_q_22_value_and_the_package_s_provisional_until`, `test_plan_i_ready_reports_package_v3_and_the_v1_fields_and_no_shadow_outcome`): 13.3 item 2 lists how each now names the shipped v4 or reads v3.

**M20. Corpus text and the identifier scan.** The development store's 331 span texts and the 12 lesson summaries hold no e-mail address, no uuid and no "Bearer" (measured 2026-11-21 with a scratch script outside the repository). Span texts are at most 700 characters.

**M21. pydantic is not pinned.** `requirements.txt` gives pydantic a floor and a major-version cap, so `model_json_schema` output may differ between minor versions: start-up compares committed schema files with their sha256 pins only, and the structural comparison runs in tests and `config_package.py --check`.

**M22. Plan text Phase 5 must meet beyond its own block.**
- 7.1: "RECOMMENDATION: only the gateway and review console deploy separately (distinct trust). The gateway MUST be the sole holder of provider credentials [Risk R-06]; the browser MUST NOT compute verdicts."
- 7.2: the tier rules "live in versioned ThresholdSet, PanelWeights and RoutingTable objects, not code constants".
- 7.7: "/ready MUST report build SHA, corpus_version, threshold_set_version and gateway state [Evidence E-62]."
- 13.2 required checks include "a test enumerating flag combinations against the 13.6 rule".
- 9.4 holds: H6 (D-12; "P3 interim path; P5 exit"; "Payload register"), H8 (D-07; "P5 exit; P9; P10"; "Pinned registry"), H9 (A-15; "P5 panel; P11 storage"; "Approved budget"), H14 (D-21; "P5 exit [Risk R-48]"; "Zero-member policy"), H15 (D-20; "P4 V1.3 enforcement"; "Interim policy"). "a hold stops the named work until its release evidence is filed".
- Phase 5 B preconditions: "Phase 4 exit; [Decision D-07][Decision D-12]; provider terms (Q-09) [Assumption A-11]; budgets [Assumption A-15]; local-model hosting [Decision D-21]."

**M23. The Phase 3 flag-combination test** (`test_ac_3_6_flag_combinations_never_deliver_two_pass_output`) enumerates ENVIRONMENT × TWO_PASS_TUTOR × TUTOR_LEDGER_ENABLED × EVIDENCE_PANEL_ENABLED × LEDGER_ROUTE_ENABLED; test 41 enumerates the Phase 5 switches.

**M24. VBT RevB p. 14 (Sec. VII-C, VII-D), summarised.** Seven arbitration rules apply in order: (1) a deterministic V1 failure is final; (2) the tier's voting rule decides each claim; (3) NOT-ENOUGH-INFO counts against a claim; (4) verifiers of one provider family count as one vote; (5) Dawid-Skene weights replace equal weights in tier 3 once enough gold claims exist; (6) learner feedback never overrides a factual verdict; (7) anything still unresolved is withheld and escalated. Trigger X2: a Type A or B objection still unresolved after two correction cycles; the claim is withheld and queued.

### 0.3 Readings

**R-a. "Deliver" in Phase 5.** No two-pass text reaches a learner. `TWO_PASS_DELIVERY_IMPLEMENTED` stays `False`, and every V2 record is a shadow record. `final: deliver` is the shadow verdict that a delivered path would act on (DI-59, DI-85). Learners still receive the D-19 contained answer.

**R-b. "A provider down".** An adapter is *ineligible* for a response when any of these holds at the response's start: the gateway is stopped (this instance's stop, or the registry's shared stop that it adopts, 4.5); `MODEL_GATEWAY_KILL_SWITCH` is not `none`; the adapter is in `MODEL_GATEWAY_DISABLED_ADAPTERS`; its provider is not opted in (non-fake only); the daily budget is 0, or the remaining daily budget is below one call's cost, or the budget's store cannot be read (`budget_unavailable`); the adapter reports itself down (`available()` false). A panel member becomes *unavailable* during the response when a call is refused by the gateway (a budget store that cannot be written included), fails after its retries, times out, or returns output that fails its contract. An unavailable member leaves the panel for the rest of the response. The panel shrinks and the rule tightens (M9). A fault of a shared store (the budget, the stop or the cache) never escapes the gateway or the V2 track, so every response keeps its record (F-1; 4.4, 4.5, 4.15).

**R-c. "Objection".** A family's claim-level verdict that is not `SUPPORTED`. `NOT_ENOUGH_INFO` objects (AC-5-4, arbitration rule 3).

**R-d. "One vote per family" (rule 4, AC-5-2).** Per claim, each member family contributes exactly one family verdict to the tally, whatever number of adapters the family has in the registry: the first eligible one in registry order is used, and the others are never called. Pair votes (one per member and cited span) are recorded, because plan 7.4 gives each vote a `span_id`, and are folded into the family verdict by 4.9 rule F. "Distinct families = votes" (invariant 4) counts family verdicts.

**R-e. "Critical".** A claim matched by D-25's critical-claim registry. D-25 is OPEN. Outside development the registry is empty, so no claim is critical there; development holds Phase 6's synthetic registry (Phase 6 spec PD-33). The X1 trigger and the sticky hold of a critical tier-1 claim are Phase 6's.

**R-f. "Pre-verified module content (stage 4)".** No store of pre-verified module content exists. The zero-member path is therefore "abstain and queue" (4.10). The record names what the learner received (D-20's replacement values). See DI-83.

**R-g. F-1 "ledger verdicts for 100% of test responses".** Plan 7.4's F-1 over *delivered* responses waits for a delivered two-pass path (DI-36, DI-59). F-1 here is measured by `scripts/run_v2_fixtures.py` over the public-corpus fixture queries at four outage levels (12.1): every response's ledger record verifies in a chain and carries a verification verdict for every claim; every V2-eligible claim of the final V1-passed candidate carries a V2 verdict; no V2 verdict follows a V1 hard fail or abstention.

**R-h. Modes.**

| `MODEL_GATEWAY` effective | What runs | Record |
|---|---|---|
| `off` | Phase 4 exactly (V1 per `V1_PIPELINE`; D-20 interim) | `ledger-entry-v2` (or v1 when V1 is off) |
| `shadow` | Phase 4 decides every final. The V2 panel votes once on each V1-passed candidate's eligible claims, and one alignment item judges V1's accepted rendering (no correction); its verdicts and `would_*` summary are recorded beside the V1 finals (plan G "shadow dual-run") | `ledger-entry-v3`, `verification.v2.mode = "shadow"` |
| `on` | V1 track (enforce), then V2 decides each eligible claim (V1.3 flags route to V2), with correction cycles, the final rendering, the alignment item and degraded modes | `ledger-entry-v3`, `verification.v2.mode = "on"` |

The effective mode is `off` whenever the two-pass shadow itself is off (`tutor_shadow.effective_mode == "off"`, the default outside development), and after a runtime stop (4.5).

---

## 1. Conflicts between plan text and the fixed decisions, with resolutions

Each resolution is a refinement. None reverses a fixed decision without quoted plan text.

1. **Where the gateway runs.** Plan 7.1: "RECOMMENDATION: only the gateway and review console deploy separately (distinct trust). The gateway MUST be the sole holder of provider credentials [Risk R-06]". E1: an in-API package. **Resolution:** plan Phase 5 E allows "Gateway and verification modules (in-API service or sidecar)". `apps/api/app/gateway/` is the only package that may read a model-provider credential through the SecretStore or make model egress, the embedding key and egress of the Phase 2 semantic backend included (4.19). The AST guard (`test_gateway_egress_guard.py`) and the SecretStore (4.3) enforce this; the guard's one allow-list entry is the vector index client (conflict 10). Separate deployment is DI-78.
2. **"Shared cache" against a per-process cache.** Plan 5.7: "Shared cache holds evidential outputs only"; 7.5: "Caches | per-process rate limiter | shared verdict cache and rate-limit store". E6: "Per-process cache with bounded size unless a shared store already exists". **Resolution:** the application database is the store every instance already shares (the rate-limit counters, P1-D-06), so `EvidentialCache` has two implementations: `DatabaseEvidentialCache`, the process cache, over a table of its own (`evidential_cache_entries`, section 8), bounded per kind, its keys stored as keyed digests; and `ProcessEvidentialCache` (bounded, per process), a test's or the fixture runner's own cache. Cross-instance invalidation is by key: a configuration bump or a model change changes the key, and stale entries leave by the bound. Plan G's "cold cache" holds: the table starts empty with its migration (4.15).
3. **Two cache keys.** 5.7 keys on "(resolved question, corpus_version, configuration version, generator id, model version)"; 7.3: "verification keys on hash(claim_text, span_id, verifier_model_id, verifier_prompt_hash), also the V2 cache key [VBT RevB: p. 11, Sec. V-E]". **Resolution:** a verdict entry's key is the union of both (4.15). A claim-plan entry's key holds 5.7's fields, with the resolved question taken as the sha256 of the whole evidential envelope (M17), so a plan is never reused for another lesson scope's bundle. Only a wired generator's plans are cached: its plan is a function of its ref and the envelope (`cache.plan_cacheable`).
4. **What a verifier sees.** The paper gives each verifier "the resolved text of each cited span and the resolved question" (M9); AC-5-3 says no verifier prompt contains "learner text or history"; plan H: "Only public-corpus spans leave the platform". **Resolution:** E5. A claim item carries the claim text, one bound span's id and resolved text, and the fixed instructions. It never carries the resolved question (learner text), other claims, the generator's identity or another member's vote.
5. **The alignment item's band.** The paper sends "the learning objective and learner band" to the alignment item; Phase 5 has no learner model, and plan H and invariant 1 apply. **Resolution:** the objective is the lesson's `summary` (authored, public curriculum text; null without a lesson), and the band is the package's V1.9 readability band. No learner state is sent. The learner band waits for Phase 8 and a Q-15 payload review (DI-82).
6. **X2 marking, and deletion.** 5.8: "Correction: two cycles, then abstain and mark X2 when critical"; AC-5-7: "Given a claim failing two cycles, then it is abstained and marked X2."; 7.2: "--fail--> correct, re-verify, <= 2 cycles, else abstain + enqueue V3 (X2)". The paper revises a failed claim "or deletes" it (M9), and its X2 names Type A or B objections (M24). **Resolution:** every claim that fails two cycles is abstained and carries a V3 intent with escalation `X2`, whatever its EHMF type (stricter: arbitration rule 7). `critical` is recorded, false while D-25's registry is empty (PD-29). No claim is deleted by the track: plan 5.8 and AC-5-7 name no deletion. A claim the generator cannot revise (the extractive generator: a verbatim quotation) is re-verified unchanged; its pairs are cache hits, so the two cycles cost no call, and it ends abstained with X2. A revision that V1.2 cannot bind is dropped by V1 (a claim-scoped drop of the new candidate).
7. **Tier 3.** 5.6: "tier 3 equal weights"; the paper uses a reliability-weighted Dawid-Skene posterior, and DS weights are a Phase 5 non-goal (rule 5); the tier-3 threshold is Q-22, unresolved. **Resolution:** rule `equal-weights-share-v1`: pass iff `den·supports ≥ num·N`, with a provisional 2/3 (`v2.voting.tier3_threshold`, `provisional_until "Q-22 (DI-52)"`). At N=3 that equals 2oo3. No shipped claim is tier 3: tier 3 is the paper's opt-in expert mode, which does not exist (PD-25).
8. **Tier assignment.** The paper puts novice learners in tier 1, which is learner state; invariant 1: "Learner state never shapes evidence, citations or abstention". **Resolution:** rule `context-tier-v1`: tier 1 when the turn is an assessment context (V1.6's `assessment_items` over the resolved text is non-empty), otherwise tier 2; tier 3 only under an expert mode, of which there is none. Novice-learner tiering waits for Phase 8 (DI-82).
9. **E3 "the OpenAI path/settings in qa_engine.py/config.py".** The tree had no OpenAI path in `qa_engine.py` (M3), and two OpenAI settings are live for the Phase 2 semantic backend. **Resolution:** retire `openai_chat_model` (dead) and every `vertex_ai_*` setting (4.18); move the embedding model, its pinned version, caps and cost into package v4 (`gateway.embeddings`, PD-26), so `openai_embedding_model` is no setting either; and move the key out of the settings: the gateway's SecretStore reads `OPENAI_API_KEY` (4.19).
10. **E1 "the ONLY module allowed to make model egress" against Phase 2's embedding backend.** **Resolution:** the backend embeds only through the gateway (`app/gateway/embeddings.py`, 4.19), and nothing in the API image imports `langchain_openai`. The AST guard's import rule covers the API image (`apps/api/app`) and has exactly one allow-list entry: `app/services/retrieval_engine.py` importing `pinecone`, the vector index client (plan 7.5 "Vector index"), which is reached only with an embedder the gateway gives. Its host-string rule covers the Python files under `apps/api/app`, `scripts`, `evaluation` (its tests included) and `tools`. The two scripts that import `urllib.request` for non-model egress (M4) are outside the import rule and covered by the host-string rule. The gateway gives no provider embedder: 4.19's checks start with the D-23 opt-in and end with plan H's bar on the learner's query text (strictly more conservative; production runs `SEMANTIC_RETRIEVAL_ENABLED=false`, PD-06).
11. **Plan 13.6** says: "No flag, kill switch, setting or governance override MAY disable V1 or deliver text whose verification has not completed; disabling V2 or a provider forces abstain-only or pre-verified content". **Resolution:** `MODEL_GATEWAY=off` never touches V1 (Phase 4's refusals stand). With V2 off or in shadow, D-20's interim policy withholds every V1.3-flagged claim (abstain-only or the D-19 replacement). The kill switches (`abstain_only`, `pre_verified_only`) make every adapter ineligible, so the ZERO path runs without a gateway call, and under `on` the record abstains (abstain-only; pre-verified-only too while no pre-verified source exists, DI-83; 4.10). Test 41 enumerates the flag combinations against this rule (plan 13.2).
12. **D-29 is an OPEN DECISION.** Its text: "Until decided, (a)". **Resolution:** the "until decided" rule. REDUCED-1 withholds and queues tiers 1 and 2, and tier 3 follows its rule on the remaining verifier (PD-23).
13. **D-07 and D-12.** 18.3: "D-07 |Pin gateway models (PI, PO) |(a) Table XIV rule, pinned |Preview default [Risk R-24]" and "D-12 |Provider and terms (PO, counsel) |(a) one pinned provider |Phase 5 blocked [Risk R-09]"; Q-09 ("Provider terms in force?") is a factual question. **Resolution:** option (a)'s *rule* for D-07 is applied: every registry identifier must be pinned (PD-24). No model is chosen (choosing one needs D-12's provider and Q-09's terms, owner and counsel facts), so the staging, production and default registries are empty. "D-07 closed" (plan P) stays unmet (DI-69), and so do D-12 and Q-09 (DI-70).
14. **Plan G "One release of shadow dual-run, then flag cutover"** against the freeze. **Resolution:** the dual-run is development-only (no release under D-05). `on` is refused outside development while `flag_policy.phase5_exit_passed` is false. `MODEL_GATEWAY=shadow` outside development is a configuration override (it logs `config.override`), and it can make no call: every non-development registry is empty and its budget 0. The cutover is DI-85.
15. **AC-5-6 "pre-verified content or abstention".** **Resolution:** R-f. `v2.degraded.pre_verified_source` is `null`, so the ZERO path withholds and queues, labelled `degraded` with the ZERO banner; the record's `replacement` follows Phase 4's D-20 values (`extractive_d19`, `abstention` or `unknown`, the D-19 answer the learner received). See DI-83.
16. **`final: correct`** (plan 7.4 enum). **Resolution:** as Phase 4 R-d. A correction is a new candidate that every V1 check judges from the start, and the record holds the final candidate. `correct` is refused on every record. Corrections are counted in `verification.v2.cycles` and listed in `v2.corrections`.
17. **Plan 7.4 vote fields** `{verifier_model_id, family, verifier_prompt_hash, verdict, ehmf_type, span_id}`; E10 adds the model version. **Resolution:** a superset with `verifier_model_version` and `cached`. The plan's fields keep their names.
18. **Tool names.** Plan 7.4: "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]"; the paper names the five servers but not their tools. **Resolution:** the server names are the paper's; the tool names are this phase's own, versioned `mcp-tools-v1` and provisional. Transport is in-process ("transport is an implementation choice", 5.2).
19. **The paper sends "the locked claim list" to each verifier.** E5 sends one claim per item. **Resolution:** E5 (blinder and smaller; Q-15). AC-5-3 does not require the list.
20. **Plan I "alert at 80% of budget"** against no cloud write. **Resolution:** the gateway logs `gateway.budget_alert` once per UTC day at 80% (4/5). The alert policy is DI-80.
21. **E2 "ONE real-provider adapter class as code only if it is needed".** **Resolution:** it is needed: AC-5-9 "Given a provider error, then logs hold no key" and 5.12 "Keys in headers from the secret store; error redaction" need an HTTP error path, and fakes hold no key. `HttpJsonAdapter` is provider-neutral and exercised only through `httpx.MockTransport`; the loader refuses any registry member whose provider is not `fake` while D-12, D-07 or Q-09 is open or the Q-15 payload review is pending.
22. **Phase 4's rule** "no deliver verdict with a V1 result other than pass or mark". Plan Phase 4 D: "V1.3 flags go to V2 after Phase 5, else the interim policy [Decision D-20]". **Resolution:** `VerificationRecordV2` in mode `on` accepts a deliver verdict whose only non-pass V1 results are V1.3 `flag`s, and only when its V2 verdict passed. Phase 4's `VerificationRecord` keeps its rule unchanged; the shared rule body is factored (3.3).
23. **Phase 4 conflict 30** ("Phase 5 adds V2 cycles as a separate field"). **Resolution:** `verification.v2.cycles` (0-2). The V1 `cycle_count` keeps its meaning.
24. **E9 sets `shadow` as the development default**, and Phase 4 tests pin the Phase 4 record shape (M12). **Resolution:** `v1_fakes.dev_pipeline()` builds `Settings(model_gateway="off")` when no settings are given, and pipeline-level Phase 4 tests that pass their own settings and pin the V1 record add `model_gateway="off"`: their subject is V1, and plan L's "Flag off returns to Phase 4" makes that path Phase 4's exactly. An explicit `v2_hook` passed to `TwoPassPipeline` (the Phase 4 seam) takes precedence over the V2 track, and with it the effective V2 mode is `off` for that pipeline. Route-level tests expect `ledger-entry-v3` and keep every other assertion (13.3).
25. **Plan L "Flag off returns to Phase 4. Stop on a payload violation, secret in logs or budget breach."** and E9's "runtime guards that switch the gateway to off and log a security event". **Resolution:** three runtime guards stop the gateway. Every later call is refused, the event `gateway.stopped` is logged, and a security event is written. The response in flight finishes with its remaining members unavailable (ZERO for the rest of it). From the next response on, the effective mode is `off`, so later records are Phase 4's. The stop is written to the registry's shared stop, which every other instance and every new process adopts; the stored stop lasts until an operator clears it, and an instance that stopped refuses every call until it is replaced (4.5).
26. **Hold H9 (A-15) blocks the "P5 panel"** until its release evidence ("Approved budget") is filed (M22). **Resolution:** the panel's code is built, but a panel that spends money never runs: every non-development budget is 0 (PD-26), every non-development registry is empty, and the development panel runs only cost-free fakes that make no network call. H9's release is DI-72.
27. **Preconditions (plan Phase 5 B).** The Phase 4 exit is not passed (DI-58); D-07 and D-12 are open; Q-09 is unresolved and A-11 ("No negotiated provider agreements") holds; A-15 is open; D-21 is open (H14). **Resolution:** proceed under P1-D-18 on the unresolved paths: no provider, no model, budgets 0 outside development, production permanently ZERO (DI-69, DI-70, DI-72, DI-73, DI-74).
28. **Arbitration rules "2-4, 7" (plan A, p. 14).** **Resolution:** rule 2 is the routing table and `voting.tally`; rule 3 is NOT_ENOUGH_INFO as an objection; rule 4 is one family verdict per family; rule 7 is the `withheld` outcome with a V3 queue intent (REDUCED-1 tiers 1-2, ZERO, kill switch) and X2 after two cycles. Rule 1 is Phase 4's typed decision (AC-5-5). Rule 5 is a non-goal; rule 6 has no input in Phase 5.
29. **Plan 7.1 "The gateway MUST be the sole holder of provider credentials"** against the semantic backend's `OPENAI_API_KEY` (M3). **Resolution:** the key is no setting: the gateway's SecretStore reads `OPENAI_API_KEY` per call (4.3), and `app/gateway/embeddings.py` holds the embedding egress (4.19). The gateway names why it gives the semantic backend no embedder: the environment's opt-in (D-23), D-07, D-12, Q-09 and the Q-15 review (`registry.providers_open`, the loader's rule for every non-fake member), a pinned model in `gateway.embeddings`, the registry's budget, an open gateway, the key, and last plan H's bar on the learner's query text (conflict 36), so no embedder is given anywhere.
30. **Plan H "Only public-corpus spans leave the platform"** against the alignment item, which carries a rendering and the lesson summary. **Resolution:** the alignment item carries no learner text: every claim segment is a locked claim on public, quotable spans, and every other segment is a renderer template output (the payload policy checks both, 4.5). The lesson summary is authored public curriculum text. The payload register names each field (Q-15), and its owner review (DI-71) precedes any non-fake adapter.
31. **Plan 7.2 "not code constants"** against the rule matrix. **Resolution:** the matrix is configuration (v4 `v2.voting.matrix`, versioned by `routing_table_version`), and the track reads it from the package. The code holds `ROUTING_TABLES = {"degraded-matrix-v1": RULE_MATRIX}`, the tables a record may name; the loader requires the package's matrix to equal the table its `routing_table_version` names, and while D-29 is open only `degraded-matrix-v1` is accepted.
32. **E12 "an autouse guard fails a test that opens a socket other than the local test database".** **Resolution:** the guard refuses every non-loopback connect and every lookup of a non-local name and allows loopback (Windows `socket.socketpair`, asyncio's self-pipe and the test PostgreSQL use 127.0.0.1). A refused attempt is recorded, and an autouse fixture fails the test that made it even when the code under test caught the refusal.
33. **E13 "property test over every registry ordering".** **Resolution:** AC-5-1's test enumerates every ordered registry of 1 to 5 adapters over 4 families (1364 registries) with every eligibility subset of its first three adapters, for every generator family (the 4 and one outside them), exhaustively.
34. **The alignment item and delivery.** The paper's alignment item judges the response. **Resolution:** under `on` a response delivers only when its final rendering's alignment item passed; when no member is left to judge it, the would-be-delivered claims are withheld and queued (`v2_degraded_withheld`), the fail-safe default of rule 7.
35. **Plan 5.10 "daily budget hard stop" and plan L's stops with several instances.** A budget or a stop held in one process lets N instances spend N budgets, and a stop ends with its instance. **Resolution:** the process gateway's budget is `DatabaseBudget` (one row per registry and UTC day, reserved by one atomic UPDATE, 4.4) and its stop is the registry's `DatabaseStopStore`, adopted by every instance and every new process; the stored stop lasts until an operator clears it, and a stopped instance until it is replaced (4.5). Every attempt an adapter sends is reserved, retries included (4.4).
36. **The semantic backend's query embedding against plan H and the payload register.** A query embedding sends the learner's query text to the provider; plan H says "Only public-corpus spans leave the platform", and the register's "Never sent" list excludes the learner's text from the V2 items. **Resolution:** plan H decides, whatever the owner decisions: `PayloadPolicy.check_embedding` refuses every query item (`learner_text`) and admits a document item only as the excerpt of a public, quotable index entry, and `embedding_problem`'s last check is `learner_text`, so the gateway gives the semantic backend, which embeds every query, no embedder (4.19). The payload register lists the embedding item and marks the query text as never sent.

---

## 2. Architecture

```
learner turn ──► TutorOrchestrator.chat / QAEngine.ask  (unchanged: D-19 contain_answer ─► legacy guard ─► learner)
   └─ ShadowJob ─► background TwoPassPipeline.run (shadow only; TWO_PASS_TUTOR off outside development)
        retrieve ─► V1.5 ─► envelope
        V1 track (Phase 4): propose [shared claim-plan cache: generation 1, wired generator only; key = envelope sha256 + 5.7 fields]
                            ─► V1.9 ─► V1.1 ─► V1.2 ─► lock ─► V1.3 ─► V1.7 ─► V1.8
                            ─► render loop (V1.9 env, V1.4, V1.6, V1.9 band)
        V1HardFail | V1Abstained ──────────────► record (no V2 call: AC-5-5, invariant 3)
        V1Passed ─► v2_outcome(hook) ─► V2Track.consult(passed)        [only when the V2 mode is not off]
              eligible = gateway.eligible(registry.verifiers())   (stopped, kill switch, disabled, opt-in, budget, budget store, available())
              Panel.build(eligible, generator_family)               (families − family(g), first eligible adapter per family, ≤ 3)
              tier per response (context-tier-v1) ; per claim: mode = mode_for(|members|) ; rule = package matrix[mode][tier]
              per claim × member × span: verdict cache ─► ToolHost("verifier","verification.verdict") ─► ModelGateway.verify
                     ModelGateway: shared stop ─► secret flag ─► stopped? ─► payload policy ─► budget (shared; each retry too) ─► capture ─► adapter (Fake | HttpJsonAdapter)
              family verdicts ─► tally ─► pass | fail | withheld
        on:     failing claims ─► correction cycle: objections all type E ─► re-render only (same candidate, fresh hook);
                otherwise revise via ClaimReviser, or unchanged ─► new candidate through V1 when the plan changed, fresh V1
                state; re-verify (unchanged pairs hit the cache) ─► ≤ 2 cycles ─► else abstain + X2
                ─► final rendering of the deliverable claims (fresh post-render hook)
                ─► alignment item (1ooN leakage) ─► Type E: re-render only (shares the ≤ 2 cycles) ─► else abstain + X2
                ─► VerificationRecordV2 ─► LedgerEntryV3 (decision follows the V2 final)
        shadow: one vote per eligible claim and one alignment item on V1's accepted rendering; no correction; Phase 4 finals kept;
                V2 verdicts + would_* summary ─► LedgerEntryV3
```

**Arbitration rules (VBT RevB p. 14; plan A "rules 2-4, 7")**

| Rule | Mechanism |
|---|---|
| 1 V1 failure final | Phase 4 typed decision; `v2_outcome` reaches a hook only with a `V1Passed`; record rule (invariant 3) |
| 2 tier rule decides | `voting.tally` with the package matrix (`degraded-matrix-v1`) |
| 3 NEI counts against | `voting.objections` |
| 4 one vote per family | `Panel.build`; 4.9 rule F; record rule on `(family, span_id)` |
| 5 DS weights | non-goal (`equal-weights-v1`) |
| 6 learner feedback | no input in Phase 5 |
| 7 unresolved withheld and escalated | `withhold-queue-v3` with `v2_degraded_withheld`; X2 after two cycles |

**Where each AC is enforced**

| AC | Mechanism | Primary tests (13.1) |
|---|---|---|
| AC-5-1 | `Panel.build` cannot return a member of `generator_family`; `Panel.__post_init__`, `V2ClaimVerdict` and `VerificationRecordV2` refuse it; an unknown generator family leaves the panel empty (fail closed) | 1, 2 |
| AC-5-2 | `Panel.build` keeps one adapter per family; the tally takes one family verdict; the record refuses two votes of one family on one span | 3 |
| AC-5-3 | `VerdictRequest`/`AlignmentRequest` are closed contracts; `ModelGateway.capture`; payload policy | 4, 5, 6 |
| AC-5-4 | `voting.tally` and the routing table; NEI is an objection | 7; `test_v2_voting.py` |
| AC-5-5 | Phase 4 typed decision: `v2_outcome` reaches the hook only with a `V1Passed` | 8 |
| AC-5-6 | eligibility, `mode_for`, the degraded matrix (D-29 (a)), queue intents, label and banner; a shared store's fault fails closed | 9 |
| AC-5-7 | `V1Track` correction loop, `MAX_CORRECTION_CYCLES` 2, X2 | 10, 11 |
| AC-5-8 | `ProcessEvidentialCache` union key includes `config_package_sha256` | 12 |
| AC-5-9 | `HttpJsonAdapter` (headers only; raised with no context), log redaction, `DailyBudget` and `DatabaseBudget` (every attempt reserved) | 13, 14 |
| AC-5-10 | `pin_problem` in the loader (every registry member and `gateway.embeddings`) at start-up | 15 |
| AC-5-11 | Cache values typed `ClaimPlan`/`AdapterVerdict` only; keys include the model version and the envelope hash | 16 |

---

## 3. Data shapes

The Python blocks of this section are valid Python (methods have `...` bodies), so the section-3 doc test (13.1 test 40) parses them and compares each class's fields with the code.

### 3.1 Gateway contracts (`apps/api/app/gateway/contracts.py`; `Contract` is `tutor_pipeline.contracts.Contract`, frozen, `extra="forbid"`)

```python
V2_VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
V2Verdict = Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
EHMF_TYPES = ("A", "B", "C", "D", "E")


class VerdictSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    text: str = Field(min_length=1, max_length=20000)


class VerdictInstructions(Contract):
    prompt_id: Literal["blind-claim-span-v1"] = "blind-claim-span-v1"
    prompt_hash: str = Field(pattern=HEX64)
    verdicts: tuple[V2Verdict, ...] = V2_VERDICTS
    ehmf_types: tuple[EhmfType, ...] = EHMF_TYPES
    tool_contract_version: str


class VerdictRequest(Contract):           # the claim item: claim + one bound span + fixed instructions only (E5)
    request_schema: Literal["v2-verdict-request-v1"] = "v2-verdict-request-v1"
    item: Literal["claim"] = "claim"
    claim_text: str = Field(min_length=1, max_length=2000)
    span: VerdictSpan
    instructions: VerdictInstructions


class ReadabilityBand(Contract):
    min_grade: float
    max_grade: float


class AlignmentInstructions(Contract):
    prompt_id: Literal["alignment-item-v1"] = "alignment-item-v1"
    prompt_hash: str = Field(pattern=HEX64)
    ratings: tuple[int, ...] = (1, 2, 3, 4, 5)
    tool_contract_version: str


class AlignmentRequest(Contract):         # the alignment item: the only payload holding objective and band (AC-5-3)
    request_schema: Literal["v2-alignment-request-v1"] = "v2-alignment-request-v1"
    item: Literal["alignment"] = "alignment"
    rendered_text: str = Field(min_length=1, max_length=20000)
    objective: str | None = Field(default=None, max_length=4000)
    band: ReadabilityBand
    instructions: AlignmentInstructions


class AdapterVerdict(Contract):           # an adapter's output is projected onto these keys before validation
    verdict: V2Verdict
    ehmf_type: EhmfType | None            # None iff verdict == "SUPPORTED"
    span_id: str = Field(pattern=SPAN_ID) # must equal the request's span id


class AlignmentVerdict(Contract):
    rating: int = Field(ge=1, le=5)
    leakage: bool
```

These rules are model validators: `AdapterVerdict`: `(ehmf_type is None) == (verdict == "SUPPORTED")`; `VerdictRequest`: the claim text holds no learner identifier pattern (4.5). The gateway keeps only `verdict`, `ehmf_type` and `span_id` (or `rating` and `leakage`) of an adapter's output before validating it (`project_verdict`, `project_alignment`). Any other key, a rationale included, is dropped and never recorded or logged. A missing key, a wrong type or a span id other than the request's is `AdapterError(kind="invalid_output")`. The same module holds the tool servers' small contracts (4.6) and registers the four request and verdict models in `SCHEMA_MODELS`.

**Adapter description** (`gateway/registry.py`; frozen dataclasses, not ledger contracts):

```python
Capability = Literal["generate", "verify"]


@dataclass(frozen=True)
class Caps:
    max_tokens: int        # 1..4096
    timeout_ms: int        # 50..10000; timeout_ms * (1 + max_retries) <= tutor_pipeline.budgets.shadow_ms
    max_retries: int       # 0..2


@dataclass(frozen=True)
class AdapterSpec:         # E1 ModelAdapter {adapter_id, family, provider, model_id, model_version, capabilities, caps}
    adapter_id: str        # [a-z0-9][a-z0-9-]{1,63}
    family: str            # [a-z0-9][a-z0-9-]{1,63}
    provider: str          # "fake" for the development fakes
    model_id: str
    model_version: str     # pinned (4.1)
    capabilities: tuple[Capability, ...]
    caps: Caps
    cost_units_per_call: int          # >= 0; fake units in development
    fake_rule: str | None = None      # e.g. "verbatim-support-v1"; set iff provider == "fake"
    endpoint: str | None = None       # HttpJsonAdapter only: https, no query, no userinfo, no fragment
    auth_header: str | None = None    # "authorization-bearer" | "x-api-key"
    secret_ref: str | None = None     # an environment variable name (Secret Manager mounts); never a value

    def public(self) -> dict: ...                         # what /ready reports: identifiers only


@dataclass(frozen=True)
class EmbeddingCaps:
    max_items: int         # inputs per request (one batch), 1..2048
    max_input_chars: int   # characters per input, 1..32000: the token cap (the gateway holds no tokenizer)
    timeout_ms: int        # 50..10000
    max_retries: int       # 0..2


@dataclass(frozen=True)
class EmbeddingSpec:       # package v4 gateway.embeddings (PD-26; 4.19)
    provider: str          # "openai-embeddings"
    secret_ref: str        # "OPENAI_API_KEY"
    model_id: str | None   # null while no embedding model is chosen (D-07 open)
    model_version: str | None
    caps: EmbeddingCaps
    cost_units_per_item: int   # >= 1; each attempt reserves len(inputs) * cost_units_per_item

    def public(self) -> dict: ...                         # what /ready reports: provider, model id and version


@dataclass(frozen=True)
class AdapterRegistry:
    name: str                          # "development" | "staging" | "production" | "default"
    members: tuple[AdapterSpec, ...]   # registry order

    def families(self) -> tuple[str, ...]: ...           # in first-appearance order

    def verifiers(self) -> tuple[AdapterSpec, ...]: ...  # capability "verify", registry order
```

E1 names the cap `timeout_s`; the spec holds milliseconds (`timeout_ms`), as every other Phase 3-4 budget does.

### 3.2 V2 vocabulary (`apps/api/app/services/v2_panel/rules.py` and `voting.py`; standard library only, so `contracts.py` may import them)

```python
DEGRADED_MODES = ("FULL", "REDUCED-2", "REDUCED-1", "ZERO")
TIERS = (1, 2, 3)
TIER_RULES = ("1oo3", "2oo3", "1oo2", "equal-weights-share-v1", "withhold-queue-v3")
RULE_MATRIX = {                                   # plan 5.6, 5.9, 7.7; D-29 (a) (PD-23)
    "FULL":      {1: "1oo3", 2: "2oo3", 3: "equal-weights-share-v1"},
    "REDUCED-2": {1: "1oo2", 2: "1oo2", 3: "1oo2"},
    "REDUCED-1": {1: "withhold-queue-v3", 2: "withhold-queue-v3", 3: "equal-weights-share-v1"},
    "ZERO":      {1: "withhold-queue-v3", 2: "withhold-queue-v3", 3: "withhold-queue-v3"},
}
ROUTING_TABLE_VERSION = "degraded-matrix-v1"
ROUTING_TABLES = {ROUTING_TABLE_VERSION: RULE_MATRIX}   # the tables a record may name (conflict 31)
MAX_MEMBERS = 3                                   # E-81 "M-out-of-N, N = 3"
MAX_CORRECTION_CYCLES = 2                         # plan 5.8 "two cycles"
PANEL_WEIGHTS_VERSION = "equal-weights-v1"        # rule 5: Dawid-Skene weights are a non-goal
TIER_RULE_ID = "context-tier-v1"
ALIGNMENT_RULE_ID = "1ooN-leakage-v1"
FAMILY_FOLD_RULE = "worst-pair-v1"
VERIFIER_PROMPT_ID, ALIGNMENT_PROMPT_ID = "blind-claim-span-v1", "alignment-item-v1"
VERIFIER_INSTRUCTIONS: str        # fixed text (4.7); names no model, family, generator or learner
ALIGNMENT_INSTRUCTIONS: str
V2_ABSTENTION_REASONS = ("v2_correction_exhausted", "v2_alignment_failed", "v2_kill_switch")   # a kill switch abstains (4.10)
V2_WITHHOLD_REASONS = ("v2_degraded_withheld",)
BANNER_IDS = ("degraded-reduced-2-v1", "degraded-reduced-1-v1", "degraded-zero-v1")


def verifier_prompt_hash() -> str: ...   # canonical sha256 of {id, instructions, request_schema, verdicts, ehmf_types}


def alignment_prompt_hash() -> str: ...
```

`voting.py` holds pure functions (4.9): `family_verdict(pairs) -> (verdict, ehmf_type)`, `objections(verdicts) -> int`, `tally(rule, family_verdicts, *, threshold=(2, 3)) -> "pass" | "fail" | "withheld"`, `mode_for(n_eligible) -> str`, `rule_for(table, mode, tier) -> str` and `is_split(family_verdicts) -> bool`.

### 3.3 Ledger contracts (`tutor_pipeline/contracts.py`, section "V2 (Phase 5)"; Phase 4 classes keep their fields)

```python
class V2Vote(Contract):                       # plan 7.4 votes[] plus model version and cache flag
    verifier_model_id: str
    verifier_model_version: str
    family: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
    ehmf_type: EhmfType | None                # None iff SUPPORTED
    span_id: str = Field(pattern=SPAN_ID)
    cached: bool


class V2ClaimVerdict(Contract):               # plan 7.4 v2 {tier, rule, generator_family, votes[], blind: true}
    tier: Literal[1, 2, 3]
    rule: Literal["1oo3", "2oo3", "1oo2", "equal-weights-share-v1", "withhold-queue-v3"]
    generator_family: str
    mode: Literal["FULL", "REDUCED-2", "REDUCED-1", "ZERO"]
    members: tuple[str, ...] = Field(max_length=3)     # the families eligible for this claim's tally, sorted
    votes: tuple[V2Vote, ...] = Field(max_length=24)   # sorted by (family, span_id)
    blind: Literal[True] = True
    objections: int = Field(ge=0, le=3)
    split: bool
    outcome: Literal["pass", "fail", "withheld"]
    critical: bool = False
    cycle: int = Field(ge=0, le=2)


class AlignmentVote(Contract):
    verifier_model_id: str
    verifier_model_version: str
    family: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    rating: int = Field(ge=1, le=5)
    leakage: bool


class V2Alignment(Contract):
    rule: Literal["1ooN-leakage-v1"] = "1ooN-leakage-v1"
    members: tuple[str, ...] = Field(max_length=3)
    votes: tuple[AlignmentVote, ...] = Field(max_length=3)
    rendered_text_sha256: str = Field(pattern=HEX64)   # the rendering judged
    outcome: Literal["pass", "fail"]


class V2Correction(Contract):
    cycle: int = Field(ge=1, le=2)
    kind: Literal["revise", "re_render"]
    failed_claim_ids: tuple[str, ...]          # sorted, claim-id pattern
    revised_claim_ids: tuple[str, ...] = ()    # the failed claims whose text the generator changed


class V2ShadowSummary(Contract):              # mode "shadow" only: what "on" would decide without correction
    would_deliver: int = Field(ge=0)
    would_fail: int = Field(ge=0)
    would_withhold: int = Field(ge=0)


class V2Block(Contract):
    block_schema: Literal["v2-panel-v1"] = "v2-panel-v1"
    mode: Literal["shadow", "on"]
    panel_reached: bool                       # the hook was consulted on at least one V1Passed candidate of this response
    gateway_state: Literal["open", "stopped"]
    registry: str
    generator_family: str
    members: tuple[str, ...] = Field(max_length=3)     # the panel at the start of the response, sorted
    degraded_mode: Literal["FULL", "REDUCED-2", "REDUCED-1", "ZERO"]   # the worst mode of a recorded claim verdict, FULL if none
    panel_weights_version: str
    routing_table_version: str
    tool_contract_version: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    alignment_prompt_hash: str = Field(pattern=HEX64)
    alignment: V2Alignment | None
    cycles: int = Field(ge=0, le=2)
    corrections: tuple[V2Correction, ...] = Field(max_length=2)
    calls: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    cost_units: int = Field(ge=0)
    kill_switch: Literal["none", "abstain_only", "pre_verified_only"]
    banner: Literal["degraded-reduced-2-v1", "degraded-reduced-1-v1", "degraded-zero-v1"] | None
    shadow: V2ShadowSummary | None


class V3IntentV2(V3Intent):
    reasons: tuple[Literal["v1_3_flag", "v1_8_misconception", "x4_margin", "v2_correction_exhausted", "v2_degraded_withheld"], ...] = Field(min_length=1)
    escalation: Literal["X2"] | None = None    # X2 iff "v2_correction_exhausted" in reasons


class ClaimVerdictV2(ClaimVerdict):
    v2: V2ClaimVerdict | None = None
    v3: V3IntentV2 | None = None


class VerificationRecordV2(VerificationRecord):
    verification_schema: Literal["v2-verification-v1"] = "v2-verification-v1"
    verdicts: tuple[ClaimVerdictV2, ...] = Field(max_length=20)
    labels: tuple[Literal["near_floor", "conflict_disclosed", "degraded"], ...] = ()
    v2: V2Block


class ProvenanceV3(ProvenanceV2):             # plan 7.4: every provenance field is filled
    panel_weights_version: str
    routing_table_version: str
    tool_contract_version: str


class ClaimLedgerEntryV3(ClaimLedgerEntryV2):
    provenance: ProvenanceV3


class LedgerEntryV3(LedgerEntryV2):
    entry_schema: Literal["ledger-entry-v3"] = "ledger-entry-v3"
    claims: tuple[ClaimLedgerEntryV3, ...]
    provenance: ProvenanceV3
    verification: VerificationRecordV2
```

Contract-level validators: `V2Vote` names an EHMF type exactly when it objects; `V2ClaimVerdict` refuses the generator's family among its members, unsorted members, a vote of a non-member family and two votes of one `(family, span_id)` (AC-5-1, AC-5-2); `V2Alignment` requires one vote per member family, sorted, and `fail` exactly when a member flags leakage; `V2Correction` requires sorted claim ids, revised ⊆ failed and no revision on a `re_render`; `V3IntentV2` requires `X2` exactly when `v2_correction_exhausted` is a reason.

**Shared rule body.**
- `VerificationRecord._rules` calls `verification_problems(record, *, v1_3_routed=_never, claim_abstains_alone=_never, final_reasons=PHASE4_FINAL_REASONS)`, where `PHASE4_FINAL_REASONS = (*ABSTENTION_REASONS, *V1_ABSTENTION_REASONS, *V1_WITHHOLD_REASONS)`. The body is the Phase 4 list, with three parameters: the deliverable check accepts a V1.3 `flag` when `v1_3_routed(verdict)`; "a claim abstains only when the response abstains" accepts a claim when `claim_abstains_alone(verdict)`; the `final_reason` allow-list is `final_reasons`.
- The `final == "correct"` refusal reads "a record never ends in 'correct': a correction is a new candidate (Phase 4 R-d)".
- With the default parameters the behaviour is Phase 4's exactly.
- `VerificationRecordV2` overrides `_rules` (the same validator name, so pydantic replaces the parent's) and runs both `verification_problems` with `v1_3_routed = lambda v: on and v.v2 is not None and v.v2.outcome == "pass"`, `claim_abstains_alone = lambda v: on and v.v3 is not None and v.v3.escalation == "X2"` and `final_reasons = (*PHASE4_FINAL_REASONS, *V2_ABSTENTION_REASONS, *V2_WITHHOLD_REASONS)`, where `on` is `self.v2.mode == "on"`; and `_v2_rules` (below).

**`VerificationRecordV2._v2_rules`**
- **Invariant 3 / AC-5-5:** when `hard_fail` is true, or `final == "abstain"` with a V1 reason (ABSTENTION_REASONS or V1_ABSTENTION_REASONS), no verdict carries `v2` and `alignment is None`: V2 never overwrites a V1 decision. `panel_reached` false implies no call, no cycle, no correction and no verdict with `v2`. The block's members exclude the generator's family and are sorted.
- **Per verdict with `v2` set:** `v2.generator_family == block.generator_family` and `generator_family not in v2.members` (AC-5-1, R-20); every vote's family is in `v2.members`; no two votes share `(family, span_id)` (AC-5-2); `v2.mode == mode_for(len(v2.members))`; `v2.rule == ROUTING_TABLES[block.routing_table_version][v2.mode][v2.tier]`; a `withhold-queue-v3` claim has no vote, no objection, `split` false and outcome `withheld`; otherwise every member family voted and `v2.objections`, `v2.split` and `v2.outcome` equal the values recomputed from the votes (`family_verdict` per member, then `tally`), so the record cannot state an outcome its votes do not give; every vote's `verifier_prompt_hash == block.verifier_prompt_hash` (E-97); `v2.cycle <= block.cycles`.
- **Mode `shadow`:** `block.shadow` is set, `block.cycles == 0`, no correction, no `escalation`, and `final_reason` lies in `PHASE4_FINAL_REASONS`; a V1.3-flagged claim is never delivered (the default deliverable rule).
- **Mode `on`:** a `deliver` verdict has `v2.outcome == "pass"`; a verdict with `v2.outcome == "fail"` has `final == "abstain"` and `v3.escalation == "X2"`; a verdict with `v2.outcome == "withheld"` has `final == "withhold"` (`"abstain"` under a kill switch) and `"v2_degraded_withheld" in v3.reasons`; `block.shadow is None`; `len(block.corrections) == block.cycles` and `corrections[i].cycle == i + 1`; an `X2` escalation implies `block.cycles == MAX_CORRECTION_CYCLES`; with a kill switch the response abstains, with `final_reason` `v2_kill_switch` (or a V1 reason when V1 abstained).
- `kill_switch != "none"` implies no call, and every claim verdict with `v2` is `withheld` in `ZERO` with no vote; `final_reason == "v2_kill_switch"` implies a kill switch.
- `"degraded" in labels` iff some verdict carries `v2` and `degraded_mode != "FULL"`; `banner` is set iff `"degraded" in labels`, and its id matches `degraded_mode`; `degraded_mode` is the worst mode of a judged claim, `FULL` if none.

**`LedgerEntryV3._v3_rules`** (the inherited `_rules` and `_v1_rules` run too): `provenance.panel_weights_version`, `routing_table_version` and `tool_contract_version` equal the block's; `delivery == "shadow"`; in V1 `enforce`, every vote's `span_id` is one of its claim's `span_ids`. The inherited rule "in enforce, the record abstains exactly when V1 does" reads `verification.final`, so the pipeline derives `decision` from the final under `on` (4.16).

**Registries.** `ACCEPTED_ABSTENTION_REASONS["ledger-entry-v3"] = (*ACCEPTED_ABSTENTION_REASONS["ledger-entry-v2"], *V2_ABSTENTION_REASONS)`; `SCHEMA_MODELS["LedgerEntryV3"] = LedgerEntryV3` (in `tutor_pipeline/contracts.py`); the four gateway request and verdict models are registered by `gateway/contracts.py` (`V2VerdictRequest`, `V2AlignmentRequest`, `V2AdapterVerdict`, `V2AlignmentVerdict`), which imports `tutor_pipeline.contracts`, never the reverse; `tutor_pipeline/package_check.model_schema` imports `app.gateway.contracts` before reading `SCHEMA_MODELS`, so no lookup depends on import order; `ENTRY_SCHEMAS["ledger-entry-v3"] = LedgerEntryV3`.

### 3.4 Runtime types (`v2_panel/panel.py`, `v2_panel/track.py`; dataclasses)

```python
@dataclass(frozen=True)
class Panel:                     # constructed only by Panel.build; __post_init__ refuses family(g) (AC-5-1)
    generator_family: str
    members: tuple[AdapterSpec, ...]     # at most MAX_MEMBERS, one per family, registry order

    @classmethod
    def build(cls, eligible: Sequence[AdapterSpec], *, generator_family: str, max_members: int = MAX_MEMBERS) -> "Panel": ...


@dataclass(frozen=True)
class V2Outcome:
    mode: Literal["shadow", "on"]
    generator_family: str
    members: tuple[str, ...]
    degraded_mode: str
    claims: Mapping[str, V2ClaimVerdict]      # eligible claims only
    alignment: V2Alignment | None
    calls: int
    cache_hits: int
    cost_units: int
    latency_ms: float
    gateway_state: str
    kill_switch: str

    def failing(self) -> tuple[str, ...]: ...       # claims with outcome "fail"
    def objection_types(self, claim_id: str) -> tuple[str, ...]: ...   # the EHMF types of its objecting families (4.9 E)
```

`aggregate.V2Hook.consult(passed) -> object` is unchanged. A new function sits beside `consult_v2`:

```python
def v2_outcome(hook: V2Hook | None, decision: V1Decision) -> object | None:
    """Only a V1Passed reaches a hook (plan rule 1, invariant 3); returns the hook's result, else None."""
```

`consult_v2` is `v2_outcome(hook, decision); return decision`; its behaviour is unchanged. `V1Run` (runner) gains `v2: Any = None`, the last V2 outcome.

---

## 4. Algorithms

### 4.1 Pinning (`gateway/pinning.py`; AC-5-10, task 5.1, R-24)

```python
PIN_RULE = "pinned-version-v1"
REFUSED_TOKENS_TEXT = r"alias|auto|current|default|exp\d*|experimental|latest|nightly|preview\d*"
REFUSED_WITHIN_TOKEN_TEXT = r"preview|latest|nightly|experimental|exp\d*$"
REFUSED_TOKEN = re.compile(rf"^(?:{REFUSED_TOKENS_TEXT})$")
REFUSED_WITHIN_TOKEN = re.compile(REFUSED_WITHIN_TOKEN_TEXT)
PINNED_VERSION = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{3}|v?\d+(?:\.\d+){1,3})$")
def pin_problem(model_id: str, model_version: str | None) -> str | None: ...
```

The checks run in this order, and the first one that fails gives the result: (1) the version is missing or blank: `"unpinned: lacks a version"`; (2) a token of `model_id` or `model_version`, split on `[^a-z0-9]+` after casefold, matches `REFUSED_TOKEN`, or holds an alias glued to other characters (`REFUSED_WITHIN_TOKEN`: `preview`, `latest`, `nightly` or `experimental` anywhere in the token, or a token ending in `exp` and digits): `"unpinned: names a moving alias (<alias>)"` (`gemini-3.1-flash-lite-preview`, `gemini3preview`, `gpt4latest`, `-latest`, `-exp`, `-exp-0827`, `gemini3exp`, `@latest`, `alias`, `default`; `exp` inside a word, as in `express` or `expert`, is no alias); (3) `model_id` or `model_version` differs from its stripped form: `"unpinned: the identifier is not in its canonical form"`, so the loader stores and cache-keys only canonical identifiers; (4) `model_version` does not fully match `PINNED_VERSION`, or a date form names no calendar day (`datetime.strptime` with `%Y-%m-%d` or `%Y%m%d`, so `2026-13-45`, `2026-02-29` and `00000000` are refused): `"unpinned: version is not a pinned form"`. Otherwise the result is `None`. The package's `gateway.pinning` texts (`refused_tokens`, `refused_within_token`, `version_pattern`) must equal the code's. The loader applies the rule to every member of every registry; the problem is structural, so the load, and with it start-up, always stops (`ConfigPackageError` naming the adapter id and "unpinned"). The development fakes are pinned by date (`2026-11-21`).

### 4.2 Registry, panel and eligibility (`gateway/registry.py`, `v2_panel/panel.py`)

- **`registry_for(package, settings)`:** the package's `gateway.registries[name]`, where `name = settings.environment.lower()` when that key exists, otherwise `"default"`. The shipped registries are `development` (four fakes), and `staging`, `production` and `default` (all empty).
- **`generator_family(package, registry, generator_id)`:** `package.v2.generator_families[generator_id]` (`extractive-d19-v1 → "extractive-d19"`); a generator whose id is a registry adapter's `adapter_id` with capability `generate` takes that spec's family. Any other generator raises `GeneratorFamilyUnknown`: the track then records every eligible claim `withheld` in `ZERO` with no call, and logs `tutor.v2.unavailable` (`reason: "unknown_generator_family"`). An unknown family never yields a panel (fail closed, AC-5-1).
- **`ModelGateway.eligible(adapters, *, settings)`** keeps registry order and drops an adapter when any R-b reason holds; each drop is counted by reason (`GATEWAY_METRICS`).
- **`Panel.build(eligible, generator_family)`:** walk `eligible` (verifiers only) in registry order; skip a member whose family equals `generator_family`; skip a member whose family is already taken (one per family, R-d); stop at `max_members`. `Panel.__post_init__` raises `PanelError` if any member's family equals `generator_family`, if two members share a family, if there are more than 3 members, or if a member does not verify, so no code path can hold a panel with family(g) (the "enforced by gateway types" part of 5.3). With the extractive generator and the development registry the panel is `fake-alpha`, `fake-beta`, `fake-gamma`; `fake-delta` is the spare family, drawn only when one of the three is ineligible. A second adapter of a family whose first adapter is ineligible represents that family.
- **`mode_for(n)`:** 3 gives `FULL`, 2 `REDUCED-2`, 1 `REDUCED-1`, 0 `ZERO`.
- **Mid-response loss.** If a call to a member raises `GatewayRefused` or `AdapterError` (R-b), the member is dropped for the rest of the response and its pair votes for the current claim are discarded; the claim is re-tallied from the remaining members' pair votes, which the track holds in memory for the current claim (no cache query and no new call), under the recomputed mode and rule; claims already decided keep their verdicts (each records its own `mode` and `members`). A `GatewayStopped` (a stop) drops every member.

### 4.3 Egress opt-in, secrets, redaction (`gateway/egress.py`, `gateway/secrets.py`; D-23, E-109, R-06, task 5.12)

- **`egress_allowed(settings, provider) -> bool`** is `provider == "fake" or provider in settings.model_egress_providers`. `MODEL_EGRESS_PROVIDERS` defaults to `[]` in every environment, development included (PD-22): each environment sets its own list, each entry names one provider. A refused non-fake member is ineligible and logs `gateway.egress_refused` (`provider`, `adapter_id`) once per process and provider. The semantic backend's embedding egress is the gateway's (4.19), and its first check is `egress_allowed(settings, "openai-embeddings")`.
- **`SecretStore`** is a Protocol: `get(ref: str) -> str | None`. `EnvironmentSecretStore` reads `os.environ[ref]`, which is how Cloud Run mounts Secret Manager secrets; it holds no SDK and makes no network call. Tests use `v2_fakes.FakeSecretStore`. A key read is registered with `install_log_redaction([value], owner="gateway")`. No adapter attribute holds a key: the key is read per call. `PROVIDER_SECRET_REFS = ("OPENAI_API_KEY",)` names the credential the gateway holds outside the registry (the embedding key, 4.19), and `provider_secret_values()` gives its value to the redaction that `main.py` and `workers/common.py` install at start-up. The gateway imports no `google.auth`, and application-default credentials are never discovered (E-109).
- **`HttpJsonAdapter(spec, *, secret_store, transport=None, sleep=time.sleep, clock=time.monotonic)`**: its constructor refuses an `endpoint` that is not `https` or holds a query, userinfo or fragment ("keys and parameters never travel in the URL"). It posts `{"model": model_id, "model_version": version, "max_tokens": caps.max_tokens, "instructions": <the fixed instruction text of the request's prompt_id>, "input": <request JSON>}` with `httpx.Client(timeout=caps.timeout_ms/1000, transport=transport)`; the envelope names the adapter's own model only, and the instruction text is `VERIFIER_INSTRUCTIONS` or `ALIGNMENT_INSTRUCTIONS` (4.7), so every verifier is sent the same text (E-97); a request whose `prompt_hash` is not that text's hash is refused before any call (`invalid_request`). The key travels only in a header (`Authorization: Bearer <key>` or `x-api-key: <key>`). It retries up to `caps.max_retries` on a timeout, a `TransportError`, any other httpx client error (`transport`) or status 429/500/502/503/504, with `sleep(0.05 * 2**i)` between tries, and before each retry it calls the gateway's `reserve_retry` hook, which reserves one more call's cost (a refused reservation sends nothing more: `budget`); a 4xx other than 429 is not retried, nor is a body the client cannot decode (`httpx.DecodingError`, `invalid_output`). The response must be `{"output": {...}, "usage": {"cost_units": int}}` with a non-negative integer cost, and `output` is returned for projection (3.1); a reported cost above the call's reservation (`spec.cost_units_per_call`) is `cost_overrun`. Every failure raises `AdapterError(adapter_id, kind, status)`, `kind ∈ {"http_status", "timeout", "transport", "invalid_output", "invalid_request", "cost_overrun", "budget", "no_key"}`, after the `except` block, so the error's `__cause__` and `__context__` are both `None` and no httpx object (whose request carries the headers) is reachable from it; its text is `adapter <id> failed: <kind>` plus the status code, naming no URL, header or key. The adapter never logs. The gateway reserves the spec's `cost_units_per_call` for each call's first attempt and, through the call's `reserve_retry` hook, for each retry before it is sent (`gateway.call`'s `cost_units` is their sum); a `budget` failure stops the gateway (`budget_breach`) unless the budget's store failed (then the member is only unavailable); and it turns any adapter exception other than `AdapterError` into `AdapterError(kind="error")`, raised outside its `except` block, so a misbehaving member is only unavailable (R-b).
- **`log_redaction`:** `install_log_redaction(values, *, owner=None)` records each secret's owner; `add_secret_listener(owner, callback)` registers a callable or a `weakref.WeakMethod`. Whenever redaction masks an owned secret literal in a text (the record factory and the JSON formatter both call `redact`), it calls that owner's listeners with the owner's name. A listener only sets a flag: it never logs, raises or touches a database, because it runs inside the logging call that made the record. The existing masking is unchanged.

### 4.4 Caps and budget (`gateway/budget.py`; task 5.10, AC-5-9, A-15)

- Caps come from each `AdapterSpec`. For fakes, the gateway treats a call whose measured duration (injectable clock) exceeds `timeout_ms` as `AdapterError(kind="timeout")`; an in-process call cannot be pre-empted, as in V1.3.
- **`DatabaseBudget(registry, daily_units, *, alert=(4, 5), today=utc_date)`** (`gateway/controls.py`) is the process gateway's budget (v4 `gateway.budgets.scope` `database`): one `gateway_budget_days` row per registry and UTC day, shared by every instance and worker. `reserve(cost)` inserts the day's row when it is missing, then runs one `UPDATE … SET spent = spent + cost WHERE registry, day AND spent + cost <= daily_units RETURNING spent`, so the hard stop holds however many instances spend; in the same transaction the first reservation that reaches 4/5 of the day's units flips `alerted` and logs `gateway.budget_alert` once a day across instances. A new UTC day is a new row. Its `remaining()` and `snapshot()` read the day's row.
- **`DailyBudget(daily_units, *, alert=(4, 5), today=utc_date)`** is the same rule in one process: the budget a test or the fixture runner passes. `remaining()` is what is left today; eligibility drops every adapter when `daily_units` is 0 and an adapter whose `cost_units_per_call` exceeds `remaining()`, so a panel shrinks before it can overspend at the start of a response. `reserve(cost) -> bool`: when the UTC date changes, `spent` resets to 0 and `alerted` clears; if `spent + cost > daily_units` it returns `False` and the gateway stops with `budget_breach` (4.5), which happens when calls inside one response cross the budget after eligibility was decided; otherwise `spent += cost`, and the first time `spent * 5 >= daily_units * 4` in a day it logs `gateway.budget_alert` (`share` "4/5", `daily_units`, `spent`) at WARNING. A reply whose reported cost exceeds the call's reservation (`cost_overrun`, 4.3) also stops the gateway with `budget_breach`: the budget no longer bounds the spend (R-47). A cache hit costs nothing. Daily units come from the package: production, staging and default 0, development 100000 (PD-26).
- **Every attempt is reserved.** The call's reservation covers its first attempt; `HttpJsonAdapter` reserves each retry through the gateway's `reserve_retry` hook before it sends it, and the embedding adapter reserves each attempt's `len(inputs) * cost_units_per_item` (4.19). A retry the budget refuses is not sent and stops the gateway (`budget_breach`), so a provider that bills a failed attempt is billed only for attempts the budget counted.
- **Store faults fail closed.** When `remaining()` raises (the shared store cannot be read), the adapter is ineligible (`budget_unavailable`); when a call's or a retry's `reserve()` raises, the call is refused (`GatewayRefused`) and the member is unavailable. Nothing is sent, nothing is spent, the gateway stays open, and each fault logs `gateway.budget_unavailable` (WARNING). The response runs on with the members left, ZERO at worst, and keeps its record.

### 4.5 Payload policy and stop guards (`gateway/policy.py`, `gateway/gateway.py`; plan H, plan L, R-10, Q-15)

**`PayloadPolicy.check(request, context)` raises `PayloadViolation(reason)`.** `context` is the call's `PolicyContext(store, corpus_registry, rendering, locked, lesson_slug)`, built by the V2 track from its own pipeline (never sent): one process gateway serves pipelines over different stores and manifests, so the policy never binds one at construction.
- **Claim items:** the span id resolves in `context.store.span_registry`; its record's `plane == "public"`; `contained_answers.span_is_quotable(record, context.corpus_registry)`, the D-19 rule (under D-31 nothing is quotable outside development, so nothing could leave); the request's span text equals the record's text after whitespace collapse; and, after the identifier scan, the claim text lies inside the span text (both NFKC-casefolded and whitespace-collapsed, the fake rule's fold), else `claim_not_in_span`. V1.2 binds whole verbatim sentences, so every locked claim passes; the check makes the claim item public corpus text by the policy itself.
- **Alignment items:** `rendered_text` equals `layout_text(context.rendering.segments)`; every claim segment names a claim of `context.locked` whose text it equals, and every span of that claim passes the claim-item span checks; every other segment's text is its `template_id`'s `TEMPLATES` output with its parameters; `objective` is `None` or the summary of the context's lesson.
- **Embedding items** (`check_embedding(texts, *, purpose, context)`, 4.19): a `query` item is refused (`learner_text`): it is the learner's query text, and plan H lets only public-corpus spans leave; each `documents` item must be the excerpt (whitespace collapsed) of an index entry of `context.store` whose span passes the claim-item span checks, else `unknown_span` or that check's reason; with no context every item is refused (`no_context`); no text holds an identifier.
- **Both:** no string matches an identifier pattern: `turn-`, `shadow-`, `qa-`, `thread-` or `message-` followed by a uuid, a bare uuid, an email address, or `Bearer` (M20: no shipped corpus text matches). A claim item that its contract refuses (an identifier in its text) is a violation too: the track stops the gateway.

**The stop guards.** `ModelGateway.stop(reason)`, `reason ∈ {"payload_violation", "secret_in_logs", "budget_breach"}`, sets `state = "stopped"` and `stop_reason`, logs `gateway.stopped` (`reason`) at ERROR and calls `record_security_event("gateway.stopped", "denied", actor_role="system", details={"reason": reason})`. Triggers: `payload_violation` when `PayloadPolicy.check` raised; `secret_in_logs` when the redaction listener set the gateway's secret flag for an owner-`gateway` secret (the gateway reads the flag before every eligibility decision and every call, and stops there, outside the logging machinery); `budget_breach` when the budget refused a call's or a retry's reservation or a reply reported a cost above its reservation. A stopped gateway refuses every call (`GatewayStopped`), so every remaining member of the response in flight is unavailable and that response finishes in ZERO, which fails closed. A call the gateway refuses before the adapter (stopped, a payload violation, a budget breach) is counted and logged as `gateway.call` with `outcome` `refused`, `latency_ms` 0 and `cost_units` 0 (it adds no latency sample). From the next response on, `v2_panel.mode(...)` is `off` (conflict 25), so later responses are Phase 4's; `/ready` reports `gateway.state "stopped"` and `model_gateway` `off` (the reason is in the log line, never on the public route: 10.2).

**Shared and durable.** The process gateway holds its registry's `DatabaseStopStore` (`gateway/controls.py`; v4 `gateway.stop.scope` `database`). `stop` also writes the reason to `gateway_stops` (the first reason written stands; a write that fails logs `gateway.stop_unshared` and this instance stays stopped). `refresh()` reads the row before every eligibility decision and every call, when the process gateway is built, and in `v2_panel.mode`, `process_gateway_stopped` and `process_gateway_state`; a recorded stop is adopted: the instance stops with that reason, logs `gateway.stopped` with `origin` `shared`, and writes no second security event (a read that fails logs `gateway.stop_unread` and leaves the state as it is). The stopping instance logs `origin` `instance`. So every instance refuses every call, and a process that builds a gateway while the stop is recorded starts stopped. Only an operator clears the stored stop, with `python -m app.workers.gateway_stop --clear REGISTRY` (the in-image command; security event `gateway.stop_cleared`, `actor_role` `operator`, with the registry and the reason it held), and a running gateway never reopens (`refresh()` returns at once once the instance is stopped): an instance that stopped or adopted the stop refuses every call until it is replaced, so service resumes with a new revision, whose processes start open. A process whose V2 mode is off by its settings (`MODEL_GATEWAY` off) builds no gateway and reads no stop, so its `/ready` reports `state` `open` with `model_gateway` `off`; the operator's status command reads the stored stops. `MODEL_GATEWAY=off` stays plan L's flag back. A gateway built without a stop store (a test's, the fixture runner's) keeps its stop to itself. `reset_process_gateway()` and `controls.clear_shared_controls()` are the test seams, used by an autouse fixture in `conftest.py`.

### 4.6 Tool contracts (`gateway/tools.py`; task 5.2, E-76, E-97)

```python
TOOL_CONTRACT_VERSION = "mcp-tools-v1"
SERVERS = ("analytics", "citation", "corpus", "learner", "verification")     # VBT RevB p. 8 (M9)
TOOLS = (
    ToolSpec("corpus", "corpus.retrieve", RetrievalRequest, EvidenceBundle, frozenset({"evidential"})),
    ToolSpec("corpus", "corpus.span_text", SpanRef, SpanText, frozenset({"evidential", "verifier"})),
    ToolSpec("citation", "citation.resolve", SpanRef, SpanResolution, frozenset({"evidential", "pedagogical", "verifier"})),
    ToolSpec("learner", "learner.presentation_plan", PresentationRequest, PresentationPlan, frozenset({"planner", "pedagogical"})),
    ToolSpec("verification", "verification.verdict", VerdictRequest, AdapterVerdict, frozenset({"verifier"})),
    ToolSpec("verification", "verification.alignment", AlignmentRequest, AlignmentVerdict, frozenset({"verifier"})),
    ToolSpec("analytics", "analytics.record_outcome", OutcomeEvent, Ack, frozenset({"ledger"})),
)
```

**Small contracts** (`gateway/contracts.py`): `SpanRef {span_id}`; `SpanText {span_id, text, content_hash, plane: "public"}`; `SpanResolution {span_id, resolution: "resolved" | "unresolvable", item_id, content_hash}`; `PresentationRequest {hint: "concise" | "stepwise" | "socratic" | None}`; `OutcomeEvent {surface: "two_pass", final, degraded_mode, calls, cost_units}` (enums and counts only); `Ack {ok: True}`.

**`ToolHost(handlers)`** has `call(role, tool, payload, **context)`: it refuses a tool whose `roles` lack `role` (`ToolNotVisible`; invariant 1: the learner server is hidden from `evidential` and `verifier`), validates the input and output models, and counts calls per `(role, tool)`. **Handlers** (`ToolHost.default(pipeline, gateway)`) are one-line delegations: `corpus.retrieve` is `tutor_pipeline.retrieve.retrieve`; `corpus.span_text` reads the pipeline's span registry; `citation.resolve` is `SpanResolver.resolve_current`; `learner.presentation_plan` returns the hint or the package default plan (no learner state); `verification.verdict` and `verification.alignment` call `ModelGateway.verify` and `ModelGateway.align` for the member passed as `adapter=` with the `PolicyContext` passed as `policy=`; `analytics.record_outcome` records `V2_METRICS`. The V2 track builds every claim item's span text through `corpus.span_text` and casts every vote through `verification.verdict`, so every verifier reaches the same tool surface (E-97).

**The contract document.** `tool_contract_document()` returns `{"contract_version", "transport": "in-process", "servers": {server: {tool: {"roles": sorted, "input": model_json_schema, "output": model_json_schema}}}}`. It is committed as `app/config_package/schemas/tool-contracts.v1.json`, and package v4 pins the committed file's canonical sha256 (`tools.sha256`). `tool_contract_version` is stamped on every v3 ledger record (provenance and V2 block).

### 4.7 Verifier and alignment instructions (fixed text, hashed)

- **`VERIFIER_INSTRUCTIONS`:** "Judge one claim against one evidence span from a public course corpus, using only the span. Answer SUPPORTED when the span states the claim, CONTRADICTED when it states the opposite, NOT_ENOUGH_INFO otherwise. When the answer is not SUPPORTED, give one EHMF type: A unsupported or contradicted content, B a citation that does not support the claim, C a misconception, D a conflict between sources, E presentation. Return the span id you relied on."
- **`ALIGNMENT_INSTRUCTIONS`:** "Rate from 1 to 5 how well this rendered answer serves the stated learning objective at the stated readability band, and flag leakage when it reveals an assessment answer key."

Neither text names a model, family, generator, learner or vote. The hashes are pinned in v4 `v2.prompt`, and the gateway package check compares them with the code.

### 4.8 Tiers (`v2_panel/tiers.py`; PD-25)

`tier_for(items, package)`: 1 when `items` is non-empty, where the V2 track computes `items = assessment_items(ctx.resolved.text, pipeline.keyed_items, v1=pipeline.v1_params, stopwords=package.retrieval.stopwords)` itself (the V1 render hook's own computation; `V1Passed` keeps its fields); otherwise `package.v2.default_tier` (2). `expert_mode` is `null` in v4, so tier 3 is never assigned in shipped behaviour; tests reach tier 3 through an in-memory overlay of the parsed parameters. `critical_for(claim_id, package, *, environment)` is membership of package v5's `v3.critical_claims` registry for the environment (empty outside development while D-25 is open; synthetic in development), and of `v2.correction.critical_registry` (empty) for a package without a v3 block (Phase 6 spec 4.13). Every claim of a response has the same tier.

### 4.9 Voting (`v2_panel/voting.py`; unit-tested exhaustively)

**F. `family_verdict(pairs)`**, over one member's (verdict, ehmf) pairs for a claim's spans in span-id order: `CONTRADICTED` if any pair is CONTRADICTED, else `NOT_ENOUGH_INFO` if any pair is NEI, else `SUPPORTED`. The family's `ehmf_type` is the type of the first pair carrying the chosen verdict. Every bound span must support the claim (a non-supporting citation objects; plan 12.3).

**T. `tally(rule, fv, threshold=(num, den))`**, with `o` = objections (family verdicts ≠ SUPPORTED), `s` = supports and `N = len(fv)`:

| rule | requires | outcome |
|---|---|---|
| `1oo3` | N = 3 | `fail` iff o ≥ 1 |
| `2oo3` | N = 3 | `fail` iff o ≥ 2 |
| `1oo2` | N = 2 | `fail` iff o ≥ 1 |
| `equal-weights-share-v1` | N ≥ 1 | `pass` iff den·s ≥ num·N (2/3, PD-25) |
| `withhold-queue-v3` | any (no calls made) | `withheld` |

A rule given the wrong N raises `ValueError`; the record rule recomputes it. The tally's default threshold is `rules.TIER3_THRESHOLD` (2, 3), and the loader refuses a package `tier3_threshold` other than it while Q-22 is unresolved, so the track (which passes the package value) and the record rule (which re-tallies every recorded claim with the default) agree; the threshold in force is pinned by the record's `config_package_version` and `config_package_sha256`. `is_split(fv)` is `s ≥ 1 and o ≥ 1`.

**E. `objection_types(pairs_by_family)`**: the EHMF types of a claim's objecting family verdicts (rule F per family), in family order. `presentation_only(types)` is true when there is at least one and every one is `E`: such a claim is a presentation fault (4.13). AC-5-4 follows: one objection fails tier 1 (1oo3) and passes tier 2 (2oo3), and NEI counts as an objection.

### 4.10 Degraded modes (`degraded-matrix-v1`; task 5.9, 5.11, D-29 (a), R-21, R-48)

| Mode (eligible members) | Tier 1 | Tier 2 | Tier 3 | Response |
|---|---|---|---|---|
| FULL (3) | 1oo3 | 2oo3 | equal weights ≥ 2/3 | as voted |
| REDUCED-2 (2) | 1oo2 | 1oo2 | 1oo2 | label `degraded`, banner `degraded-reduced-2-v1` |
| REDUCED-1 (1) | withheld, queued for V3 | withheld, queued (D-29 (a)) | equal weights on the remaining verifier | label `degraded`, banner `degraded-reduced-1-v1` |
| ZERO (0) | withheld, queued | withheld, queued | withheld, queued | no call. Pre-verified module content when `pre_verified_source` is set (it is `null`), else withhold and queue. Label `degraded`, banner `degraded-zero-v1` |

- A `withheld` claim gets V3 reason `v2_degraded_withheld`, with no escalation and no call.
- A kill switch makes every adapter ineligible: every eligible claim is `withheld` in ZERO with no call. In `on` the record abstains whatever the legacy decision was (plan 13.6 "abstain-only, pre-verified-only"): every claim's final is `abstain`, each claim V2 withheld keeps its `v2_degraded_withheld` queue intent, and the response's `final_reason` is `v2_kill_switch` with `replacement` `none`. `pre_verified_only` takes plan 5.11's other branch, "abstain and queue", because `pre_verified_source` is `null` (DI-83), so the two switches give the same finals. The record names the switch (`verification.v2.kill_switch`). Like `MODEL_GATEWAY`, the switch acts on the two-pass shadow pipeline only: no delivered answer reads it until delivery exists (DI-85), so it is no learner stop (the runbook's learner fallback is `MODEL_GATEWAY=off`, and the delivered path is D-19 containment).
- The banner texts are package values (`v2.degraded.banners`, PD-30), recorded by id on the V2 block: `degraded-reduced-2-v1` "Fewer independent checks than usual verified this answer." (its claims passed 1oo2 voting), `degraded-reduced-1-v1` "Parts of this answer are held back until more checks are available." and `degraded-zero-v1` "Verification is unavailable right now, so only quoted course passages or no answer is shown." (the D-19 answer or an abstention; no checked content exists). No banner says grounded. Nothing outside the development or test shadow path builds or shows them (E12).

### 4.11 Alignment item

- One `AlignmentRequest` per remaining member, after the claim items, when some claim passed and a member remains: in mode `shadow` on V1's accepted rendering; in mode `on` on the final rendering (4.14), and again on each Type E re-render. `rendered_text` is that rendering's text (locked claim texts plus fixed templates, M10); `objective` is `store.lessons[ctx.lesson_slug].summary`, or `None`; `band` is `ReadabilityBand(v1.readability_min, v1.readability_max)`.
- Rule `1ooN-leakage-v1`: `fail` iff any member flags `leakage`. Ratings are recorded and never gate (the plan gives no rating threshold, and ratings never certify truth: invariant 5).
- Alignment verdicts are not cached (they depend on rendered text). The item's failure is type E. The record names the rendering judged (`rendered_text_sha256`). With no member left, there is no alignment verdict (conflict 34).

### 4.12 The V2 track (`v2_panel/track.py`): `V2Track.consult(passed) -> V2Outcome`

```
def consult(passed: V1Passed) -> V2Outcome:
    begin once per response: gateway.check_secret_flag(); eligible = gateway.eligible(registry.verifiers(), settings=settings)
        try: gf = generator_family(package, registry, pipeline.generator.ref.generator_id)
        except GeneratorFamilyUnknown: gf, eligible = "unknown", []      # fail closed: every eligible claim withheld in ZERO
        panel = Panel.build(eligible, generator_family=gf); members = list(panel.members)
    eligible_claims = locked claims not in (V1.8 flagged ∪ withheld-conflict claims ∪ V1.6-omitted claims)   # V1.3 flags route to V2
    items = assessment_items(ctx.resolved.text, ...); tier = tier_for(items, package)
    for claim in eligible_claims (locked order):
        pairs = {}                                                  # (member, span_id) -> (AdapterVerdict, cached), this claim only
        while True:
            mode = mode_for(len(members)); rule = table[mode][tier]
            if rule == "withhold-queue-v3": record withheld (members = families of `members`, no vote); break
            for m in members, span_id in claim.span_ids not yet in pairs:
                if budget_over("verify"): members = []; lost; break          # the shadow budget: everyone unavailable (ZERO)
                request = VerdictRequest(claim_text=claim.text, span=tools.call("verifier", "corpus.span_text", SpanRef(span_id)), ...)
                hit = cache.get("verdict", verdict_key(...))
                try: verdict = hit or tools.call("verifier", "verification.verdict", request, adapter=m, policy=policy_context)
                except GatewayStopped: members = []; lost; break
                except (GatewayRefused, AdapterError): members.remove(m); drop pairs of m; lost; break   # re-tally from memory
                if not hit: cache.put("verdict", key, verdict)
            if not lost: fv = [family_verdict(pairs of m) for m in members]; outcome = tally(rule, fv); break
    alignment = shadow: align(V1's accepted rendering) when some claim passed; on: after the final rendering (4.14)
    return V2Outcome(...)
```

Every step logs only enumerations and counts. `budget_over` is the pipeline's shadow-budget closure (`_over(started, budget_ms, "verify", event="tutor.v2.budget_exceeded")`); a budget stop is recorded like an outage (ZERO for the rest of the response), logs `tutor.v2.budget_exceeded` with its own message (`pipeline.BUDGET_EVENTS`: "The V2 panel exceeded the shadow budget") and is counted apart in `V2_METRICS` (`budget_exceeded`). `V2Track.finish(record, passed=...)` logs `tutor.v2.run`, counts the response in `V2_METRICS` and records the outcome through `analytics.record_outcome`. It computes `completed` (`V2Track.completed`: the response passed V1, every V2-eligible claim got a completed vote, `pass` or `fail`, and the alignment item was judged when a claim passed; a withheld claim or an unjudged alignment item is not completed) and `panel_mode()` (the mode of the members left at the end of the response, which is the worst mode its panel ran in because members only leave within a response; `None` when the panel was never reached).

### 4.13 Correction (mode `on`; task 5.8, AC-5-7)

`V1Track.run` with the V2 track as its hook runs this loop (in mode `shadow` the loop body never runs):

```
decision = self._decide(..., state=_RunState(...))  # candidate 0 (Phase 4, V1 regenerations included)
outcome, cycles, corrections = None, 0, []
while True:
    track.cycle = cycles; outcome = v2_outcome(track, decision)   # None unless V1Passed (AC-5-5)
    if outcome is None or outcome.mode == "shadow": break
    failing = outcome.failing()
    if not failing: break
    if cycles == MAX_CORRECTION_CYCLES: exhausted = failing; break
    cycles += 1
    presentation = {c in failing: presentation_only(outcome.objection_types(c))}   # every objection type E (plan 5.8)
    content = failing - presentation
    plan, revised = the locked claims, each content claim revised by generator.revise(text, span_texts, ehmf_type) when the
                    generator has it (ehmf_type: its first objection type other than E, in family order); none when content is empty
    corrections.append(V2Correction(cycle=cycles, kind="revise" if content else "re_render", failed_claim_ids=sorted(failing),
                                    revised_claim_ids=sorted(revised)))
    if revised:
        decision = self._decide(ctx, bundle, envelope, None, plan, budget_over, state=_RunState(...), regenerate=False)
        # a new candidate with fresh V1 state, judged by every V1 check from the start (Phase 4 R-d); a hard fail or an
        # abstention ends the loop with no further V2 call; the plan bypasses the claim-plan cache; its rendering
        # re-renders the presentation claims too
    elif presentation:
        decision = self._render(ctx, state, state.generation, ..., presentation=socratic)   # re-render only, fresh hook
        # a V1 failure of the rendering ends the loop with no further V2 call
    # otherwise unchanged: the same candidate is consulted again, every pair a cache hit
```

- **Type E re-renders only** (plan 5.8). A failing claim whose every objecting family names EHMF type `E` (presentation) is never given to `revise`: the cycle re-renders the same candidate (Socratic, a fresh post-render hook) and records `V2Correction(kind="re_render")` when every failing claim is such a claim. A claim with any objection of type A-D is a content fault and follows the revise path, given its first such type; in a cycle with both kinds the content claims are revised (`kind="revise"`), and the presentation claims are re-rendered with the new candidate, or with the same one when nothing was revised. The claim item carries no rendering, so a re-rendered claim is re-verified from the cache and, still failing after the cycles, abstains with X2 like any other (conflict 6). Package v4's `v2.correction` names the rules (`type_e` `re_render_only`, `other` `revise_or_reverify_unchanged`, `exhausted` `abstain_mark_x2`), and the loader refuses any other value (`rules.CORRECTION_RULES`).

- `ClaimReviser` is a Protocol: `revise(claim_text: str, span_texts: tuple[str, ...], ehmf_type: str) -> str | None`, never called with type `E`. `ExtractiveD19Generator` does not implement it: a verbatim quotation is re-verified unchanged (conflict 6). Test generators (`v2_fakes.RevisingGenerator`) implement it.
- A corrected claim keeps its span ids; its unchanged pairs hit the cache.
- **Fresh V1 state.** Every candidate, the first included, has its own `_RunState`, and every rendering starts from the candidate's pre-render results (`_RunState.pre_render`): no earlier candidate's or rendering's results reach `accepted_results` (M16). The record's `checks`, `generation_attempts` and `render_attempts` are the final candidate's and its final rendering's.
- **Exhaustion:** each still-failing claim ends `abstain` with `V3IntentV2(reasons + ["v2_correction_exhausted"], escalation="X2")`.

### 4.14 Finals, final rendering, alignment (`v2_panel/aggregate.py`, `v1_checks/runner.py`)

**Mode `on`, per locked claim of the final `V1Passed`:**
- `deliver` iff it is V2-eligible, its V2 outcome is `pass`, the final rendering shows it and the alignment item passed;
- `withhold` iff it is V1-withheld (V1.8, a withheld V1.7 conflict, V1.6) or its V2 outcome is `withheld`, or its V2 outcome passed and no member was left to judge the alignment item (with `v2_degraded_withheld`; conflict 34);
- `abstain` iff it is exhausted (X2), or under a kill switch (every claim; 4.10).

**Final rendering.** When the deliverable claims differ from the claims V1's accepted rendering shows, the track renders once more, leaving out every other claim, through `render_checked` with a fresh post-render hook (V1.9 envelope, V1.4, V1.6, V1.9 band). This is not a correction cycle. If it fails V1, the response is that V1 decision's (invariant 3: no claim verdict carries `v2`).

**Alignment.** The alignment item (4.11) judges the final rendering. When it fails (Type E) and `cycles < MAX_CORRECTION_CYCLES`, the track re-renders only (`presentation=socratic`, the same omissions, a fresh post-render hook), records `V2Correction(kind="re_render")`, increments `cycles` and judges the new rendering again. No new claim plan is made. When it still fails after the cycles, every claim it would have delivered abstains with X2.

**Response:**

| Condition | `final` | `final_reason` |
|---|---|---|
| a kill switch | `abstain` | `v2_kill_switch` (whatever the legacy decision; `replacement` `none`) |
| any `deliver` | `deliver` | None |
| none delivers, any withheld | `withhold` | `v2_degraded_withheld` when a V2 withholding exists, else `conflict_withheld` when every withheld claim is a withheld conflict's, else `d20_interim_withhold` |
| every claim exhausted | `abstain` | `v2_alignment_failed` / `v2_correction_exhausted` |

`replacement` follows `replacement_for(legacy_decision)` for `withhold`.

**V3 intents (`V3IntentV2`):** the Phase 4 reasons, except that `v1_3_flag` is dropped when the claim's V2 vote completed (`pass` or `fail`: "after Phase 5, flags route to V2"); `v2_degraded_withheld` for a V2 withholding; `v2_correction_exhausted` with escalation `X2`.

**Labels:** Phase 4's, plus `degraded` per 3.3.

**Mode `shadow`:** the finals, `final_reason`, `replacement` and V3 intents are exactly Phase 4's (each `V3Intent` re-validated as `V3IntentV2`), with `v2` set for each eligible claim. `V2ShadowSummary` counts what `on` would decide with no correction (pass → would_deliver, fail → would_fail, withheld → would_withhold). A disagreement between the response-level would-final and the V1 final logs `tutor.v2.disagreement` (`v1_final`, `v2_would`) and is counted.

### 4.15 Evidential cache (`v2_panel/cache.py`; task 5.7, AC-5-8, AC-5-11, R-47)

```python
class EvidentialCache(Protocol):
    def get(self, kind: Literal["claim_plan", "verdict"], key: str): ...

    def put(self, kind: Literal["claim_plan", "verdict"], key: str, value: ClaimPlan | AdapterVerdict) -> None: ...   # any other type: TypeError


class DatabaseEvidentialCache:  # the process cache: shared by every instance (evidential_cache_entries); bounds from v4 gateway.cache
    ...


class ProcessEvidentialCache:   # thread-safe; one LRU per kind in process memory: a test's or the fixture runner's own cache
    ...
```

The bounds are v4 `gateway.cache.max_entries`: 1024 claim plans and 8192 verdicts.

- **Claim-plan key:** `canonical_sha256({"kind": "claim_plan", "envelope_sha256": canonical_sha256(envelope), "corpus_version", "config_package_version", "config_package_sha256", "generator_id", "generator_model_id", "evidential_prompt_hash"})`. The envelope holds the resolved text and the lesson-scoped evidence (M17), so the same question under another lesson scope misses.
- **Verdict key:** `canonical_sha256({"kind": "verdict", "claim_text_sha256", "span_id", "span_content_hash", "verifier_adapter_id", "verifier_model_id", "verifier_model_version", "verifier_prompt_hash", "tool_contract_version", "resolved_question_sha256", "corpus_version", "config_package_version", "config_package_sha256", "generator_id", "generator_model_id"})`: conflict 3's union key.
- No learner identifier, thread id, response id or learner text is in a key (hashes only) or a value: a value's only text is corpus text (a claim plan's claim texts, which the one wired generator quotes from the bundle's spans; a verdict holds a span id and enumerations). The shared cache stores each key only as `keyed_digest(key, "evidential-cache")` (an HMAC with the guest-token secret, so a stored key cannot be matched against a guessed question) and each value as the canonical JSON of its `ClaimPlan` or `AdapterVerdict`; a hit refreshes the entry's `used_at`, and a put evicts the least recently used entries beyond the kind's bound. No key is logged or exported.
- **Claim plans:** only generation 1's proposal is read from and written to the cache (a V1 regeneration and a correction candidate bypass it); only a wired generator's plan (`plan_cacheable`: the generator is the package's `GENERATORS` class for its id; a test double sharing a wired ref never is); a cached plan whose candidate hard-fails V1.9 or V1.1 is evicted; in V1 shadow, Phase 3's first proposal is written after validation.
- Rendered text, alignment verdicts and ledger entries are never cached. A configuration bump changes `config_package_sha256`, and a model change changes `verifier_model_version`; either misses.
- `get_cache()` returns the shared cache when the package names the database scope (v4 `gateway.cache.scope`), else a per-process one (a package without a gateway block). Every instance reads and writes the same entries; a configuration bump or a model change misses everywhere, and stale entries leave by the bound. The table starts empty with its migration (plan G "cold cache"). `reset_process_cache()` is the test seam: a new cache object and an empty table. With the V2 mode off no cache is read or written.
- **A store fault is a miss.** When the shared table cannot be read or written, `get` returns `None` (counted as a miss) and `put` and `evict` do nothing; each logs `tutor.v2.cache_unavailable` (`operation` `get`, `put` or `evict`). A database fault costs calls, never the response or its record (F-1); a wrong value type is still a `TypeError`.

### 4.16 Pipeline integration (`tutor_pipeline/pipeline.py`, `v1_checks/runner.py`)

**`TwoPassPipeline.__init__`** gains keyword-only arguments `gateway=None`, `adapter_registry=None`, `cache=None`, `tool_host=None` and `v2_clock=time.monotonic` (the corpus registry keeps the name `registry`). An explicit `v2_hook` takes precedence: with it the pipeline builds no V2 track and `v2_mode()` is `off`. Otherwise, while the V2 mode is not off, each run uses the injected parts, else `get_gateway()` (the process gateway, read per run and never kept on the pipeline, 4.17), `registry_for(package, settings)`, `get_cache()` and `ToolHost.default(pipeline, gateway)`.

**`run()`** computes `v2_mode = pipeline.v2_mode()` beside the V1 mode: with `v2_mode == "off"` every path is Phase 4's, byte for byte (13.1 test 20); otherwise `_v1()` builds `V2Track(self, ctx, mode=v2_mode, …)` and passes it as `V1Track(v2_hook=…, cache=…)` (the claim-plan cache in V1 enforce only). In V1 enforce with `v2_mode == "on"`, the record's `decision` is `"abstain"` iff `v1.record.final == "abstain"`, with `abstention_reason` the record's `final_reason`, else `"answer"`; `rendered`, `presentation` and `rendered_text_sha256` are the final rendering's.

**`V1Track`:** `run` measures V1 latency without the V2 time; with a V2 track it runs the 4.13 loop and `build_record_v2(...)`, and a run whose candidates never passed V1 gives a V2 block with `panel_reached` false and no claim verdict (the AC-5-5 record). `_decide(..., state, *, regenerate=True)` makes one attempt with `regenerate=False`. `_render(..., state, *, presentation=None, omit_extra=frozenset())` judges a rendering with a fresh post-render hook from the candidate's pre-render results. Under `on`, the rendering's withheld set leaves out V1.3 flags (`withheld_claim_ids(results, disclosure, v1_3_routes_to_v2=True)`; the keyword defaults to `False`, Phase 4's set).

**`_entry_v3`** builds a `LedgerEntryV3` with `ProvenanceV3` (the three versions from the block) and `PipelineCountsV2`. `_finish` is unchanged, and the append goes through the same ledger path. `budget_over` gains step `"verify"`.

### 4.17 Effective mode, the process gateway and start-up (`v2_panel/__init__.py`, `gateway/gateway.py`, `gateway/package_check.py`, `main.py`)

**`v2_panel.mode(settings, package, *, gateway=None)`** returns `off` when the package has no gateway, v2 or tools block, when `gateway.GATEWAY_UNAVAILABLE_REASON` is set, when `tutor_shadow.effective_mode(settings, package) == "off"`, when `v1_checks.mode(...) == "off"`, when `settings.model_gateway == "off"`, or, after those checks, when the given gateway (else the process gateway, which the call then builds) is stopped after a `refresh()` (its own stop or the registry's shared stop, 4.5), so a build whose V2 mode is off by its settings builds no gateway and reads no stop; `shadow` when the setting is `on` but the V1 mode is `shadow` (logging `tutor.v2.on_downgraded` once; Settings refuse this combination, so it is defence in depth); the setting otherwise.

**`get_gateway()`** returns the one process gateway: it holds the state, the stop, the secret flag, the budget and the metrics. Everything per pipeline or per call is passed per call. Its budget is the package's `daily_units` for this process's registry, kept in the shared `DatabaseBudget` (4.4), and its stop store is the registry's `DatabaseStopStore` (4.5); it adopts a recorded stop when it is built.

**`check_gateway_package(package, *, structural) -> list[str]`** checks that the committed tool-contract file exists, its canonical sha256 equals `tools.sha256`, and `tools.version` and `tools.servers` are the code's; the `v2.prompt` hashes equal `verifier_prompt_hash()` and `alignment_prompt_hash()`; `v2.voting.matrix == ROUTING_TABLES[v2.routing_table_version]`, and the weights, tier rule, alignment rule and `max_members` are the code's; every fake rule is in `WIRED_FAKE_RULES = {"verbatim-support-v1"}`; `generator_families` covers `WIRED_GENERATORS`; `retired_settings == RETIRED_PROVIDER_SETTINGS`. With `structural=True` (tests and `config_package.py --check` only) it also checks that the committed tool-contract file equals `tool_contract_document()`. Start-up never compares a generated JSON Schema (M21).

**`main._check_tutor_pipeline_package`** calls `_check_gateway_package(package)` after `_check_v1_package`. With a package without a gateway block, `GATEWAY_UNAVAILABLE_REASON = None` and the mode is off. A pinning problem never reaches this check: the loader refuses it in every build (AC-5-10). Any other problem raises `ConfigPackageError("gateway: …")` when the build is governed and the gateway is requested (`MODEL_GATEWAY` not `off`); otherwise it sets the reason (`/ready` `gateway.available` false) and logs `tutor.v2.unavailable` (WARNING). Outside development `MODEL_GATEWAY` is `off`, so such a problem never stops production start-up. It reads only the package, the committed files beside it and code values, and writes nothing.

**`lifespan`** calls `_warn_retired_provider_settings()`: when `retired_settings_present()` is non-empty, it logs `gateway.retired_setting` (`names`, upper-case environment names only) at WARNING.

### 4.18 Legacy provider retirement (E3)

- **`teaching_assistant.py`:** every member listed in M2 is deleted, with the `google.auth` try-import, `VERTEX_AI_SCOPE`, `import os`, `import httpx` and the unused imports. `chat` and `pipeline` are unchanged. The module docstring says the class answers with D-19 containment and that model egress belongs only to `app.gateway`.
- **`config.py`:** `openai_chat_model`, `vertex_ai_api_key`, `vertex_ai_project_id`, `vertex_ai_location` and `vertex_ai_chat_model` are deleted, and so are `openai_embedding_model` and `openai_embedding_model_version` (the embedding model is `gateway.embeddings`, 4.19). With `extra="ignore"`, a deployed environment that still sets them starts unchanged. `OPENAI_EMBEDDING_MODEL` is not in `RETIRED_PROVIDER_SETTINGS`, because the API's developer env template still assigns it and no agent may edit that file (DI-88): it is ignored without a start-up line.
- **`gateway/retired.py`:** `RETIRED_PROVIDER_SETTINGS = ("OPENAI_CHAT_MODEL", "VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL", "VERTEX_AI_LOCATION", "VERTEX_AI_PROJECT_ID")`; `retired_settings_present()` names those set in `os.environ`; `retired_secret_values()` returns the `VERTEX_AI_API_KEY` value, for redaction only. No file is opened, so a retired key kept only in a `.env` file is neither named nor masked, and no code reads it (the field is gone, and Settings ignore unknown keys).
- **`main.py` and `workers/common.py`:** `install_log_redaction([*retired_secret_values(), *provider_secret_values(), settings.pinecone_api_key, …])` (4.3).
- **Proof that no production path reached the removed code** (13.1 test 25): an AST scan finds no definition or attribute use of the removed names in `apps/api/app`, `scripts`, `apps/api/alembic` and `evaluation`; `TeachingAssistantService.chat` and `/assistant/chat` answer with `provider == "none"` while `VERTEX_AI_API_KEY` is set, and the network guard records no attempt; the legacy contained bodies equal the Phase 4 golden (test 33).

### 4.19 Embedding egress (`gateway/embeddings.py`; plan 7.1, 7.6; D-23; R-06; conflicts 10, 29, 36)

The Phase 2 semantic backend embeds its index entries and its queries only through the gateway; no Settings field holds `OPENAI_API_KEY` or names the embedding model. Its parameters are package v4's `gateway.embeddings` (`registry.EmbeddingSpec`, provisional, PD-26): `provider` `openai-embeddings`, `secret_ref` `OPENAI_API_KEY`, `model_id` and `model_version` (both `null`: no embedding model is chosen while D-07, D-12 or Q-09 is open or the Q-15 review is pending; a named model must be pinned, and the loader refuses an unpinned one, AC-5-10), `caps` (`max_items` 256 inputs per request, `max_input_chars` 8000 per input, the token cap, since the gateway holds no tokenizer; `timeout_ms` 10000; `max_retries` 2) and `cost_units_per_item` 1. `/ready` reports its provider, model id and version (10.2).

- **`embedding_problem(settings, package, *, secret_store=None, gateway=None) -> str | None`** names why no provider embedder may run; the first check that fails gives the reason (`EMBEDDING_PROBLEMS`): `egress_not_opted_in` (`MODEL_EGRESS_PROVIDERS` does not name `openai-embeddings`, D-23); `provider_open` (the package has no gateway block or no `gateway.embeddings`, or `registry.providers_open(owner_decisions)`: D-12 or D-07 is `open`, Q-09 is `unresolved`, or Q-15's `state` is not `reviewed`, a decision the package does not hold counting as open; the loader applies the same function to every non-fake member, 5.2); `unpinned` (`gateway.embeddings` names no model, or `pin_problem` refuses it, 4.1); `no_budget` (the registry's daily units are 0); `gateway_stopped` (the process gateway, refreshed, is stopped); `not_configured` (the secret store holds no `OPENAI_API_KEY`); and last `learner_text`: the backend embeds every query, and a query embedding sends the learner's query text, which plan H never lets leave (conflict 36). So `embedding_problem` never returns `None`: with the shipped package the reason is `provider_open` once an environment opts in, and `learner_text` would remain once every other check passed. **`embedder_for(settings, package, *, store=None, …)`** returns the `OpenAIEmbeddingAdapter` when there is no problem, else `None`; it always returns `None`.
- **`OpenAIEmbeddingAdapter(spec, *, store, secret_store, gateway=None, transport=None, corpus_registry=None, sleep=time.sleep)`**, like `HttpJsonAdapter`, is exercised only through `httpx.MockTransport`; it refuses a spec with no pinned model. `embed_query(text)` and `embed_documents(texts)` (batches of `caps.max_items`) post `{"model", "input", "encoding_format": "float"}` to `EMBEDDINGS_ENDPOINT` (https, no query). Before any attempt a request runs: `gateway.refresh()` (the shared stop another instance wrote is adopted before every request, so a stop written during an index sync stops the next batch), the secret flag, the stop (`stopped`), the payload policy (`PayloadPolicy.check_embedding` over the adapter's `store` and its corpus registry: a query item is refused, and so is a document that is not a public, quotable index entry's excerpt; a violation stops the gateway, `payload_violation`), then the caps (more than `max_items` inputs or an input over `max_input_chars` is `invalid_request`, nothing sent, no stop). Then up to `1 + max_retries` attempts with `httpx.Client(timeout=caps.timeout_ms)`: each attempt first reserves `len(inputs) * cost_units_per_item` from the gateway's daily budget (a refusal stops the gateway, `budget_breach`, kind `budget`; a budget store that cannot be written is `budget_unavailable`, nothing sent, no stop), and the key is read from the secret store, registered with the redaction (owner `gateway`) and sent only as `Authorization: Bearer`. Timeouts, transport errors and 429/500/502/503/504 are retried; the reply must hold one float vector per input (`data[].index`, `data[].embedding`), returned in input order. Every failure raises `EmbeddingError(kind, status)`, `kind ∈ {"http_status", "timeout", "transport", "invalid_output", "invalid_request", "no_key", "stopped", "budget", "budget_unavailable", "payload_violation"}`, after its `except` block (no cause, no context, no key, URL or header in its text).
- **`PineconeSemanticBackend(store, settings, *, embedder=None)`** asks the gateway (`embedding_problem`, `embedder_for` with its store); an `embedder` passed in is a test's in-process embedder, which needs no egress check. `enabled` is the setting, the vector index's SDK, key and name, and no embedding problem; `egress_refused` is the setting with the problem `egress_not_opted_in`. `RetrievalEngine(store, settings, *, embedder=None)` passes it on. `RetrievalEngine.semantic_inactive_reason` is the embedding problem, else `not_configured` when the vector index is not configured, else `not_aligned`, or `None` when the setting is off or retrieval is hybrid. `sync_semantic_index` logs `gateway.egress_refused` (`consumer` `semantic-retrieval`, once per process) when the setting is on without the opt-in.
- **Start-up.** `main._warn_semantic_inactive()`, called by `lifespan` after the course store is built, logs `semantic.inactive` with `reason` and that reason's `SEMANTIC_INACTIVE_MESSAGES` text (one per `EMBEDDING_PROBLEMS` entry, `learner_text` included, and `not_aligned`) when the setting is on and retrieval stays lexical.

---

## 5. Configuration package v4 (`apps/api/app/config_package/v4.json`)

### 5.1 File

**v4 is a copy of v3 with:** `package_version "4.0.0"`, `schema_version 4`, `phase "5"`, `created` (the build date); `supersedes {"package_version": "3.0.0", "sha256": "116504d45d14b1048eeed5ccba0a62f16c92ccdb9b72618bd4ca65b97813a153", "readable_until": "the release after the Phase 5 merge"}`. Every v3 block is unchanged, except as listed below.

**`tutor_pipeline` changes:** `schemas` adds five pins: `LedgerEntryV3` (`ledger-entry-v3`, `schemas/ledger-entry.v3.schema.json`), `V2VerdictRequest` (`v2-verdict-request-v1`), `V2AlignmentRequest` (`v2-alignment-request-v1`), `V2AdapterVerdict` (`v2-adapter-verdict-v1`) and `V2AlignmentVerdict` (`v2-alignment-verdict-v1`). `ledger.entry_schema` is `"ledger-entry-v3"` (the newest record the code writes; with `MODEL_GATEWAY` off it writes v2, as package v3 named v2 while V1 off wrote v1), and `entry_schemas` is `["ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3"]`. `unused_provenance_fields` is `[]`: the list describes the package's entry schema, as in v1 to v3, and `ledger-entry-v3` fills every provenance field; a `ledger-entry-v2` record written under v4 with `MODEL_GATEWAY` off keeps the three Phase 5 fields null, as a `ledger-entry-v1` record under v3 kept `v1_3_checker_model_id` null.

**New block `gateway`** (`provisional: true`, `status "provisional"`, `version "gateway-v1"`, `authority` naming PD-22, PD-24, PD-26, PD-27 and DI-76):

```json
"gateway": {
  "pinning": {"rule": "pinned-version-v1", "refused_tokens": "alias|auto|current|default|exp\\d*|experimental|latest|nightly|preview\\d*",
              "refused_within_token": "preview|latest|nightly|experimental|exp\\d*$", "version_pattern": "…PINNED_VERSION…",
              "dates": "calendar-valid", "canonical_form": "no surrounding whitespace in the model id or the version",
              "applies_to": "every member of every registry; …"},
  "egress": {"opt_in": "per_environment_per_provider", "setting": "MODEL_EGRESS_PROVIDERS", "default": [], "provisional": true, "record": "PD-22"},
  "registries": {
    "development": [
      {"adapter_id": "fake-alpha-v1", "family": "fake-alpha", "provider": "fake", "model_id": "fake-alpha-verifier",
       "model_version": "2026-11-21", "capabilities": ["verify"], "caps": {"max_tokens": 256, "timeout_ms": 500, "max_retries": 1},
       "cost_units_per_call": 1, "fake": {"rule": "verbatim-support-v1"}},
      … fake-beta-v1, fake-gamma-v1 (verify) and fake-delta-v1 (capabilities ["generate", "verify"]; not the package's generator; the spare family)
    ],
    "staging": [], "production": [], "default": []},
  "budgets": {"provisional": true, "scope": "database", "unit": "cost-unit",
              "daily_units": {"development": 100000, "staging": 0, "production": 0, "default": 0},
              "alert_share": {"numerator": 4, "denominator": 5}, "record": "PD-26; hold H9 (DI-72)"},
  "cache": {"provisional": true, "scope": "database", "key_rule": "plan-5.7-envelope-union-7.3-v1",
            "max_entries": {"claim_plan": 1024, "verdict": 8192}, "record": "PD-27"},
  "embeddings": {"provisional": true, "record": "PD-26", "consumer": "semantic-retrieval", "provider": "openai-embeddings",
                 "secret_ref": "OPENAI_API_KEY", "model_id": null, "model_version": null, "model_note": "…",
                 "caps": {"max_items": 256, "max_input_chars": 8000, "timeout_ms": 10000, "max_retries": 2}, "cost_units_per_item": 1},
  "payload_policy": {"rule": "public-quotable-spans-and-templates-only-v1", "on_violation": "stop"},
  "stop": {"on": ["budget_breach", "payload_violation", "secret_in_logs"], "action": "gateway_stopped_then_off_security_event",
           "scope": "database", "clear": "operator"},
  "retired_settings": ["OPENAI_CHAT_MODEL", "VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL", "VERTEX_AI_LOCATION", "VERTEX_AI_PROJECT_ID"],
  "terms": null
}
```

**The fake rule `verbatim-support-v1`.** A claim item gets `SUPPORTED` iff the NFKC-casefolded, whitespace-collapsed claim text is a substring of the same fold of the span text, otherwise `NOT_ENOUGH_INFO` with EHMF `B`. An alignment item gets rating 4, no leakage. No network call is made.

**New block `v2`** (`provisional: true`, `version "v2-panel-v1"`): `panel` `{"max_members": 3, "one_vote_per_family": true, "order": "registry", "eligibility": "before_panel", "generator_excluded": true, "blind": true}`; `generator_families` `{"extractive-d19-v1": "extractive-d19"}`; `verdicts` (the three) and `objection` `["CONTRADICTED", "NOT_ENOUGH_INFO"]`; `prompt` `{verifier_prompt_id, verifier_prompt_hash, alignment_prompt_id, alignment_prompt_hash}`; `tiers` `{"provisional": true, "rule": "context-tier-v1", "assessment_context": 1, "default": 2, "expert_mode": null, "record": "PD-25"}`; `voting` `{"provisional": true, "matrix": RULE_MATRIX (string tier keys), "tier3_threshold": {"numerator": 2, "denominator": 3}, "provisional_until": "Q-22 (DI-52)", "record": "PD-23, PD-25"}`; `panel_weights_version "equal-weights-v1"`, `routing_table_version "degraded-matrix-v1"`; `correction` `{"provisional": true, "max_cycles": 2, "type_e": "re_render_only", "other": "revise_or_reverify_unchanged", "exhausted": "abstain_mark_x2", "critical_registry": [], "record": "PD-29"}`; `degraded` `{"provisional": true, "zero": "pre_verified_or_abstain_queue", "pre_verified_source": null, "banners": {"degraded-reduced-2-v1": "Fewer independent checks than usual verified this answer.", "degraded-reduced-1-v1": "Parts of this answer are held back until more checks are available.", "degraded-zero-v1": "Verification is unavailable right now, so only quoted course passages or no answer is shown."}, "record": "PD-30"}`; `alignment` `{"provisional": true, "rule": "1ooN-leakage-v1", "objective_source": "lesson_summary", "band_source": "v1.v1_9.readability", "rating_gates": false, "record": "PD-25"}`.

**New block `tools`:** `{"version": "mcp-tools-v1", "transport": "in-process", "servers": ["analytics", "citation", "corpus", "learner", "verification"], "path": "schemas/tool-contracts.v1.json", "sha256": "<canonical sha256 of the committed file>", "provisional": true, "record": "PD-31 (…); DI-86"}`: the tool names and the transport are this phase's own (conflict 18; plan 7.4 A-18), recorded as PD-31, and the paper's tool names are DI-86.

**`flag_policy` adds** `"model_gateway": {"values": ["off", "shadow", "on"], "default_development": "shadow", "default_elsewhere": "off", "on_requires": "phase5_exit_passed", "on_outside_development": "refused_before_exit", "on_requires_v1": "enforce", "stop": "off_until_cleared", "authority": "plan Phase 5 G, L; 13.6; PD-28"}`, `"phase5_exit_passed": false` and `"phase5_exit_evidence": null`; `flag_policy.authority` adds PD-28 and DI-76.

**`owner_decisions` adds:** `D-07` `{"state": "open", "option": "(a) Table XIV rule, pinned", "applied": "pinned-version-v1 (rule only; no model chosen)", "ratified": false, "record": "PD-24; DI-69; hold H8"}`; `Q-09` `{"state": "unresolved", "terms": null, "record": "DI-70; A-11"}`; `D-23` `{"option": "RECOMMENDATION", "text": <18.4 text>, "applied": "MODEL_EGRESS_PROVIDERS, default []", "ratified": false, "record": "PD-22"}`; `D-29` `{"state": "open", "applied": "(a)", "text": <18.4 text>, "ratified": false, "record": "PD-23"}`; `D-25` `{"state": "open", "registry": [], "record": "PD-29"}`; `A-15` `{"state": "open", "budgets": "0 outside development", "hold": "H9 blocks the P5 panel until an approved budget is filed", "record": "PD-26; DI-72"}`; `Q-15` `{"state": "owner review pending", "register": "docs/security/payload-register.md", "record": "DI-71"}`. `D-12` is unchanged, and so is its `PLAN-3.3` deviation. `Q-22.provisional_values` adds `"v2.voting"`, and `Q-22.record` adds PD-25.

**New files:** `v4.json.sha256`; `schemas/ledger-entry.v3.schema.json`; `schemas/v2-verdict-request.v1.schema.json`; `schemas/v2-alignment-request.v1.schema.json`; `schemas/v2-adapter-verdict.v1.schema.json`; `schemas/v2-alignment-verdict.v1.schema.json`; `schemas/tool-contracts.v1.json`. `v3.json`, `v2.json`, `v1.json`, their sidecars and the nine existing schema files are byte-unchanged.

### 5.2 Loader (`app/core/config_package.py`)

**Paths.** `DEFAULT_PACKAGE_PATH` is `v4.json`, and `V3_PACKAGE_PATH` is added.

**Schema versions.** `schema_version in (1, 2, 3, 4)`. Schema 4 applies every schema-3 rule with `TUTOR_SCHEMA_NAMES_V4`, `entry_schemas == LEDGER_ENTRY_SCHEMAS_V4` and `unused_provenance_fields == []` (its message: "its entry schema, ledger-entry-v3, fills every provenance field"). `GatewayParams` holds `budget_scope`, `stop_scope` and `cache_scope` (each `database`) and `embeddings` (an `EmbeddingSpec`, 4.19). `ConfigPackage` gains `gateway: GatewayParams | None = None`, `v2: V2Params | None = None` and `tools: ToolParams | None = None`. `FlagPolicy` gains `phase5_exit_passed: bool = False` and `phase5_exit_evidence: str | None = None`; its two existing fields are unchanged.

**`_parse_gateway` refuses** (each refusal is structural): an unmarked provisional block; a pinning rule other than `pinned-version-v1`, or `refused_tokens`, `refused_within_token` or `version_pattern` texts other than the code's; an egress block other than `MODEL_EGRESS_PROVIDERS` with default `[]`; a missing owner decision of D-07, Q-09, D-23, D-29, D-25, A-15 or Q-15; a registry name outside `{development, staging, production, default}` or no `default`; a malformed `adapter_id` or `family`, or a duplicate `adapter_id`; `pin_problem` on any member (AC-5-10), with a message naming the adapter and "unpinned"; capabilities outside `{generate, verify}`; caps outside the 3.1 bounds, or a verifier whose `timeout_ms * (1 + max_retries)` exceeds the shadow budget; a negative cost; a fake member without a wired rule, or with an endpoint, auth header or secret, or a non-fake member with a fake rule; a fake member in any registry but `development`; a non-fake member anywhere while `registry.providers_open(owner_decisions)` holds (`D-12` or `D-07` open, `Q-09` unresolved, or `Q-15`'s review not done; a decision the package does not hold counts as open: the one rule the embedding egress shares), and a non-empty `staging`, `production` or `default` registry under the same conditions; an endpoint with a query, userinfo, a fragment or a non-https scheme; a `secret_ref` that is not an upper-case environment name; `daily_units` that do not name every registry, or a non-zero value outside development while `A-15` is open (hold H9); an `alert_share` other than 4/5 (plan I); a budget `scope` other than `database`; an unmarked cache, a cache `scope` other than `database`, or cache bounds outside 1-100000; a payload policy that does not stop on a violation; stop reasons other than the three, or a stop `scope` other than `database` or a `clear` other than `operator`; `retired_settings` not equal to `RETIRED_PROVIDER_SETTINGS`; `terms` other than `null` while Q-09 is unresolved; a missing `gateway.embeddings`, or one that is unmarked (`provisional: true`, `record` PD-26), names another provider or secret reference, lacks `model_id` or `model_version`, names a model that `pin_problem` refuses ("gateway.embeddings is unpinned…", AC-5-10) or any model while `providers_open` holds, has caps outside `max_items` 1-2048, `max_input_chars` 1-32000, `timeout_ms` 50-10000 or `max_retries` 0-2, or a `cost_units_per_item` below 1.

**`_parse_v2` refuses:** an unmarked provisional block; `max_members` other than 3; a `generator_families` entry set that does not cover `WIRED_GENERATORS`, or that names a registry family; an unmarked `tiers` block, an `assessment_context` tier other than 1 or a `default` tier outside 1-3; an unmarked `voting`, `correction`, `degraded` or `alignment` block; a `routing_table_version` that is not one of `ROUTING_TABLES`, a voting matrix other than that table, or, while D-29 is open, any table but `degraded-matrix-v1`; a `tier3_threshold` that does not hold integers with `0 < num <= den`, or, while Q-22 is unresolved, any threshold but `TIER3_THRESHOLD` 2/3 (the record rule re-tallies with it); `max_cycles` other than 2; a `type_e`, `other` or `exhausted` correction rule other than `CORRECTION_RULES`'s; a non-empty `critical_registry` while D-25 is open; a `pre_verified_source` that is not `null` (no store exists, DI-83); banner ids other than `BANNER_IDS`, or empty banner texts.

**`_parse_tools` refuses** an unmarked provisional block (A-18, PD-31), a version other than `mcp-tools-v1`, servers other than the five, a transport other than `in-process`, a path that is absolute or holds `..`, or a `sha256` that is not 64 hex characters.

**`_parse_flag_policy` (schema 4):** `model_gateway`'s values and defaults must equal the code constants `MODEL_GATEWAY_DEFAULT_DEVELOPMENT` and `MODEL_GATEWAY_DEFAULT_ELSEWHERE`, with `on_requires` `phase5_exit_passed` and `on_requires_v1` `enforce`; `authority` names PD-28 and DI-76; `phase5_exit_passed` must be a boolean, and when it is true, `phase5_exit_evidence` must be a string.

### 5.3 Package checks

**`tutor_pipeline/package_check.py`:** `entry_model` is `LedgerEntryV3` for schema 4 or later; the entry-schema comparison is per schema (schema 3 requires `["ledger-entry-v1", "ledger-entry-v2"]`, schema 4 `sorted(ENTRY_SCHEMAS)`; M8); `model_schema` imports `app.gateway.contracts` before reading `SCHEMA_MODELS` (3.3); its module docstring names v4 as the shipped package.

**`gateway/package_check.py`:** as in 4.17.

### 5.4 Scripts (`scripts/config_package.py`)

- `--check` also runs `check_gateway_package(package, structural=True)` for schema 4 and prints a gateway summary line (registries and member counts, budgets, tools version, routing table, `phase5_exit_passed`).
- `--rehash` for schema 4 also recomputes the tool-contract file's sha256 and the two prompt hashes (the schema pins, the V1 hashes and the fixture pin as for v3).
- `--write-schemas` writes the fourteen pinned schemas plus the tool-contract document for v4; the nine v3 files come out byte-identical in content.
- The default path is v4.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `MODEL_GATEWAY` | `Literal["off", "shadow", "on"] \| None = None`. `None` means `"shadow"` in development and `"off"` elsewhere (`MODEL_GATEWAY_DEFAULT_DEVELOPMENT`, `MODEL_GATEWAY_DEFAULT_ELSEWHERE`, which v4 `flag_policy.model_gateway` must name) | E9 and plan L "Flag off returns to Phase 4". `off` outside development, so no egress and no change. `shadow` acts on the two-pass shadow pipeline only, which is off outside development (`TWO_PASS_TUTOR`); with it off the effective mode is `off` (4.17). Set outside development, `shadow` logs `config.override` and can make no call (empty registry, budget 0). |
| `MODEL_EGRESS_PROVIDERS` | `Annotated[list[str], NoDecode] = []`; a comma or JSON list; each entry `[a-z0-9][a-z0-9-]{0,63}` | D-23 (PD-22). Empty everywhere, so no non-fake provider and no embeddings call is possible without an explicit per-environment entry (and the gateway gives no embedder in any case, 4.19). |
| `MODEL_GATEWAY_DISABLED_ADAPTERS` | `Annotated[list[str], NoDecode] = []` | 13.6 "kill switches per provider" (strictly more conservative) |
| `MODEL_GATEWAY_KILL_SWITCH` | `Literal["none", "abstain_only", "pre_verified_only"] = "none"` | 13.6 "abstain-only, pre-verified-only". Every adapter becomes ineligible, so the ZERO path runs with no call, and under `on` the record abstains (4.10; strictly more conservative). It acts on the two-pass shadow pipeline only, like `MODEL_GATEWAY`. |

The retired settings are listed in 4.18. `openai_api_key` is no setting either: the gateway's SecretStore reads `OPENAI_API_KEY` (4.19); nor are `openai_embedding_model` and `openai_embedding_model_version`: the embedding model is package v4's `gateway.embeddings` (4.19).

**Validator additions** (after the `v1_pipeline` block): if `model_gateway is None`, the default applies; `model_gateway == "on"` and `v1_pipeline != "enforce"` gives a `ValueError`: "MODEL_GATEWAY=on needs V1_PIPELINE=enforce (V2 consults only the V1 track's own V1Passed)"; outside development, `model_gateway == "on"` reads the package lazily and refuses while `flag_policy.phase5_exit_passed` is false: "MODEL_GATEWAY=on is refused outside development before the Phase 5 exit (configuration package flag_policy.phase5_exit_passed is false; plan Phase 5 G, P). Use off or shadow.", and refuses unless the package is the shipped, hash-verified one. In development, `on` is allowed; it acts only on the shadow pipeline.

**`main._record_configuration_overrides`** adds `("model_gateway_shadow", settings.model_gateway == "shadow")`, `("model_gateway_on", settings.model_gateway == "on")` and `("model_egress_opt_in", bool(settings.model_egress_providers))`. Under production defaults its details are unchanged.

**`infra/cloudrun/api-production.env.example.yaml`** adds a Phase 5 comment block, then `MODEL_GATEWAY: "off"`, then `MODEL_EGRESS_PROVIDERS: "[]"`. `OPENAI_API_KEY` (read by the gateway, 4.19) and `PINECONE_API_KEY` stay. The comment says that the VERTEX_AI_* and OPENAI_CHAT_MODEL variables are retired (if one is set, start-up logs its name) and that the value of any retired key is still redacted.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/gateway/`

| Module | Contents |
|---|---|
| `__init__.py` | Docstring (the only egress module; D-12/D-07/Q-09 open and the Q-15 review pending; registries empty outside development; no embedder), `GATEWAY_UNAVAILABLE_REASON`, lazy re-exports |
| `contracts.py` | 3.1 request and verdict contracts, the tool servers' small contracts, the identifier pattern; their `SCHEMA_MODELS` registration |
| `pinning.py` | 4.1 |
| `registry.py` | `Caps`, `AdapterSpec`, `EmbeddingCaps`, `EmbeddingSpec`, `AdapterRegistry`, `registry_for`, `generator_family`, `GeneratorFamilyUnknown`, `providers_open` and `PROVIDER_GATES` |
| `adapters.py` | `ModelAdapter` Protocol (`spec`, `available()`, `verify(request) -> dict`, `align(request) -> dict`), `FakeAdapter` (`script`, `down`, `late_ms`, `calls`, `record`), `HttpJsonAdapter`, `AdapterError`, `project_verdict`, `project_alignment` |
| `embeddings.py` | 4.19: `embedding_problem`, `embedder_for`, `providers_open`, `OpenAIEmbeddingAdapter`, `EmbeddingError`, `Embedder` |
| `secrets.py` | `SecretStore`, `EnvironmentSecretStore`, `PROVIDER_SECRET_REFS`, `provider_secret_values` |
| `egress.py` | `egress_allowed`, the one-time refusal log |
| `budget.py` | `DailyBudget` |
| `controls.py` | `DatabaseBudget`, `DatabaseStopStore`, `stop_rows`, `clear_shared_controls` (4.4, 4.5) |
| `policy.py` | `PayloadPolicy` (`check`, `check_embedding`), `PolicyContext`, `PayloadViolation` |
| `gateway.py` | `ModelGateway` (`verify`, `align`, `eligible`, `ineligible_reason`, `stop`, `refresh`, `state`, `stop_reason`, `stop_store`, `check_secret_flag`, `capture`), `GatewayRefused`, `GatewayStopped`, `budget_unavailable`, `get_gateway`, `process_gateway_stopped`, `process_gateway_state`, `reset_process_gateway` |
| `tools.py` | 4.6 |
| `retired.py` | 4.18 |
| `metrics.py` | `GATEWAY_METRICS`: calls by adapter and outcome, latency (nearest-rank p95 per adapter over the last 1024), cost units, ineligibility and refusals by reason |
| `package_check.py` | `check_gateway_package` |

**Import rule.** No module under `app/gateway/` or `app/services/v2_panel/` imports `learner_record`, `learner_progress`, `learning_intelligence`, `microlearning`, `app.core.auth`, `app.api.routes.*`, `answer_history` or `retrieval_legacy_p1` (13.1 test 24). The loggers are `qcai.gateway` (the `gateway.*` events) and `qcai.tutor` (the `tutor.*` events), the start-up line `gateway.retired_setting` (on `qcai.gateway`) included; the exceptions are the operator's `gateway.stop_status` (on `qcai.worker`) and the API's start-up line `semantic.inactive` (on `qcai.api`) (10.4).

### 7.2 NEW `apps/api/app/services/v2_panel/`

| Module | Contents |
|---|---|
| `__init__.py` | `mode()`, lazy re-exports |
| `rules.py`, `voting.py` | 3.2, 4.9 |
| `panel.py` | `Panel`, `PanelError` |
| `tiers.py` | 4.8 |
| `cache.py` | 4.15: `DatabaseEvidentialCache`, `ProcessEvidentialCache`, the key functions, `plan_cacheable`, `get_cache`, `reset_process_cache` |
| `track.py` | `V2Track`, `V2Outcome`, `ClaimReviser` |
| `aggregate.py` | 4.14: `build_record_v2`, `v1_excluded` |
| `metrics.py` | `V2_METRICS` (10.3) |

### 7.3 MOD (Phase 3/4 modules)

| File | Change |
|---|---|
| `tutor_pipeline/contracts.py` | 3.3: the V2 section; the `verification_problems` factoring (three parameters; the `correct` message; `PHASE4_FINAL_REASONS`); the `ACCEPTED_ABSTENTION_REASONS`, `SCHEMA_MODELS` and `ENTRY_SCHEMAS` entries; the module docstring names the v3 schemas and the shipped package v4 |
| `tutor_pipeline/pipeline.py` | 4.16: constructor injections, the explicit-hook precedence, `v2_mode()`, the `on` decision derivation, `_entry_v3`, the `verify` budget step, the V1-shadow claim-plan write, the docstring's mode table |
| `tutor_pipeline/package_check.py` | 5.3 |
| `tutor_pipeline/evidential.py` | Docstring: the generator interface and the gateway's generate capability (none wired while D-12 is open); `ClaimReviser` is optional |
| `tutor_pipeline/__init__.py` | Docstring names the shipped package v4 |
| `v1_checks/runner.py` | 4.13, 4.16 (a `_RunState` per candidate, `pre_render`, the correction loop, `regenerate`, `presentation`/`omit_extra`, fresh post-render hooks, the claim-plan cache, latency without V2); docstring |
| `v1_checks/aggregate.py` | `v2_outcome`; `withheld_claim_ids(..., v1_3_routes_to_v2=False)`; the module docstring states D-20 with V2 off or in shadow and V1.3 flags routing to V2 under `on`; `V2Hook`'s docstring names the Phase 5 track |
| `services/ledger.py` | `SCHEMA_REVISION` is `20261122_phase5_gateway_controls` (section 8). `_provenance_problems(seq, entry, params, v1, phase5)`: `phase5` is `phase5_blocks(package)` (`(package.v2, package.tools)` or `None`), passed by every caller. The V1 checks apply to `entry_schema in ("ledger-entry-v2", "ledger-entry-v3")`; a v3 record must also match `tool_contract_version`, `panel_weights_version`, `routing_table_version` and `verification.v2.verifier_prompt_hash` with the package. `pending_v3_intents` reads `entry_schema IN ('ledger-entry-v2', 'ledger-entry-v3')` and adds `"escalation"` to v3 rows only; a v2 row's item is unchanged. The module docstring names the shipped package. |
| `services/tutor_followups.py` | Docstring names the shipped package's budgets (v5 since Phase 6 and v4 since Phase 5) |
| `services/retrieval_engine.py` | 4.19: the backend embeds through the gateway (no `langchain_openai` import, no key), `embedder=` on the backend and the engine, `embedding_problem`, `index_configured`, `egress_refused`, `semantic_inactive_reason`, the store passed to `embedder_for`; `sync_semantic_index` logs `gateway.egress_refused` (`consumer` `semantic-retrieval`, once per process) when the setting is on without the opt-in; the module docstring |
| `services/teaching_assistant.py` | 4.18 |
| `core/config.py` | Section 6; the retired fields, `openai_api_key`, `openai_embedding_model` and `openai_embedding_model_version` deleted |
| `core/config_package.py` | 5.2; the module docstring and the `WIRED_GENERATORS` comment |
| `core/log_redaction.py` | `owner=`, `add_secret_listener` (4.3) |
| `main.py` | `_check_gateway_package`, `_warn_retired_provider_settings`, the redaction values (`provider_secret_values`), `/ready` (10.2), overrides (6); `_warn_semantic_inactive` (4.19) |
| `workers/common.py` | Redaction values (4.18) |
| `workers/gateway_stop.py` (new) | The operator's read and clear of the shared stop (4.5) |
| `db_models.py` | `GatewayBudgetDay`, `GatewayStop`, `EvidentialCacheEntry` (section 8) |
| `alembic/versions/20261122_phase5_gateway_controls.py` (new) | Section 8; the Phase 3 revision's docstring names it as the next revision |

### 7.4 NEW scripts and data

- `scripts/run_v2_fixtures.py` (12.1); `docs/evaluation/phase5/v2_fixture_report_v1.json` and `docs/evaluation/phase5/README.md`.
- `scripts/capture_public_payloads.py` and `apps/api/tests/data/phase4_public_payloads_v1.json` (12.2).

### 7.5 MOD scripts and records

| File | Change |
|---|---|
| `scripts/config_package.py` | 5.4 |
| `scripts/run_v1_fixtures.py` | Both `Settings(...)` add `model_gateway="off"`: its report measures V1 alone (Phase 4 evidence) |
| `docs/evaluation/phase4/v1_fixture_report_v1.json` | Re-written (`--write --allow-dirty`) at the last code commit: `config_package` 4.0.0 and its sha256, `inputs`, `created_at`, `commit` and latency change; every class, final and answer-rate value stays equal |
| `docs/evaluation/phase3/three_plan_replay_v1.json` | Re-written: production settings, so the gateway is off; decision, count and hash-equality columns unchanged; package and `inputs` change |
| `docs/evaluation/phase4/README.md` | Names the shipped package that pins the fixture hash (v3 from the Phase 4 release, v4 from the Phase 5 release) |
| `.github/workflows/ci.yml` | Section 14 |
| `infra/cloudrun/api-production.env.example.yaml` | Section 6 |
| `infra/cloudrun/provider-key-rotation.md` | The API no longer reads `VERTEX_AI_API_KEY` (Phase 5 retired the code); the D-23 opt-in exists (`MODEL_EGRESS_PROVIDERS`); rotation stays a D-05 cloud write; removing the secret from the service is DI-81 |
| `.gitattributes` | `docs/architecture/phase5-implementation-spec.md text eol=lf` |

### 7.6 Text that describes the code (P2-12-D-03; no behaviour change)

These texts are edited in place where Phase 5 makes them false, and the tests that match them change with them (13.3 item 2): ADR-005's D-20 bullet ("While no V2 vote decides (`MODEL_GATEWAY` off, the default outside development, or shadow, or a panel in ZERO) …; under `on` (development only before the Phase 5 exit) V1.3 flags route to the V2 panel (ADR-008)"); the Phase 3 spec where it names the shipped package (5.2's `DEFAULT_PACKAGE_PATH`, "`.../v4.json` with Phase 5"; the schema versions the loader accepts, "and 4 since Phase 5"; the test lines naming the package version, "4.0.0 for Phase 5's v4"; 7.17's replay report shape; `RAW`); the Phase 4 spec's 5.2 `DEFAULT_PACKAGE_PATH`, its `consult_v2`/`V2Hook` text, D-20's "before Phase 5" statements and the `VerificationRecord` `correct` rule's text; the `aggregate.py`, `runner.py`, `evidential.py`, `contracts.py`, `package_check.py`, `tutor_pipeline/__init__.py`, `ledger.py` and `tutor_followups.py` docstrings and the `WIRED_GENERATORS` comment; `teaching_assistant.py`'s docstring; `provider-key-rotation.md`; the Phase 3 runbook's budget lines and the env example's budget comment (v4 from the Phase 5 release); the Phase 3 spec's `ClaimGenerator` comment (no provider generator is wired while D-12 is open) and its 7.10 line on the Vertex helpers (retired by Phase 5); the D-23 opt-in of semantic retrieval in ADR-002 item 5, the Phase 2 spec's `SEMANTIC_RETRIEVAL_ENABLED` row, the `semantic_retrieval_enabled` comment of `config.py`, `retrieval_engine.py`'s docstring, the env example's `MODEL_EGRESS_PROVIDERS` comment and the deployment runbook's Phase 5 section; `TutorPipeline._over`'s docstring and messages (`BUDGET_EVENTS`); the retired `OPENAI_CHAT_MODEL` line of the API's developer env template, now a comment; the embedding egress through the gateway (4.19) in ADR-002 item 5, ADR-006, ADR-008, the Phase 2 spec's `semantic.inactive` and `SEMANTIC_RETRIEVAL_ENABLED` rows, the observability runbook's start-up row, the env example's comments and the deployment runbook; the shared budget, stop and cache (4.4, 4.5, 4.15) in ADR-006, ADR-008, the registry document, the runbooks and the gateway's docstrings; the Phase 3 spec's `SCHEMA_REVISION` line and its test 32, the Phase 3 revision's docstring and the deployment runbook's Phase 3 rollback stamp step (section 8).

---

## 8. Database

- **One migration**, `20261122_phase5_gateway_controls` (after `20261119_phase3_response_ledger`; `ledger.SCHEMA_REVISION` names it, so every record stamps it as `versions.schema_revision_expected`): three tables with no learner data and no evidence. `gateway_budget_days` (`registry`, `day`, the primary key; `spent`, `alerted`), `gateway_stops` (`registry`, the primary key; `reason`, `stopped_at`) and `evidential_cache_entries` (`kind`, `key`, the primary key; `value`, `used_at`, indexed). Start-up's `create_all` builds them too. The downgrade drops them; dropping `gateway_stops` also drops a recorded stop, so `MODEL_GATEWAY=off` comes first (the runbook). The v3 record needs no column (M7): `ledger-entry-v3` rows go into `response_ledger` as canonical JSON, like v1 and v2 rows.
- A mixed v1/v2/v3 chain verifies and exports on the session dialect (SQLite, and PostgreSQL under psycopg and pg8000) and restores into a fresh database (13.2 `test_v2_ledger_records.py`). `pending_v3_intents`' `IN` filter runs on all three.
- **Erasure:** unaffected. Phase 5 adds no identifier and no learner text: the V2 block holds enumerations, model ids, hashes and span ids. A v3 shadow row carries the same pseudonymous turn and source message ids as every v2 shadow row, erased with the turns as before. None of the three new tables has a user-keyed column (`erasure.user_keyed_tables` finds none): the cache's keys are keyed digests of hashes and its values corpus-derived claim plans and verdicts (4.15).
- **Rollback by digest:** an image older than Phase 5 cannot validate v3 rows, so before such a rollback the operator runs the export (runbook). Production writes no v3 row while `TWO_PASS_TUTOR` and `MODEL_GATEWAY` are off. The earlier image reads none of the three tables, so a digest rollback needs no downgrade.
- **Writes:** no start-up write is added. At run time (in development only while every other registry is empty and its budget 0): a stop writes one security event and its `gateway_stops` row (4.5); each call's reservation updates the day's budget row (4.4); each cache miss writes its entry and each hit refreshes it (4.15); the operator's clear deletes a stop row and writes `gateway.stop_cleared`.

---

## 9. Routes and request-path behaviour

| Path | Outside development | Development |
|---|---|---|
| `POST /assistant/chat`, `POST /tutor/turns`, `POST /qa/ask` | Learner bodies unchanged (13.1 test 33). No gateway call (`MODEL_GATEWAY` off; empty registry). `/tutor/turns` stays disabled. | Unchanged learner bodies. The background shadow writes `ledger-entry-v3` with the V2 shadow beside V1. |
| `GET /ready` | Gains the fields of 10.2 (registry `production`, no members, `model_gateway` `off`) | Same fields, with the development registry |
| `GET /ledger/responses/{id}` | 404 (unchanged) | Returns v3 shadow records to the reviewer as it returns v2 shadow records |
| Shadow pipeline | Off | V2 shadow on fakes; `on` on request |

No route is added, and the authorization matrix is unchanged (`scripts/authorization_matrix.py --check` stays green).

---

## 10. Start-up, `/ready`, logs and SLIs

### 10.1 Start-up

The order is `_check_v1_package`, then `_check_gateway_package` (4.17), then the tutor pipeline check, then the manifest, all before any table. An unpinned identifier stops the load itself (4.1). The retired-settings warning is logged in `lifespan`.

### 10.2 `/ready` (`_build_fields()`; no database read but the shared stop)

```json
"model_gateway": "off|shadow|on", "model_gateway_setting": "off|shadow|on", "phase5_exit_passed": false,
"gateway": {"version": "gateway-v1", "registry": "development|staging|production|default",
            "members": [{"adapter_id", "family", "provider", "model_id", "model_version", "capabilities"}],
            "embeddings": {"provider": "openai-embeddings", "model_id": null, "model_version": null},
            "state": "open|stopped", "budget_daily_units": 0,
            "tool_contract_version": "mcp-tools-v1",
            "panel": {"max_members": 3, "weights": "equal-weights-v1", "routing_table": "degraded-matrix-v1", "tier_rule": "context-tier-v1"},
            "provisional": true, "available": true}
```

`gateway` is `null` for a package without a gateway block. `/ready` is public (`GET /ready` is `public` in the authorization matrix), so it reports the gateway's state only: never the stop's reason (it may say a credential reached the logs, or name a spend outcome) and never the operator's switches (`MODEL_EGRESS_PROVIDERS`, `MODEL_GATEWAY_KILL_SWITCH`, `MODEL_GATEWAY_DISABLED_ADAPTERS`), on any body (ready, degraded or building); the reason is in the `gateway.stopped` line and the operator's status command. Every value is fixed for the life of the process except `gateway.state` and `model_gateway` (the effective mode, which `v2_panel.mode` turns `off`), which change once, at a stop of this instance or when it adopts the registry's shared stop (plan 7.7 requires "gateway state"; 4.5). The only database read is that adoption: `model_gateway` and `gateway.state` read the shared stop through the process gateway, which `v2_panel.mode` builds only when the V2 mode is not off by the settings, so a build whose V2 mode is off by its settings (production) reads no gateway table and reports `state` `open` (4.5). A store that cannot be read leaves the state as it is (`gateway.stop_unread`), so `/ready` still answers. No count, spend or per-run outcome is reported; `slis` is unchanged; `config_package_version` reports 4.0.0.

### 10.3 Metrics (in process; not public)

`V2_METRICS.detail_snapshot(budget=..., cache=..., gateway=...)` holds: `runs` by mode; `completion` `{"passed_v1", "completed", "withheld", "rate"}` (verification completion, `V2Track.completed`: a V1-passed response whose every V2-eligible claim got a completed vote, `pass` or `fail`, and whose alignment item was judged when a claim passed; a V1-passed response with a withheld claim, REDUCED-1 tiers 1-2, ZERO, a kill switch, a stop or the shadow budget, or with an unjudged alignment item, counts as `withheld`, so an outage lowers the rate); `modes` (V1-passed responses per panel mode, and `budget_exceeded`, the shadow budget, counted apart); `time_in_mode_s` (wall seconds per mode, an injectable `clock`: the clock moves only on a response whose panel was reached, which attributes the time since the previous such response to that one's mode, and its panel mode is the mode in force from then on; a response that never reached the panel leaves the clock and the mode unchanged; the snapshot adds the time since the last such response to the mode in force); `latency_ms` (nearest-rank p95 over the last 1024: `gateway_call` per adapter from `GATEWAY_METRICS`, `panel` per response and `correction` per cycle); `cost_units` `{"total", "per_response_mean", "per_response_p95"}`; `budget` `{"daily_units", "spent_today", "alerted"}`; `cache` (hits, misses and entries per kind); `x2`, `degraded_withheld`, `disagreements` and `gateway` (`state`, `stop_reason`).

### 10.4 Log events (enumerations, counts, adapter ids, registry names, stop times and hashes only; no text, no learner or response ids)

| Event | Fields | Severity |
|---|---|---|
| `gateway.call` | `adapter_id`, `family`, `item` (claim\|alignment), `outcome` (ok\|error\|timeout\|refused; `refused` for a call the gateway refused before the adapter, with `latency_ms` and `cost_units` 0), `latency_ms`, `cost_units` | INFO |
| `gateway.call_failed` | `adapter_id`, `kind`, `status` | WARNING |
| `gateway.egress_refused` | `provider`, `adapter_id`, `consumer` (`gateway` for a registry member; `semantic-retrieval`, with `adapter_id` null, for the Phase 2 embedding backend) | WARNING (once per provider) |
| `gateway.budget_alert` | `share`, `daily_units`, `spent` | WARNING (once per UTC day) |
| `gateway.stopped` | `reason`, `origin` (`instance` for the stopping instance, `shared` for one that adopts the registry's shared stop) | ERROR, plus security event `gateway.stopped` (origin `instance` only) |
| `gateway.stop_unshared` | `reason` (the stop could not be written to the shared store; this instance stays stopped) | ERROR |
| `gateway.stop_unread` | — (the shared stop could not be read; the state is kept) | WARNING |
| `gateway.budget_unavailable` | — (the daily budget's store could not be read or written; the member is ineligible or the call refused, nothing is sent, no stop) | WARNING |
| `gateway.stop_status` | `stops` (registry, reason, time), `cleared` (the operator's `python -m app.workers.gateway_stop`; a clear also writes security event `gateway.stop_cleared`) | INFO |
| `gateway.retired_setting` | `names` | WARNING |
| `tutor.v2.run` | `mode`, `degraded_mode`, `generator_family`, `members`, `claims`, `outcomes` (tier → outcome → count), `cycles`, `x2`, `calls`, `cache_hits`, `cost_units`, `latency_ms`, `alignment`, `passed_v1`, `panel_reached`, `panel_mode` (null when the panel was not reached), `completed` | INFO |
| `tutor.v2.degraded` | `mode`, `eligible` (logged once per response, when its panel is built below FULL) | WARNING |
| `tutor.v2.disagreement` | `v1_final`, `v2_would` | INFO |
| `tutor.v2.unavailable` | `reason` | WARNING |
| `tutor.v2.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms` (message "The V2 panel exceeded the shadow budget") | WARNING |
| `tutor.v2.cache_unavailable` | `operation` (`get`, `put` or `evict`; the shared cache's store failed and the operation was a miss or a no-op) | WARNING |
| `semantic.inactive` (start-up, Phase 2) | `reason` (`egress_not_opted_in`, `provider_open`, `unpinned`, `no_budget`, `gateway_stopped`, `not_configured`, `learner_text`, `not_aligned`; 4.19) | WARNING |
| `tutor.v2.on_downgraded` | — | WARNING (once) |

The Phase 5 events log on `qcai.gateway` (the `gateway.*` events) and `qcai.tutor` (the `tutor.*` events), the start-up line `gateway.retired_setting` (on `qcai.gateway`) included. The exceptions are the operator's `gateway.stop_status` (on `qcai.worker`), with registry names, reasons and stop times, and the API's start-up line `semantic.inactive` (on `qcai.api`); the security events `gateway.stopped` and `gateway.stop_cleared` log on `qcai.security`, with `event_type`, as every security event does.

---

## 11. Frontend

No change (E12). The degraded banner exists only on the V2 record in the shadow path. The frontend job still runs (lint, typecheck, 154 integration tests, `npm audit`).

---

## 12. Fixtures and records

### 12.1 `scripts/run_v2_fixtures.py` (plan P F-1, plan J fault injection)

```
python scripts/run_v2_fixtures.py --write docs/evaluation/phase5/v2_fixture_report_v1.json [--allow-dirty]
python scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
```

**Setup.** `DATABASE_URL` defaults to in-memory SQLite before any app import. The all-public-approved store from a temporary manifest (the only file written, in a `tempfile` directory). `Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=…, retrieval_gate="bm25f-v1", two_pass_tutor="shadow", v1_pipeline="enforce", model_gateway="on", model_gateway_disabled_adapters=…)`. The shipped development registry, a fresh `ModelGateway` (its own `DailyBudget`, no stop store) and `ProcessEvidentialCache` per scenario, so the record does not depend on the database's shared state, an in-memory SQLite ledger, and the capture hook. The script refuses `lqs/` paths. Public-corpus fixtures only: `apps/api/tests/data/score_floor_queries.json` (174 in-domain, 124 off-topic and stopword-only).

**Scenarios** (disabled through `MODEL_GATEWAY_DISABLED_ADAPTERS`; eligibility precedes the panel, so `fake-delta` is the spare family): `all_up`; `one_down` (`fake-gamma`, `fake-delta`), REDUCED-2; `two_down` (`fake-beta` to `fake-delta`), REDUCED-1; `three_down` (all four), ZERO; and a `cache_pass` that runs the `all_up` queries again on the `all_up` gateway and cache.

**Report shape.**

```json
{"report": "qcai-v2-fixture-report", "format_version": 1, "created_at": "…", "commit": "…",
 "evidence_class": "fixture measurements, not research results (plan Phase 5 H: V-2, V-4 are E2 results, never claimed from fixtures)",
 "public_corpus_only": true, "config_package": {"version": "4.0.0", "sha256": "…"}, "queries": {"path": "…", "count": 298},
 "scenarios": [{"name": "all_up", "down": [], "responses": 298, "f1": {"complete": 298, "rate": "298/298"},
                "modes": {"FULL": 0, "REDUCED-2": 0, "REDUCED-1": 0, "ZERO": 0}, "finals": {"deliver": 0, "withhold": 0, "abstain": 0},
                "tiers": {"1": 0, "2": 0, "3": 0}, "outcomes": {"pass": 0, "fail": 0, "withheld": 0}, "x2": 0, "calls": 0,
                "calls_by_item": {"claim": 0, "alignment": 0},
                "cost_units": {"total": 0, "per_response_mean": 0.0}, "v2_after_v1_fail": 0, "deliver_without_pass": 0}],
 "cache_pass": {"claim_plan_hits": 0, "verdict_hits": 0, "verdict_calls": 0, "alignment_calls": 0, "first_pass_calls": 0, "f1": {}},
 "voting_table_sha256": "…", "payload_fields": {"claim": ["claim_text", "instructions", "item", "request_schema", "span"], "alignment": […]},
 "latency": {"p95_ms": {"gateway_call": 0.0, "panel": 0.0}}, "result": "pass", "problems": [],
 "inputs": {"rule": "imported-repository-modules-sha256-lf-v1", "files": {}, "sha256": "…"}}
```

`calls_by_item` splits a scenario's calls into claim items and alignment items (from the requests the gateway captured). In `cache_pass`, `verdict_calls` counts the claim items that missed the cache and `alignment_calls` the alignment items, which are never cached; `first_pass_calls` is the `all_up` pass's total.

**F-1.** For each response: the chain verifies (`verify_response_ledger` at the end of the run); every recorded claim has a verdict with at least one V1 result; every V2-eligible claim of the final V1-passed candidate has `v2` set; no V2 verdict exists when the record is a V1 hard fail or V1 abstention. `rate` must be `n/n`.

**Exit codes.** 0 pass; 1 drift (latency ignored); 3 F-1 below 100%, or a mode or rule that contradicts the routing table (a stop); 4 a dirty tree on `--write`; 5 `v2_after_v1_fail > 0` or `deliver_without_pass > 0` (an invariant breach). The fixtures' fakes support every verbatim claim, so the report shows no `fail` and no X2; the AC tests (13.1 tests 7, 10, 11) cover those paths.

### 12.2 Phase 4 public-payload golden (`scripts/capture_public_payloads.py`; E12)

The script was run on the branch at the commit that adds it, before any `apps/api/app` change, so it captured Phase 4 code. **Configurations:** (a) `governed`: `Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"], corpus_manifest_path=<repository manifest>)`; (b) `all_approved`: the same with an all-public-approved temporary manifest. **Captures:** for every query of `score_floor_queries.json` (298), the sha256 of the canonical JSON of `QAEngine(engine, settings).ask(q)` and of `TutorOrchestrator(TeachingAssistantService(engine, settings), settings).chat(db, user, AssistantChatRequest(message=q))` on an in-memory SQLite database (a uuid4 demo `AuthUser`; `thread_id` and `turn_id` replaced by fixed placeholders), the legacy guard included in both. It never stores a body, and it writes `apps/api/tests/data/phase4_public_payloads_v1.json` (`{"captured_on_app_tree": "98f7cc4", "configurations": {name: [{"surface", "query_index", "sha256"}]}}`). `--check` recomputes on the current tree and exits 1 on any difference.

---

## 13. Tests

### 13.1 `apps/api/tests/test_phase5_acceptance.py`

**Fakes and fixtures.** Fakes live in `apps/api/tests/v2_fakes.py`: `fake_spec(family, …)`; `make_registry(families, *, generator_family=None, duplicate=None)`; `ScriptedFakeAdapter` (a script from `(claim_text_sha256, span_id)` or `"*"` to verdict and EHMF, `down`, `late_ms`, `fail_calls`, `alignment`, `calls`); `FakeSecretStore`; `RevisingGenerator` (a `ClaimReviser` that returns the same text, or a scripted one); `FamilyGenerator` and `FakeAlphaGenerator` (a generator whose id is a registry adapter of family `fake-alpha` with capability `generate`); `fresh_gateway(units, *, adapters, clock)`; `v2_pipeline(settings=None, **kw)` (`model_gateway="on"` unless the settings say otherwise, its own gateway and a cold cache); `captured(gateway)`; `adapters_of(registry, **options)`. The Phase 4 helpers `run` and `MULTI_CLAIM` are reused from `v1_fakes`. One module-scoped fixture runs `run_v2_fixtures.compute()` once. Security events are read ordered by `seq`.

**AC-5-1**
1. `test_ac_5_1_the_panel_never_holds_the_generator_s_family_for_any_registry_ordering`: every ordered registry of 1-5 adapters over 4 families (1364 registries) with every eligibility subset of its first three adapters, for each generator family (the 4 and one outside them): the panel never holds the generator family, holds distinct families and at most 3 members, and its members are the first eligible adapter of each of the first three eligible non-generator families.
2. `test_ac_5_1_a_panel_with_the_generator_s_family_cannot_be_built_or_recorded`: `Panel(...)` raises `PanelError`; `V2ClaimVerdict` and `VerificationRecordV2` refuse it; a pipeline whose generator is `FakeAlphaGenerator` records no `fake-alpha` vote and the fake-alpha adapter's `calls` stays 0; an unknown generator family leaves the panel empty and withholds every eligible claim with no call.

**AC-5-2**
3. `test_ac_5_2_two_verifiers_of_one_family_yield_one_vote`: a registry with `fake-beta-1` and `fake-beta-2` gives one fake-beta member and `fake-beta-2.calls == 0`; with `fake-beta-1` disabled, `fake-beta-2` represents the family; a claim verdict with two votes of one family on one span is refused.

**AC-5-3**
4. `test_ac_5_3_captured_verifier_prompts_hold_no_generator_identity_votes_learner_ids_text_or_history`: every request captured at `ModelGateway.capture` over route turns (`/assistant/chat` and `/tutor/turns`, demo learners, a follow-up turn, a marker word in the learner text) and over fixture runs holds no generator id or family, no other member's adapter or model id, no key in `{vote, votes, verdict_of, family, generator, model}`, no user, thread, turn, response or source message id, no email, no learner question, follow-up or resolved question, and no marker.
5. `test_ac_5_3_objective_and_band_appear_only_in_the_alignment_item_payload`.
6. `test_ac_5_3_every_verifier_gets_the_same_prompt_and_tool_surface` (E-97): one `verifier_prompt_hash`, one `tool_contract_version` and one instructions object across members and responses; every fresh vote went through `verification.verdict` and every vote's span text through `corpus.span_text`.

**AC-5-4**
7. `test_ac_5_4_one_objection_fails_tier_1_and_passes_tier_2_and_not_enough_info_objects`: in `voting.tally` and through the pipeline (`on`): a tier-1 claim (an assessment context) fails with one CONTRADICTED or NOT_ENOUGH_INFO objection, and a tier-2 claim passes.

**AC-5-5**
8. `test_ac_5_5_a_v1_hard_fail_or_abstention_makes_no_gateway_call`: an unresolvable span id (V1HardFail), an off-topic query (V1.5 abstain) and a checker-unavailable run (V1Abstained): every fake's `calls == 0`, no verdict carries `v2`, and `panel_reached` is false.

**AC-5-6**
9. `test_ac_5_6_fault_injection_one_two_and_three_providers_down`, parametrized over 0-3 down (the spare family down too): FULL; REDUCED-2 (1oo2, label `degraded`, banner); REDUCED-1 (tier-1 and tier-2 claims withheld with `v2_degraded_withheld` and no call; a tier-3 claim, through an overlay, follows equal weights on the remaining verifier); ZERO (no call, every claim withheld and queued, the response withheld with the replacement of the legacy decision, `degraded` and the ZERO banner). `test_ac_5_6_a_mid_response_loss_and_each_kill_switch` covers a mid-response failure (re-tallied from memory, no vote marked `cached`) and each kill switch (the record names it and abstains whatever the legacy decision was, every V2-withheld claim queued; with no pre-verified source both switches give the same finals; a kill-switched record that withholds, and `v2_kill_switch` without a switch, are refused). `test_ac_5_6_a_shared_store_failure_fails_closed_and_every_response_keeps_its_ledger_record`, in `on` and `shadow`, over the process gateway and cache: an unreadable shared budget (every member ineligible: ZERO), an unwritable one (each member refused at its first call) and a failing cache store (misses, calls made): every response keeps its ledger record (F-1), and nothing stops the gateway. `test_ac_5_6_the_degraded_banners_claim_no_check_the_learner_does_not_get`: the ZERO banner says "quoted course passages or no answer", and no banner says checked, verified (ZERO) or grounded.

**AC-5-7**
10. `test_ac_5_7_a_claim_failing_two_correction_cycles_is_abstained_and_marked_x2`: `RevisingGenerator` with every member contradicting one claim: two cycles, the claim abstains with escalation X2, and `pending_v3_intents` returns it; with the extractive generator the failed claim is re-verified unchanged (no new call) and the rest delivers.
11. `test_ac_5_7_a_type_e_objection_re_renders_only`: alignment leakage: no new claim plan (generator calls unchanged), two re-renders, then `v2_alignment_failed`. `test_ac_5_7_a_claim_level_type_e_objection_is_re_rendered_and_never_revised`: every member objects to one claim with type E: two `re_render` cycles, no `revise` call and no new plan, then the claim abstains with X2 and the rest delivers (Socratic); a type E objection beside a type A one is revised with type A; a cycle with a presentation claim and a content claim revises the content claim only.

**AC-5-8**
12. `test_ac_5_8_a_repeated_claim_span_pair_hits_the_cache_and_a_configuration_bump_misses`: a second identical run casts every vote from the cache, and adapter calls grow by the alignment item only; a bumped package copy (`package_version` 4.0.1, rehashed) misses.

**AC-5-9**
13. `test_ac_5_9_a_provider_error_leaves_no_key_authorization_header_or_query_in_logs_or_exceptions`: `HttpJsonAdapter` over `MockTransport` returning 401 (with the key echoed in the body), 500, a `ReadTimeout`, invalid JSON and a body the client cannot decode (a `gzip` content encoding over plain bytes: `httpx.DecodingError`), through the gateway, with caplog at DEBUG for root, `httpx`, `httpcore` and `qcai.gateway`: the header carried the key and the URL no query; the error's `__cause__` and `__context__` are `None`; its `str`, `repr` and formatted traceback (from the gateway down), and every log line, hold no key, no `Bearer`, no `Authorization` and no `?`; the gateway stays open; an endpoint with a query is refused at construction.
14. `test_ac_5_9_calls_stop_at_the_daily_budget`: a budget of 5 units at a cost of 1 and a response needing 6 calls (two claims, three members): five calls, the alert after the fourth, the sixth refused, the gateway stopped with `budget_breach`, the security event written, the rest of that response in ZERO, and the next response's V2 mode `off` (a `ledger-entry-v2`).

**AC-5-10**
15. `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`, parametrized over a missing version, `-preview`, `-latest`, `-exp`, `alias`, a non-pinned version form, a glued `preview` and `latest`, an impossible date and an unstripped version: the loader refuses each, and a start-up subprocess (a package copy) exits non-zero naming "unpinned"; the retired id `gemini-3.1-flash-lite-preview` is refused. `test_ac_5_10_an_unpinned_embedding_model_makes_start_up_fail`: an unpinned `gateway.embeddings` model stops start-up too.

**AC-5-11**
16. `test_ac_5_11_two_learners_share_only_evidential_entries_and_a_model_change_misses`: two demo learners, the same question, through `/tutor/turns`: the second run's claim-plan and verdict entries hit; every response is rendered (a spy); the cache holds only `ClaimPlan` and `AdapterVerdict` values, whose keys and values hold no learner id, thread id, turn id or rendered text; a fake with a new `model_version` misses; the same question under another lesson scope misses the claim-plan entry.

**Plan P (F-1) and the fixture record**
17. `test_plan_p_f_1_every_fixture_response_carries_ledger_verdicts` (rate `n/n` in every scenario and the cache pass; each scenario's calls are its claim and alignment items; the cache pass makes no claim-item call, and its only calls are the `all_up` pass's alignment items).
18. `test_plan_p_the_committed_v2_fixture_report_matches_a_fresh_run_and_names_its_evidence_class`: the record equals a fresh run but for `created_at`, `commit`, `latency` and `inputs`; the record's `inputs` match the checkout (`input_problems`) and every module they list is one the fresh run imported, unchanged (inside a test process the map also holds what other tests imported; `--check`, a process of its own, compares the whole map).

**Plan G, L, H, E, D, I, F; invariants; freeze**
19. `test_plan_g_model_gateway_defaults_and_refusals`: the defaults; `on` refused outside development before the exit, and refused with V1 shadow; a package claiming both exits allows it and the override is recorded; a gateway package problem other than pinning stops a governed start-up only when the gateway is requested, and otherwise reports `gateway.available` false with the mode off; a start-up subprocess with `MODEL_GATEWAY=on` outside development exits non-zero.
20. `test_plan_l_flag_off_returns_to_phase_4`: with `model_gateway="off"` a `ledger-entry-v2` with a `VerificationRecord`, no gateway or cache built or read (a factory that raises), and Phase 4's finals; an explicit `v2_hook` gives the same.
21. `test_plan_g_shadow_dual_run_records_v2_beside_the_unchanged_v1_decision`: shadow and off give equal finals, reasons, replacements and labels; the V2 block and the would-summary are present, and the disagreement is logged.
22. `test_plan_l_a_payload_violation_stops_the_gateway_with_a_security_event`: an unknown span, an identifier in the text and an alignment rendering with a non-template segment: the gateway stops, the security event is written, and the next response's V2 mode is `off`.
23. `test_plan_l_a_secret_reaching_a_log_stops_the_gateway`: the listener only sets the flag (no stop and no security event until the gateway's next eligibility decision); then the gateway stops with `secret_in_logs` and one event is written. `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`: one instance's stop stops another at its next eligibility decision (origin `shared`, no second security event) and a new process gateway, `/ready` reports it, another registry's stop is its own, a status read clears nothing, and the operator's `--clear` removes it with the security event `gateway.stop_cleared`; after the clear the running instances stay stopped until they are replaced, and a new process starts open.
24. `test_plan_h_only_public_quotable_spans_leave_and_gateway_and_v2_import_no_learner_module`: a governed (D-31) store gives nothing quotable, so a violation; and the import rule.
25. `test_plan_e_the_legacy_provider_code_is_retired_and_no_production_path_reached_it` (4.18).
26. `test_plan_e_a_retired_setting_is_named_at_start_up_and_its_value_never_logged`.
27. `test_plan_e_only_the_gateway_makes_model_egress` (the 13.2 scanner on the tree; the single allow-list entry).
28. `test_plan_e_d_23_provider_egress_needs_a_per_environment_per_provider_opt_in`: a non-fake member is refused, then allowed by `MODEL_EGRESS_PROVIDERS`; the semantic backend is off without its opt-in, and opted in it is off while the provider decisions are open. `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`: no Settings field holds the key or names the embedding model; each of 4.19's reasons in order, `learner_text` last, so no embedder is given even with closed decisions, the Q-15 review, a pinned `gateway.embeddings` model, a budget, an open gateway and the key; the start-up redaction reads the key through the gateway. `test_plan_e_a_semantic_setting_without_the_d_23_opt_in_names_its_refusal`: the engine's `semantic_inactive_reason` is `egress_not_opted_in`, `sync_semantic_index` logs one `gateway.egress_refused` (`consumer` `semantic-retrieval`), opted in it is `provider_open`, and with a test's embedder and no index key `not_configured`; every reason has a message. `test_plan_e_the_start_up_semantic_warning_names_its_reason`: the lifespan logs `semantic.inactive` with each reason and its message, and nothing with the setting off.
29. `test_plan_e_no_real_provider_is_registered_in_any_shipped_registry` (and every non-development budget is 0: hold H9).
30. `test_plan_d_five_tool_servers_have_versioned_contracts_and_the_learner_server_is_hidden`.
31. `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome`: the gateway's static values, the embedding entry and the state; no stop reason and no operator switch on the body, whatever the settings.
32. `test_plan_i_v2_metrics_report_completion_time_degraded_p95_cost_and_the_budget_event`: an outage (every member down, a V1-abstained response in the middle, an injected clock): completion 0 of 3 with 3 withheld, all the time ZERO's, and each `tutor.v2.run` line's `passed_v1`, `panel_reached`, `panel_mode` and `completed`; then FULL and REDUCED-2 responses: completion 3 of 3, the time per mode, p95, cost and the 80% budget event.
33. `test_freeze_public_payloads_with_shipped_non_development_settings_are_byte_identical_to_phase_4` (the 12.2 golden).
34. `test_invariant_3_v2_never_overwrites_a_v1_hard_fail` (a final rendering's hard fail; a correction candidate's is `test_v2_correction.py`'s).
35. `test_invariant_4_distinct_families_equal_votes`.
36. `test_invariant_6_no_v2_delivery_without_a_completed_passing_vote` (300 seeded fault schedules).
37. `test_invariant_10_every_vote_carries_its_prompt_hash_and_every_v3_record_its_provenance_fields`.
38. `test_freeze_v1_3_flags_route_to_v2_only_under_model_gateway_on` (D-20 holds with off and shadow).
39. `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package`: every adapter, family, model id, version, capability, cap, cost and daily budget `gateway-registry.md` states equals the package's, as do the matrix, the payload register's fields and the terms record.
40. Doc tests: `test_phase5_spec_section_3_lists_the_code_s_fields`; `test_phase5_docs_quote_the_plan_and_state_the_current_rules` (plan L and M quoted exactly; PD-22..PD-31 and DI-69..DI-88 in this spec; the four settings in the spec and the runbook; v4's Q-22 values); `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly` (the observability table's rows are well formed and name every 10.4 event; the shared stop and the ledger export's path in the runbook; the payload register's never-sent list and HTTP envelope; the egress guard's scope; the texts Phase 5 made false, 7.6); `test_phase5_docs_name_the_logger_each_phase5_event_logs_on` (the logger of every 10.4 event, read from the source, a literal `event` through its module's or an imported logger and the shadow-budget events through `BUDGET_EVENTS`, and run for `gateway.retired_setting`, `semantic.inactive` and `gateway.stop_status`, is the one 10.4's logger sentence, the 7.1 import rule and the observability runbook name; the two security events on `qcai.security`); `test_phase5_docs_the_test_strategy_maps_every_test_module_the_phase_added` (both tables: every module the phase added, and every existing module it changed, `PHASE5_EXTENDED_MODULES`); `test_phase5_docs_the_spec_ends_in_one_review_history_table`. The egress guard's scope is compared with line breaks and code marks folded, in ADR-006, the gateway's docstring and the guard's own docstring.
41. `test_plan_13_6_flag_combinations_never_disable_v1_or_deliver_unverified_text` (plan 13.2): ENVIRONMENT × TWO_PASS_TUTOR × V1_PIPELINE × MODEL_GATEWAY × MODEL_GATEWAY_KILL_SWITCH × MODEL_EGRESS_PROVIDERS: a combination is refused exactly when the rules say so; outside development the V1 mode is never `off`, the V2 mode is `off` unless `MODEL_GATEWAY=shadow` is set explicitly, the registry is empty and its budget 0; no record is `delivered`.

### 13.2 Unit test files and helper modules

| File | Proves |
|---|---|
| `test_gateway_pinning.py` | Every refused form, glued aliases, impossible dates and non-canonical identifiers included; the pinned forms (`exp` inside a word is no alias); the retired Vertex id; every message names "unpinned" |
| `test_gateway_registry.py` | Registry selection per environment; the generator family; every gateway refusal of the loader; the `gateway.embeddings` entry's refusals (an unpinned model, a model while the provider gates are open, caps, cost, marking); a non-fake member waits for the Q-15 review, the rule the embedding egress shares |
| `test_gateway_adapters.py` | The fake rule; scripted tables; `down`; a fake keeps no request unless built with `record=True`; a late fake is a timeout at the gateway; output projection; `HttpJsonAdapter` header-only key, the instruction text in the body, `max_tokens`, bounded retries on 429/5xx/timeouts/other client errors and none on 4xx or an undecodable body, `cost_overrun` and an invalid cost, `__cause__` and `__context__` `None`, `no_key`, `invalid_request`, endpoint refusals; any other adapter exception is an unavailable member at the gateway; the embedding adapter (4.19): the key as a Bearer header only, vectors in input order, one budget unit per input and per attempt (retries included), the batch and input caps, the payload policy (a query, a text that is no index entry's excerpt, a private-plane entry and no store: refused, nothing sent, the gateway stopped), a stop another instance writes adopted between two batches, a budget store failure sending nothing, every failure with no cause, context, key or host, and a refused reservation stopping the gateway |
| `test_gateway_budget.py` | Reserve, alert once at 4/5, refuse beyond the budget, reset at the UTC day, 0 makes every adapter ineligible; the shared `DatabaseBudget`: two instances spend from one row, one alert a day across them, a registry's own row, a new day; the process gateway's budget and stop store are the shared ones, and its spend survives a new process; a reply costing more than its reservation stops the gateway (`budget_breach`, a security event), and a refused call is logged with no latency sample; every retry an HTTP adapter sends is reserved, and a refused retry is not sent and stops the gateway; a budget store that cannot be read or written makes members ineligible or unavailable, with no stop and no raise; an unreadable shared stop keeps the state and never raises into a call, the V2 mode or `/ready`, and an unwritable one still stops the instance and logs `gateway.stop_unshared` |
| `test_gateway_egress_guard.py` | The AST scanner: the import rule over `apps/api/app` outside `app/gateway/` with its one allow-list entry (the vector index client), and the host-string rule over the Python files under `apps/api/app`, `scripts`, `evaluation` and `tools`; each rule's samples caught, `langchain_openai` in the retrieval engine included; `urllib.parse`, `langchain_text_splitters`, the two scripts' `urllib.request` and "coherence" not |
| `test_gateway_tools.py` | The document's servers and tools; visibility per role; input/output validation; the committed file equals the document and its sha256 is the package pin |
| `test_gateway_policy.py` | Each claim-item and alignment-item check, a claim text outside its span and a span record outside the public plane (`non_public_span`, before the D-19 quotable rule) included; the policy context is per call |
| `test_v2_voting.py` | The voting arithmetic, exhaustive over modes, tiers and verdict tuples (N = 0..3) against a reference written from the plan; `family_verdict`; split; the routing table and prompt hashes |
| `test_v2_panel.py` | Construction; each eligibility reason; eligibility before the panel; mid-response loss re-tallied from memory; ZERO and the abstention with the kill switches; the alignment rule; tiers computed by the track; each shadow-budget stop logs its own event and message |
| `test_v2_cache.py` | Every key field changes the key, the envelope's lesson scope included; hits; LRU bounds; type refusals; the shared `DatabaseEvidentialCache`: two instances share entries under keyed digests, a hit refreshes an entry, the bound evicts the least recently used, eviction and round-tripped values; the process cache is the shared one and the seam empties it; the generation-1 read and the eviction of a hard-failing plan; no learner data; a store that fails makes a get a miss and a put or an evict a no-op |
| `test_v2_correction.py` | A revised claim is a new candidate judged with fresh V1 state; an unrevisable claim re-verified from the cache and abstained with X2; every rendering judged with a fresh post-render hook; a corrected candidate's V1 hard fail ends with no further V2 call; V1.3 flags route to V2 only under `on`, and in shadow V1 withholds and renders a flagged claim as with V2 off |
| `test_v2_ledger_records.py` | Every `VerificationRecordV2` and `LedgerEntryV3` rule; V2 final reasons only on the V2 record; the factored Phase 4 rules unchanged with the defaults; the `on` record's decision follows its final; a mixed v1/v2/v3 chain verifies, exports and restores; `_provenance_problems` for v3; `pending_v3_intents` |
| `test_config_package.py` (additions) | `test_v3_stays_readable_for_one_release`; `test_v4_keeps_every_v3_value_but_the_listed_changes`; `test_v4_structural_errors_always_stop_the_load` (the Q-22 tier-3 threshold, the correction rules, the tools block's marking, the pinning texts, the marks of `correction`, `degraded` and `alignment`, and the database scopes of the budget, the cache and the stop included); `test_v4_names_the_entry_schema_whose_provenance_fields_it_fills`; `test_gateway_package_check_problems` |
| `test_python_sources.py` (addition) | `test_the_network_guard_refuses_a_non_loopback_socket_and_allows_loopback` |
| `v2_fakes.py`, `network_guard.py` | Not test modules (13.1; conflict 32) |
| `conftest.py` (additions) | Installs the guard before the application import and fails a test that tried a refused socket; an autouse fixture calls `reset_process_gateway()`, `clear_shared_controls()` and `reset_process_cache()` before and after each test |

### 13.3 Existing tests that change (intent kept; each commit message gives the reason)

1. **`test_config_package.py`:** the shipped package is "4.0.0", schema 4; `V3_RAW` reads v3 for `test_v3_keeps_every_v2_value_but_the_listed_changes` and `test_v2_stays_readable_for_one_release`; `test_v3_structural_errors_always_stop_the_load` applies its refusals to `v3.json` and to the shipped v4.
2. **`test_phase4_acceptance.py`:** `body["config_package_version"] == PACKAGE.package_version`; the mixed chain runs with `model_gateway="off"` (its subject is the v2 record beside v1); the route turns expect `ledger-entry-v3`; `test_phase4_docs_the_ci_records_name_the_latest_branch_run` asserts the merge (E15); `test_phase4_docs_the_phase3_spec_states_what_phase4_changed` expects "with Phase 5", "for Phase 5's v4", `(1, 2, 3, 4)` and `RAW` reading v4; `test_phase4_docs_the_code_texts_name_the_shipped_package` expects "v4 since Phase 5" and compares the pin counts of v2, v3 and v4; `test_phase4_docs_name_every_q_22_value_and_the_package_s_provisional_until` reads `V3_PACKAGE_PATH`, the package whose values the Phase 4 spec's DI-52 row names.
3. **`v1_fakes.dev_pipeline`** builds `Settings(model_gateway="off")` when no settings are given (conflict 24); **`test_v1_aggregate_and_runner.py`** `test_shadow_and_enforce_records` and `test_a_v1_1_hard_failed_candidate_counts_its_claims_so_the_bound_claim_ratio_sees_them` construct with `model_gateway="off"`.
4. **`v1_fakes.temp_package`** and **`test_v1_5_abstention.py`** write the copy under `DEFAULT_PACKAGE_PATH.name`.
5. **`test_api.py`:** `test_teaching_assistant_uses_api_key_header_and_no_learner_state_in_the_prompt` and `test_provider_error_logs_no_key` are removed with `_ask_vertex`, the code they exercised; their AC-1-8 intent is carried by tests 13 and 4 and `test_gateway_adapters.py`. `test_teaching_assistant_quotes_approved_spans_and_never_calls_a_provider` sets `VERTEX_AI_API_KEY` in the environment, asserts the class holds no provider path, and keeps its assertions.
6. **`test_phase2_acceptance.py::_semantic_engine`:** an enabled engine adds `model_egress_providers=["openai-embeddings"]` (D-23), and the test asserts that without it the backend stays off.
7. **`test_configuration_overrides.py`:** cases for `model_gateway_shadow`, `model_gateway_on` (refused, still recorded when present) and `model_egress_opt_in`.
8. **`test_response_ledger.py` and `test_response_ledger_provenance.py`:** every direct caller of `_provenance_problems` passes the new `phase5` argument.
9. **`test_phase3_acceptance.py::observe_three_learners`** (the invariant-1 fixture) starts each learner from a cold evidential cache (`reset_process_cache()` empties the shared table too): a record's V2 call and cache-hit counts are traffic history, not learner state. **`test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger`** builds every table but the Phase 3 and Phase 5 revisions' and steps down through the Phase 5 revision before the Phase 3 refusal; **`test_response_ledger_migrations.py`** `test_e10_*` stamps the head and goes down one revision at a time, and `test_f14_*` applies the Phase 3 and then the Phase 5 revision: each keeps its subject, the Phase 3 revision's safety, with the revision that now follows it.
10. **Records:** `docs/evaluation/phase4/v1_fixture_report_v1.json` and `docs/evaluation/phase3/three_plan_replay_v1.json` are re-written (7.5).
11. **Expected unchanged:** the Phase 3 doc and listing guards; `test_phase4_spec_section_3_lists_the_code_s_fields`; the AC-3-6 tests; the `consult_v2` and AC-4-1 tests; `test_the_verification_and_ledger_v2_rules_refuse_each_inconsistency` (its `correct` match holds the new message); `test_structured_logging.py`, `test_security_log.py`; every frontend test.
12. **The semantic backend's tests:** `test_phase2_acceptance.py::_semantic_engine` gives the engine an in-process embedder (`embedder=`) instead of a key, and its D-23 case asserts `egress_not_opted_in` through the gateway; `test_phase2_acceptance.py` and `test_tutor_retrieve_bind_lock.py` drop the `openai_api_key` keyword (no such setting); `test_gateway_egress_guard.py`'s allow-list is the vector index client only.
13. **`test_phase2_acceptance.py::test_d9_ready_reports_the_p1_floor_threshold_in_force_and_the_effective_semantic_state`** builds its switched engine with `_semantic_engine` (an in-process embedder and an index), so the backend is enabled and only the missing alignment keeps `semantic_enabled` false (`not_aligned`); its former settings reached the D-23 refusal instead, once the gateway gave the embedder.
14. **`test_phase3_acceptance.py::test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`** also counts the engine's statements during `_build_fields()`: no session read, and only the shared gateway stop's reads (10.2).
15. **The kill-switch tests** (`test_a_kill_switch_runs_the_zero_path_with_no_call`, `test_ac_5_6_a_mid_response_loss_and_each_kill_switch`) expect the abstention (4.10); **the embedding adapter's tests** send document items (the policy refuses a query) and count a unit per input and attempt; **`test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`** and **`test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome`** read the state with no public stop reason; **`test_a_non_fake_member_loads_only_once_every_provider_decision_is_settled`** settles the Q-15 review too.

### 13.4 Frontend tests

None change.

### 13.5 Mutation checks (each must fail its test when reverted)

A mutation check reverts one rule (or one text a doc test pins), runs the tests named for it, sees them fail and restores the file byte for byte. The checks performed, each recorded in its commit's message and in the BEP phase record:
- `848bf09` (E15): `check_records.py`'s assertion fails on the pre-merge spec, and `test_phase4_docs_the_ci_records_name_the_latest_branch_run` on the pre-merge texts.
- `e992209` (the network guard), 2: `_is_local` always true, and the `conftest.py` install removed: `test_the_network_guard_refuses_a_non_loopback_socket_and_allows_loopback`.
- `d4d4d80` (the build), 17: `plan_cacheable` true for every generator; `Panel.__post_init__` accepting the generator's family, and two members of one family; the pin rule accepting `latest`; `egress_allowed` allowing every provider; a budget that never refuses; the payload policy passing an unquotable span, and altered span text; the log redaction notifying no listener; V1.3 flags routed to V2 in shadow; NOT-ENOUGH-INFO not objecting; claims delivered with no alignment item judged; the HTTP adapter raising a timeout inside its `except` block; a stopped gateway staying eligible; the kill switch ignored; the network guard treating every host as local; a stale module hash in the committed V2 report.
- The review-1 commit (section 18), 30: a claim-level type E objection revised like any other: `test_ac_5_7_a_claim_level_type_e_objection_is_re_rendered_and_never_revised`; verification completion counting every V1-passed response: `test_plan_i_v2_metrics_report_completion_time_degraded_p95_cost_and_the_budget_event`; the time-in-mode clock moved by every response, with the record's placeholder mode: `test_plan_i_v2_metrics_report_completion_time_degraded_p95_cost_and_the_budget_event`; the HTTP adapter's `DecodingError` and other client-error clauses removed: `test_retries_are_bounded_and_every_failure_is_raised_with_no_cause_or_context`; the gateway's catch-all for other adapter exceptions removed: `test_an_adapter_that_raises_anything_else_is_only_unavailable_at_the_gateway`; the adapter ignoring a reported cost above the reservation: `test_retries_are_bounded_and_every_failure_is_raised_with_no_cause_or_context`, `test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged`; the gateway not stopping on `cost_overrun`: `test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged`; the instruction text left out of the HTTP body: `test_the_http_adapter_sends_the_key_in_a_header_with_its_caps_and_returns_the_output`; the adapter's prompt-hash check removed: `test_a_request_naming_another_prompt_hash_is_refused_before_any_call`; a fake keeping every request: `test_a_fake_keeps_no_request_unless_a_test_asks_it_to`; the loader accepting any tier-3 threshold while Q-22 is unresolved: `test_v4_structural_errors_always_stop_the_load`; the loader accepting any correction rule: `test_v4_structural_errors_always_stop_the_load`; the loader accepting an unmarked tools block: `test_v4_structural_errors_always_stop_the_load`; the loader accepting any pinning text: `test_v4_structural_errors_always_stop_the_load`; the pin rule accepting a glued alias: `test_every_unpinned_form_is_refused_and_names_unpinned`, `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`; the pin rule accepting a date that names no calendar day: `test_every_unpinned_form_is_refused_and_names_unpinned`, `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`; the pin rule stripping the version instead of refusing it: `test_every_unpinned_form_is_refused_and_names_unpinned`, `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`; the fixture report counting every repeat-pass call as a verdict call: `test_plan_p_f_1_every_fixture_response_carries_ledger_verdicts`; the V2 budget stop logging the V1 track's message: `test_each_shadow_budget_stop_logs_its_own_event_and_message`; the policy passing a claim text outside its span: `test_a_claim_item_passes_only_with_a_public_quotable_span_and_its_own_text`; refused calls not logged: `test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged`; the semantic backend's D-23 refusal not logged: `test_plan_e_a_semantic_setting_without_the_d_23_opt_in_names_its_refusal`; the inactive reason hiding the missing opt-in: `test_plan_e_a_semantic_setting_without_the_d_23_opt_in_names_its_refusal`; the API env template's retired `OPENAI_CHAT_MODEL` assignment restored: `test_plan_e_the_legacy_provider_code_is_retired_and_no_production_path_reached_it`; the observability runbook's pre-fix text: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the deployment runbook's pre-fix text: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the payload register's pre-fix text: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; ADR-006's pre-fix text: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the Phase 3 spec's pre-fix text: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the registry document's pre-fix text: `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package`.
- The review-2 commit (section 18), 35: the embedding problem ignoring open provider decisions, ignoring the Q-15 review and ignoring the pin: `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`; the embedding key in the URL and an embedding call reserving no budget: `test_the_embedding_adapter_sends_its_key_in_a_header_and_spends_from_the_gateway_s_budget` (and `test_an_embedding_call_needs_a_key_an_open_gateway_and_budget_and_a_breach_stops_the_gateway`); an embedding error raised inside its `except` block: `test_every_embedding_failure_is_bounded_and_raised_with_no_cause_context_or_key`; the retrieval engine reading a key from the settings: `test_plan_h_the_semantic_backend_is_off_by_default_and_needs_span_ids`, `test_the_allow_list_is_the_one_recorded_exception`; the shared budget refusing nothing and alerting every time: `test_the_shared_budget_is_one_budget_for_every_instance_with_one_alert_a_day`; the process gateway keeping a per-process budget: `test_the_process_gateway_spends_from_the_shared_budget_and_keeps_the_shared_stop`; the shared stop never read, never written, and the operator command clearing nothing: `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`; the process cache per process: `test_the_process_cache_is_the_shared_cache_and_the_seam_empties_it`; the shared cache storing raw keys, evicting nothing and not refreshing a hit: `test_the_shared_cache_is_one_cache_for_every_instance_under_keyed_digests`; the loader accepting any budget scope, any stop scope, an unmarked alignment block and an unmarked correction block: `test_v4_structural_errors_always_stop_the_load`; the old unused-provenance message: `test_v4_names_the_entry_schema_whose_provenance_fields_it_fills`; the lifespan logging no semantic warning, and the warning naming no reason: `test_plan_e_the_start_up_semantic_warning_names_its_reason`; the record naming one kill switch for both: `test_ac_5_6_a_mid_response_loss_and_each_kill_switch`; the policy's plane check removed: `test_a_span_record_outside_the_public_plane_is_refused_as_non_public`; the retired module's `.env` sentence removed: `test_plan_e_a_retired_setting_is_named_at_start_up_and_its_value_never_logged`; the gateway docstring's pre-fix scope, wrapped across lines: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the downgrade keeping `gateway_stops`: `test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows`; the Phase 2 spec's and the observability runbook's pre-fix `semantic.inactive` rows, the deployment runbook's bullet without the start-up line, its per-instance stop and ADR-006's pre-fix scope: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; a changed module left out of the test strategy: `test_phase5_docs_the_test_strategy_maps_every_test_module_the_phase_added`.
- The review-3 commit (section 18), 37: the eligibility's and a call's budget reads unguarded: `test_a_budget_store_failure_makes_members_unavailable_without_a_stop_or_a_raise`, `test_ac_5_6_a_shared_store_failure_fails_closed_and_every_response_keeps_its_ledger_record`; the shared cache's get, put and evict unguarded: `test_a_shared_cache_whose_store_fails_misses_and_skips_and_never_raises` (and the F-1 test for get and put); an embedding request reading no shared stop: `test_an_embedding_request_adopts_a_stop_another_instance_wrote`; an embedding request skipping the payload policy, the policy letting a query leave and admitting any document text: `test_an_embedding_request_passes_the_payload_policy_before_it_leaves`; the embedding caps not enforced: `test_the_embedding_caps_bound_each_request_before_anything_is_sent`; an embedding call reserving once, not per attempt: `test_a_retried_embedding_call_succeeds_within_its_bound_and_each_attempt_is_reserved`, `test_an_embedding_call_needs_a_key_an_open_gateway_and_budget_and_a_breach_stops_the_gateway`; an attempt reserving one unit whatever its inputs: `test_the_embedding_adapter_sends_its_key_in_a_header_and_spends_from_the_gateway_s_budget`; an embedding budget store failure escaping: `test_an_embedding_budget_store_failure_sends_nothing_and_does_not_stop_the_gateway`; an HTTP retry reserving nothing, and a refused retry not stopping the gateway: `test_every_retry_an_adapter_sends_is_reserved_and_a_refused_retry_stops_the_gateway`; a retry's store failure stopping the gateway: `test_a_budget_store_failure_makes_members_unavailable_without_a_stop_or_a_raise`; the loader reading the embedding model unpinned: `test_the_embedding_entry_is_versioned_configuration_and_names_no_unpinned_model`, `test_ac_5_10_an_unpinned_embedding_model_makes_start_up_fail`; the loader accepting an embedding model while the gates are open: `test_the_embedding_entry_is_versioned_configuration_and_names_no_unpinned_model`; the provider gates ignoring Q-15: `test_a_non_fake_member_waits_for_the_q_15_payload_review_as_the_embedding_egress_does`, `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`; the embedding egress giving an embedder once every check passes: `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`; `/ready` reporting no embedding entry, and disclosing the stop reason and a switch: `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome` (and the shared-stop test); a kill switch withholding again, the record letting a kill switch withhold, and `v2_kill_switch` standing without a switch: `test_ac_5_6_a_mid_response_loss_and_each_kill_switch` (and `test_a_kill_switch_runs_the_zero_path_with_no_call`); an unreadable shared stop raising into a call: `test_an_unreadable_shared_stop_keeps_the_state_and_never_raises_into_a_call`; an unwritable one raising out of `stop()`: `test_an_unwritable_shared_stop_still_stops_this_instance_and_says_so`; a cleared stop reopening a running instance: `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`; `/ready` reporting the backend's state instead of the effective one: `test_d9_ready_reports_the_p1_floor_threshold_in_force_and_the_effective_semantic_state`; `_build_fields` reading a table besides the shared stop: `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`; the Phase 3 spec's test-31 line, the Phase 4 spec's loader line, the cache docstring, the `GatewayStopped` docstring and the observability runbook's logger sentence and stop row, each restored: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`; the registry document's embedding caps: `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package`.
- The review-3 check commit (section 18), 8: the observability runbook's, 10.4's and the 7.1 import rule's pre-fix logger sentences, each restored; each of the three in its current form naming `gateway.retired_setting` on `qcai.api`; the runbook's security-event clause removed; `_warn_retired_provider_settings` logging on `qcai.api` with the texts unchanged: `test_phase5_docs_name_the_logger_each_phase5_event_logs_on`.

The other rules sections 4-12 describe have their tests (13.1, 13.2) but are not yet mutation-checked, among them: the fake-outside-development and non-fake refusals of the loader, the endpoint refusal, the retry bound, budget eligibility, the identifier scan, the deferred secret stop, `family_verdict`, `mode_for`, the D-29 (a) cells, the re-tally from memory, tiers, the alignment rule, the cycle cap and X2, fresh run state and post-render hooks, the explicit-hook precedence, each `_v2_rules` and `_v3_rules` rule, the factored defaults, `ACCEPTED_ABSTENTION_REASONS` v3, the `on` decision derivation, `_provenance_problems` v3, the `pending_v3_intents` filter, the cache key fields and type refusals, the settings defaults and `on` refusals, the requested-only gateway stop, the retired-setting warning, `/ready`, the override keys, the egress scanner rules, the golden comparison and `run_v1_fixtures`'s `model_gateway="off"`.

---

## 14. CI changes (`.github/workflows/ci.yml`, job `api-and-evaluation`)

After the v2 package check:

```yaml
      # Phase 5: configuration package v3 stays readable for one release (DI-84).
      - run: python scripts/config_package.py --check --path apps/api/app/config_package/v3.json
      # Plan Phase 5 P/J: F-1 (ledger verdicts for 100% of fixture responses) and fault injection, one to three
      # providers down, on development fakes (fixture measurements, not E2 results). Exit 3 is an F-1 or matrix stop;
      # exit 5 a V2 call after a V1 fail or a delivery without a passing vote.
      - run: python scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
      # E12: the shipped non-development learner answer bodies equal Phase 4's (sha256 only; no corpus text committed).
      - run: python scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json
```

The v1 and v2 package checks stay (DI-42, DI-63). The PostgreSQL matrix, the frontend job, `api-image-boundary-scan` and `release-artifacts` are unchanged; the new tests run in both suites. No CI step makes a network call beyond `pip install`, `pip-audit` and `npm audit`.

---

## 15. Docs and evidence

1. **This spec** as `docs/architecture/phase5-implementation-spec.md`, LF. Section 4 holds plan F's degraded-mode matrix (4.10) and the gateway algorithms.
2. **`docs/adr/ADR-008-model-gateway-and-v2-panel.md`:** `## Context` (E-42, E-43, E-66, E-109, R-06, R-10, R-20, R-21, R-24, R-47, R-48; holds H6, H8, H9, H14); `## Decision 2026-11-21 (Phase 5: provider-neutral gateway and V2)`; `## Consequences`; `## Residuals` (plan M, quoted exactly: "Residual: correlation unmeasured until E2."; production permanently ZERO while the registries are empty; the provisional tool names, DI-86; an instance that adopted a stop keeps it until it is replaced; the learner band and novice tier waiting for Phase 8).
3. **ADR-006:** an appended `## Revision 2026-11-21 (Phase 5: provider egress, keys and redaction)`.
4. **ADR-005:** the in-place D-20 bullet edit (7.6).
5. **Plan F deliverables:** `docs/architecture/gateway-registry.md` (the adapter registry per environment and the degraded-mode matrix; test 39); the matrix in ADR-008; `docs/security/payload-register.md` (Q-15: per item kind, every field, its source, its plane and its bound, and what is never sent, the embedding item included; status owner review pending, DI-71; H6's release evidence); `docs/security/provider-terms-record.md` ("Q-09 is unresolved; no provider terms are recorded; no provider is registered; package v4 `gateway.terms` is null", DI-70).
6. **`docs/evaluation/phase5/README.md`:** reproduction, the scenarios, the F-1 definition (R-g), "fixture measurements, not research results", and that V-2 and V-4 are E2 results (plan H).
7. **`docs/testing/test-strategy.md`:** the E15 exit-gate edit; `## Phase 5 acceptance map (plan Phase 5 K)` after Phase 4, with `### Phase 5 test files` and an `**Exit gate.**` paragraph.
8. **`infra/cloudrun/deployment.md`:** `## Phase 5: gateway and V2 (runbook)`: the D-05 cloud writes; what ships and its defaults; the pre-release checks and the Phase 5 revision's Alembic step; the `/ready` checks; the stop conditions, the shared stop and the operator's clear; rollback is `MODEL_GATEWAY=off` (plan L "Flag off returns to Phase 4"); registering any model follows plan 13.9 (a) and needs DI-69, DI-70, DI-71 and DI-72 closed; the ledger export before a digest rollback past a v3 row.
9. **`infra/cloudrun/observability.md`:** `## Phase 5 SLIs: gateway and V2 (plan Phase 5 I)`: the log-based metric of each of verification completion, time per degraded mode, p95 per stage, cost per response and the 80% budget event, all "Not set up yet" (DI-80), and every new override key.
10. **`infra/cloudrun/provider-key-rotation.md`:** 7.5.
11. **The Phase 3 and Phase 4 specs:** the in-place edits of 7.6.
12. **BEP-2-12** (outside the repository): `phase05/PHASE_RECORD.md` (current state first, then `## History`, one row per round); `phase05/CLOSURE_EVIDENCE_NOTES.md` (R-06, R-10, R-20, R-21, R-24, R-46, R-47, R-48); the register rows PD-22..PD-31 and DI-69..DI-88 under `## Phase 5`; `00_meta/check_records.py` `check_p5_*` checks and the E15 edit.

---

## 16. Provisional defaults and deferred items (appended under `## Phase 5`)

### 16.1 Provisional defaults

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-22 | D-23 provider egress opt-in (SL) | 18.4: "D-23 RECOMMENDATION: provider egress needs a per-environment opt-in [Evidence E-109]; invariant 8 [Risk R-10]. SL." | `MODEL_EGRESS_PROVIDERS` lists the opted-in providers per environment, empty everywhere including development. Fakes need none. The semantic backend's embedding egress needs `openai-embeddings`, then the gateway's other checks (spec 4.19). | `config.py`; v4 `gateway.egress`, `owner_decisions.D-23` |
| PD-23 | D-29 REDUCED-1 tiers (PI) | 18.4: "D-29 OPEN DECISION: REDUCED-1 tiers: (a) withhold tiers 1-2, queue (RECOMMENDATION, Phase 5 item 5.9); (b) tiers 2-3 "under review" after V1 pass plus one SUPPORTED vote. Until decided, (a)" | Option (a): tiers 1-2 withheld and queued (`v2_degraded_withheld`), tier 3 by its rule on the remaining verifier; no "under review" state; routing table `degraded-matrix-v1` | v4 `v2.voting.matrix`, `owner_decisions.D-29` |
| PD-24 | D-07 pinned model set (PI, PO) | 18.3: "D-07 \|Pin gateway models (PI, PO) \|(a) Table XIV rule, pinned \|Preview default [Risk R-24]" | Option (a)'s rule only: `pinned-version-v1` refuses a missing version or a moving alias in every registry. No model is chosen (D-12, Q-09 open), and staging and production are empty. | v4 `gateway.pinning`, `owner_decisions.D-07` |
| PD-25 | V2 tiers, the tier-3 threshold (Q-22) and the alignment rule | 5.6 "tier 1 1oo3, tier 2 2oo3, tier 3 equal weights"; plan L798-800 "[PROV] values and the unspecified X4 margin, V1.3 threshold, V1.9 band and tier-3 threshold MUST be frozen in versioned configuration before use (Q-22; Decision D-06), never reported as results." | `context-tier-v1` (assessment context 1, default 2, no expert mode); tier 3 equal weights 2/3 (`provisional_until "Q-22 (DI-52)"`): an engineering value, because the plan gives no tier-3 threshold (Q-22 lists it UNVERIFIED / REQUIRES ACCESS), and unused while `expert_mode` is null; alignment `1ooN-leakage-v1`, objective from the lesson summary, the V1.9 band, ratings never gate | v4 `v2.tiers`, `v2.voting`, `v2.alignment` (each marked provisional, record PD-25) |
| PD-26 | Caps and budgets (A-15 open; hold H9) | 5.10 "Token, timeout and retry caps; daily budget hard stop"; I "alert at 80% of budget"; A-15 "No budget figure exists" | Development fakes: 256 tokens, 500 ms, 1 retry, 1 unit per call, 100000 units a day. Staging, production and default: 0 units (every adapter ineligible). Alert at 4/5. Each registry's budget is shared by every instance (one row per UTC day), and every attempt an adapter sends reserves its cost, retries included. The embedding egress (v4 `gateway.embeddings`, marked provisional, record PD-26): no model while the provider gates are open, 256 inputs per request, 8000 characters per input (the token cap), 10 s, 2 retries, 1 unit per input. | v4 `gateway.budgets`, registry caps, `gateway.embeddings`; `gateway/controls.py` |
| PD-27 | The evidential cache (engineering parameters) | 5.7 (no bounds given) | Shared by every instance in the application database, each key stored as a keyed digest, the least recently used entries evicted beyond 1024 claim plans and 8192 verdicts; the envelope-hash claim-plan key and the union verdict key (conflict 3); generation-1 plans of a wired generator only | v4 `gateway.cache` |
| PD-28 | `MODEL_GATEWAY` and the kill switches (freeze, D-05) | Phase 5 G "One release of shadow dual-run, then flag cutover"; L "Flag off returns to Phase 4"; 13.6 | Development `shadow`, elsewhere `off`; `on` refused outside development before `phase5_exit_passed`, and refused unless V1 enforces; per-adapter kill switch; `abstain_only` and `pre_verified_only`; a runtime stop, shared by every instance of the registry, turns the effective mode off for the life of every stopped instance: an operator clears the stored stop (`python -m app.workers.gateway_stop --clear`) and replaces the instances (a new revision); under `on` a kill switch abstains | `config.py`; v4 `flag_policy.model_gateway`, `gateway.stop`; env example |
| PD-29 | D-25 critical-claim registry (PI); correction | 18.4 "D-25 OPEN DECISION: critical-claim registry triggering X1"; 5.8 "Correction: two cycles, then abstain and mark X2 when critical; Type E re-renders only."; AC-5-7 | Registry empty. Every claim failing two cycles is abstained and marked X2 (conflict 6). A claim whose objections are all EHMF type E (presentation) is re-rendered only, never revised; any other failing claim is revised against the cited span, or re-verified unchanged when the generator cannot revise; no claim is deleted by the track. | v4 `v2.correction` (its `type_e`, `other` and `exhausted` rules, which the loader binds to the code), `owner_decisions.D-25` |
| PD-30 | The zero-member path and degraded banners (R-48) | 5.11 "Zero members: pre-verified module content (stage 4) or abstain and queue"; 5.9 "with visible banner" | No pre-verified source exists (`null`): withhold and queue, the record naming the D-20 replacement the learner received; under `on` the kill switches abstain and queue (`pre_verified_only` too, while no source exists). The three banner texts (the ZERO one: "only quoted course passages or no answer is shown"), shown nowhere until delivery exists (DI-85). | v4 `v2.degraded` |
| PD-31 | The tool contracts' names and transport (no owner decision named; an engineering choice like PD-27) | 7.4: "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]"; 5.2: "transport is an implementation choice [VBT RevB: p. 5, Sec. III-B]" | The paper's five server names (corpus, citation, learner, verification, analytics) with this phase's own tool names, versioned `mcp-tools-v1` (`corpus.retrieve`, `corpus.span_text`, `citation.resolve`, `learner.presentation_plan`, `verification.verdict`, `verification.alignment`, `analytics.record_outcome`), and the in-process transport; ratified under DI-76; the paper's tool names are DI-86 | v4 `tools` (`provisional: true`, `record`); `app/gateway/tools.py`; `schemas/tool-contracts.v1.json` |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-69 | Plan P "D-07 closed" and hold H8 ("Pinned registry"): the owner pins the model set (Table XIV rule). Blocked by: the OPEN owner decision D-07 (PI, PO). | PI / PO | Open |
| DI-70 | D-12 and Q-09 (A-11: no negotiated provider agreements): the provider and the terms in force; the terms record; then a provider-specific adapter, its registration outside development by plan 13.9 (a), and hold H6's release (its evidence, the payload register, needs DI-71). Blocked by: the OPEN owner decision D-12 and the unresolved factual question Q-09 (PO, counsel). | PO / counsel, then Eng | Open |
| DI-71 | Q-15: owner review of `docs/security/payload-register.md` (the claim, alignment and embedding items) before any non-fake adapter is registered (the loader enforces it through `registry.providers_open`). The learner's query text stays barred from an embedding request by plan H whatever the review says (spec 4.19). Blocked by: the Security Lead's review, an owner decision (Q-15 is open). | SL | Open |
| DI-72 | A-15 and hold H9 ("P5 panel"; release evidence "Approved budget"): owner-approved budget ceilings and prices (A-14). The shared, cross-instance budget store exists (`gateway_budget_days`, spec 4.4). Blocked by: the OPEN assumption A-15 (no budget figure exists; the PO approves ceilings) and hold H9. | PO, then Eng | Open |
| DI-73 | Hold H14 (D-21 local hosting) at the P5 exit: with no local model, production is permanently ZERO (the zero-member policy, PD-30). Blocked by: the OPEN owner decision D-21. | PO | Open |
| DI-74 | The Phase 5 exit: AC-5-1..AC-5-11 green in a cited CI run on `main`. `phase5_exit_passed` stays false while D-07, D-12, Q-09, A-15 and D-21 are open, holds H6, H8, H9 and H14 hold, and the Phase 4 exit is not passed (DI-58). The plan-P CI item is met: PR #37 was squash-merged on 2026-11-22 as `main` `c34a8c1` (tree identical to `8aa4ff1`); PR run 45043411679 and branch push run 45042478870 at `8aa4ff1` passed every job (release-artifacts skipped by design), and main run 45044415408 at `c34a8c1` passed every job and is the cited run for AC-5-1..AC-5-11. The exit is not passed. Blocked by: the OPEN owner decisions D-07, D-12 and D-21, Q-09 and A-15 (DI-69, DI-70, DI-72, DI-73) and the Phase 4 exit (DI-58). | Eng / PI | Open |
| DI-75 | E2 (research plane, D-14, Phase 10): V-2, V-4 and verifier correlation (plan M "Residual: correlation unmeasured until E2."); never from fixtures. Blocked by: the OPEN owner decision D-14 (the research data plane) and Phase 10. | PI / Research Lead | Deferred |
| DI-76 | Ratify PD-22..PD-31. Blocked by: owner decisions (PI, PO). | PI / PO | Open |
| DI-77 | Plan 7.1 "The gateway MUST be the sole holder of provider credentials": the semantic backend's embedding egress and its `OPENAI_API_KEY`. Closed: `app/gateway/embeddings.py` holds the egress and reads the key through the gateway's SecretStore (no Settings field), with its model, caps and cost in package v4's `gateway.embeddings`, behind the D-23 opt-in, closed provider decisions and the Q-15 review, a pinned model, a budget and an open gateway, and with no embedder given while plan H bars the learner's query text (spec 4.19); evidence `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes` and `test_the_allow_list_is_the_one_recorded_exception`. | Eng | Closed 2026-11-22 (the review-2 commit, spec 18) |
| DI-78 | Plan 7.1's separate deployment of the gateway (distinct trust). Blocked by: a deployment decision (PfO) and a cloud write (a separate service) under D-05. | PfO, then Eng | Deferred |
| DI-79 | A shared evidential cache (plan 5.7 "Shared cache", 7.5) with cross-instance invalidation. Closed: `DatabaseEvidentialCache` over `evidential_cache_entries`, keys as keyed digests, bounded per kind; a configuration or model change misses everywhere (spec 4.15); evidence `test_the_shared_cache_is_one_cache_for_every_instance_under_keyed_digests` and `test_the_process_cache_is_the_shared_cache_and_the_seam_empties_it`. | Eng | Closed 2026-11-22 (the review-2 commit, spec 18) |
| DI-80 | The Phase 5 log-based metrics and alerts, the 80% budget alert policy included. Blocked by: a cloud write under D-05. | PfO | Defined, not created |
| DI-81 | Remove `VERTEX_AI_*` from the Cloud Run service, and retire or disable the old provider key and secret. Blocked by: cloud writes under D-05. | PfO | Not started |
| DI-82 | The paper's learner band in the alignment item and novice-learner tier 1: need the Phase 8 learner model, an invariant-1 review and a Q-15 payload review. Blocked by: learner-facing capability outside development (the Phase 8 learner model; D-27 consent classes OPEN) and the Q-15 review (DI-71). | PI, then Eng (P8) | Deferred |
| DI-83 | A pre-verified module content store (stage 4) for the zero-member path. Blocked by: an owner decision on which module content is pre-verified (CO, PI); under D-31 no asset is approved, so no such content may be served. | CO / PI, then Eng | Deferred |
| DI-84 | Remove configuration package v3 after one release, with its CI step. Blocked by: a production release under D-05 (v3 stays readable for the release after the Phase 5 merge). | Eng | Deferred |
| DI-85 | The flag cutover after one release of shadow dual-run (plan G) and the delivered path's V2 behaviour (the degraded banner shown to learners, and the kill switches' abstention reaching them), with DI-59; plan 7.4's F-1 over delivered responses with DI-36. Blocked by: the Phase 5 exit (DI-74), a production release under D-05, and learner-facing capability outside development. | PO, then Eng | Deferred |
| DI-86 | Plan 7.4 "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]": reconcile the tool names of `mcp-tools-v1` (PD-31) with the paper's supplementary materials, then version the contracts again if they differ. Until then the names are this phase's own and provisional. Blocked by: A-18 ("Supplementary materials unavailable"; the Principal Investigator supplies them, Q-14), an UNVERIFIED input. | PI, then Eng | Open |
| DI-87 | A shared, durable gateway stop (plan Phase 5 L "Stop on a payload violation, secret in logs or budget breach."). Closed: the stop is written to `gateway_stops`, every instance and every new process adopts it before its next eligibility decision or call (an embedding request included), only the operator's `python -m app.workers.gateway_stop --clear` removes the stored stop, and a stopped instance stays stopped until it is replaced (spec 4.5); evidence `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it` and `test_an_embedding_request_adopts_a_stop_another_instance_wrote`. | Eng | Closed 2026-11-22 (the review-2 commit, spec 18) |
| DI-88 | The API's developer env template (`apps/api/.env.example`) is unchecked, because no agent reads it: whether its text about `OPENAI_API_KEY` (now read by the gateway's secret store from the process environment, not from a `.env` file through Settings) and its `OPENAI_EMBEDDING_MODEL` assignment (found by a names-only scan, the acceptance test's own rule) state the current code is unchecked: the embedding model is package v4's `gateway.embeddings`, so the variable is ignored, and it is no retired setting because a retired name the template assigns fails that test. Blocked by: the binding rule that no agent opens or reads a `.env` file (the owner reviews the template). | Owner, then Eng | Open |

---

## 17. Verification, work order and exit

**Work order (commits on the branch).**
1. **E15: the Phase 4 records after the merge** (a separate first commit, docs and one test only): the Phase 4 spec's DI-58 row, section 17's exit and CI bullets and one Merge row in its history table; the test strategy's Phase 4 exit gate; `test_phase4_docs_the_ci_records_name_the_latest_branch_run`; `check_records.py`'s `check_p4_r5_the_phase_4_records_name_the_latest_branch_run` (it passes on the new spec and fails on the pre-merge one).
2. **The golden and the guard.** `scripts/capture_public_payloads.py` and its golden written on the unchanged application tree; `tests/network_guard.py`, the `conftest.py` install and its test.
3. **Gateway, V2, package v4, retirement.** Every module of section 7, the package, the start-up and `/ready` changes, the D-23 gate on embeddings, the tests of section 13 and the 13.3 changes.
4. **Records and docs.** `run_v2_fixtures.py` and its report; the re-written Phase 3 and 4 records (their `inputs` hash every imported module); the docs, ADRs, runbooks, env example, CI and test strategy; the BEP records and registers.
5. **Review rounds.** Each round's fixes in their own commits, after the build (section 18 names them).

**Commands.** `<py>` is the scratch venv's python.

```
<py> -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests -p no:cacheprovider
<py> scripts/validate_corpus.py --check-public-assets --check-recall-stop
<py> scripts/validate_lqs.py --allow-draft
<py> scripts/config_package.py --check
<py> scripts/config_package.py --check --path apps/api/app/config_package/v3.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v2.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v1.json
<py> scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
<py> scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
<py> scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json
<py> scripts/authorization_matrix.py --check
<py> scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
<py> scripts/generate_manifest.py --check
<py> scripts/validate_corpus.py --check-hashes --check-near-duplicates
<py> scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
<py> scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report <scratchpad>/boundary.json
<py> D:\QC_AI_Studio\BEP-2-12\00_meta\check_records.py
cd apps/frontend && npm run lint && npm run typecheck && npm run test:integration
git status --short   (no stray files; nothing in the repository root)
```

**Scratch PostgreSQL 17.** Never the installed server's data directory, and never pipe `pg_ctl` output; ports 55024-55623 are reserved, so 57433. `initdb` into the scratchpad, `pg_ctl … -o "-p 57433" … start`, `createdb qcai_test`; the suite with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:57433/qcai_test`, then with `postgresql+pg8000://…` on a fresh database; `pg_ctl … stop`.

**Exit (plan P).**
- Plan P: "AC-5-1 to AC-5-11 green in a cited CI run; D-07 closed; ledger verdicts for 100% of test responses (F-1)."
- The AC tests and F-1 over the fixture responses are done in code. The earlier push run 44998840311 at `3498b52` passed every job. PR #37 was squash-merged on 2026-11-22 as `main` `c34a8c1` (tree identical to `8aa4ff1`); PR run 45043411679 and branch push run 45042478870 at `8aa4ff1` passed every job (SQLite, PostgreSQL 16 under psycopg and pg8000, the frontend and the image boundary scan; release-artifacts skipped by design), and main run 45044415408 at `c34a8c1` passed every job and is the cited run (DI-74). "D-07 closed" is an owner decision (DI-69). Holds H6, H8, H9 and H14 stay held (DI-70, DI-69, DI-72, DI-73).
- `phase5_exit_passed` stays `false`.

---

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | — (sections 0-17) | The design: `test_ac_5_1_the_panel_never_holds_the_generator_s_family_for_any_registry_ordering`, `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`, `test_plan_l_flag_off_returns_to_phase_4` |
| Spec review 1 (pre-code) | — (sections 0-17) | A correction candidate and every re-render are judged with fresh V1 state: `test_every_rendering_is_judged_with_a_fresh_post_render_hook`, `test_invariant_3_v2_never_overwrites_a_v1_hard_fail`<br>The claim-plan cache keys on the envelope hash (lesson scope included): `test_the_claim_plan_key_holds_the_envelope_so_another_lesson_scope_misses`, `test_ac_5_11_two_learners_share_only_evidential_entries_and_a_model_change_misses`<br>In `on` the record's decision follows the V2 final, and the V2 record's final reasons are a parameter of the shared rule body: `test_ledger_entry_v3_rules_and_the_on_record_s_decision_follows_its_final`<br>No claim is deleted; an unrevisable claim is re-verified unchanged and ends with X2: `test_ac_5_7_a_claim_failing_two_correction_cycles_is_abstained_and_marked_x2`<br>Eligibility precedes the panel, and an unknown generator family fails closed: `test_eligibility_precedes_the_panel_so_a_spare_family_or_a_second_adapter_represents_a_lost_one`, `test_ac_5_1_a_panel_with_the_generator_s_family_cannot_be_built_or_recorded`<br>The adapter raises outside its `except` block: `test_ac_5_9_a_provider_error_leaves_no_key_authorization_header_or_query_in_logs_or_exceptions`<br>The secret listener only sets a flag, and a stop turns the effective mode off: `test_plan_l_a_secret_reaching_a_log_stops_the_gateway`, `test_plan_l_a_payload_violation_stops_the_gateway_with_a_security_event`<br>One process gateway with a per-call policy context: `test_the_policy_context_is_per_call_so_one_gateway_serves_pipelines_over_different_stores`<br>A non-pin gateway problem stops start-up only when the gateway is requested: `test_plan_g_model_gateway_defaults_and_refusals`<br>The egress guard's import rule covers the API image, its host rule the scripts: `test_the_scanner_catches_each_rule_s_sample_and_passes_what_is_not_egress`<br>The golden goes through the orchestrator and the Q&A engine over all 298 queries: `test_freeze_public_payloads_with_shipped_non_development_settings_are_byte_identical_to_phase_4`<br>The 13.6 flag combinations are enumerated: `test_plan_13_6_flag_combinations_never_disable_v1_or_deliver_unverified_text`<br>Section 3's blocks parse as Python: `test_phase5_spec_section_3_lists_the_code_s_fields` |
| Build | the commit after `e992209` | Only a wired generator's claim plans are cached (a test double sharing the extractive ref returned another plan): `test_generation_1_reads_the_cache_and_a_cached_plan_that_hard_fails_v1_1_is_evicted`, `test_j1_two_claim_orders_that_lock_one_claim_set_give_one_ratio_and_no_stop`<br>The process gateway and cache are read per run, never kept on a cached pipeline: `test_ac_5_3_captured_verifier_prompts_hold_no_generator_identity_votes_learner_ids_text_or_history`<br>The invariant-1 fixture starts each learner from a cold cache: `test_j2_a_learner_dependent_threshold_fails_the_invariant_1_fixture`<br>A response delivers only when its alignment item passed, and with no member left its claims are withheld: `test_with_no_member_left_for_the_alignment_item_the_claims_are_withheld`<br>The V1 fixture runner measures V1 alone (`model_gateway="off"`): `test_ac_4_2_the_committed_fixture_report_matches_a_fresh_run_and_its_hashes_match_the_package`<br>The committed V2 report's module map is compared with the checkout and with the modules a fresh run imported, not with a test process's whole map: `test_plan_p_the_committed_v2_fixture_report_matches_a_fresh_run_and_names_its_evidence_class`<br>In shadow, V1's rendering omits a V1.3-flagged claim as with V2 off (only `on` routes V1.3 flags to V2): `test_in_shadow_v1_withholds_and_renders_a_v1_3_flagged_claim_as_with_v2_off` |
| Review 1 | the commit after `d4d4d80` | A claim-level type E objection re-renders only, never revised: `test_ac_5_7_a_claim_level_type_e_objection_is_re_rendered_and_never_revised`, `test_v4_structural_errors_always_stop_the_load`<br>Verification completion counts a withheld response as withheld, and time in mode moves only on panel-reaching responses: `test_plan_i_v2_metrics_report_completion_time_degraded_p95_cost_and_the_budget_event`<br>The tool names and transport are PD-31, the paper's names DI-86: `test_phase5_docs_quote_the_plan_and_state_the_current_rules`, `test_v4_structural_errors_always_stop_the_load`<br>An undecodable body or any other httpx error is an `AdapterError`, and the gateway turns any other adapter exception into one: `test_retries_are_bounded_and_every_failure_is_raised_with_no_cause_or_context`, `test_an_adapter_that_raises_anything_else_is_only_unavailable_at_the_gateway`, `test_ac_5_9_a_provider_error_leaves_no_key_authorization_header_or_query_in_logs_or_exceptions`<br>The tier-3 threshold is bound to 2/3 while Q-22 is unresolved, so the record rule re-tallies with the value in force: `test_v4_structural_errors_always_stop_the_load`<br>The pin rule refuses glued aliases, impossible dates and non-canonical identifiers: `test_every_unpinned_form_is_refused_and_names_unpinned`, `test_ac_5_10_an_unpinned_identifier_makes_start_up_fail`<br>The fixture report splits claim and alignment calls: `test_plan_p_f_1_every_fixture_response_carries_ledger_verdicts`<br>The HTTP body carries the fixed instruction text, and a reported cost above the reservation stops the gateway: `test_the_http_adapter_sends_the_key_in_a_header_with_its_caps_and_returns_the_output`, `test_a_request_naming_another_prompt_hash_is_refused_before_any_call`, `test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged`<br>A fake keeps no request unless asked: `test_a_fake_keeps_no_request_unless_a_test_asks_it_to`<br>The V2 budget stop logs its own message: `test_each_shadow_budget_stop_logs_its_own_event_and_message`<br>A claim item's text must lie inside its span, and refused calls are logged: `test_a_claim_item_passes_only_with_a_public_quotable_span_and_its_own_text`, `test_a_call_costing_more_than_its_reservation_stops_the_gateway_and_refused_calls_are_logged`<br>The D-23 refusal of semantic retrieval is logged and named at start-up: `test_plan_e_a_semantic_setting_without_the_d_23_opt_in_names_its_refusal`<br>The API env template assigns no retired setting: `test_plan_e_the_legacy_provider_code_is_retired_and_no_production_path_reached_it`<br>13.5 records only the checks performed; the observability table, the per-instance stop (DI-87), the export path, the payload register, the egress guard's scope, the registry document and the texts Phase 5 made false (7.6) are current: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`, `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package` |
| Review 2 | the commit after `3498b52` | The embedding egress and `OPENAI_API_KEY` are the gateway's, behind D-23, closed provider decisions, the Q-15 review, a pin, a budget and an open gateway (DI-77 closed): `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`, `test_the_embedding_adapter_sends_its_key_in_a_header_and_spends_from_the_gateway_s_budget`, `test_every_embedding_failure_is_bounded_and_raised_with_no_cause_context_or_key`, `test_the_allow_list_is_the_one_recorded_exception`<br>The daily budget is shared by every instance (DI-72's store): `test_the_shared_budget_is_one_budget_for_every_instance_with_one_alert_a_day`, `test_the_process_gateway_spends_from_the_shared_budget_and_keeps_the_shared_stop`<br>A stop is shared and durable until an operator clears it (DI-87 closed): `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`<br>The evidential cache is shared under keyed digests (DI-79 closed): `test_the_shared_cache_is_one_cache_for_every_instance_under_keyed_digests`, `test_the_process_cache_is_the_shared_cache_and_the_seam_empties_it`<br>The three tables' migration, through which the Phase 3 revision's tests now step: `test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows`, `test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp`, `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger`<br>The start-up `semantic.inactive` line is tested through the lifespan, and the Phase 2 spec's and the observability runbook's rows give its `reason`: `test_plan_e_the_start_up_semantic_warning_names_its_reason`, `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`<br>The egress guard's scope is exact (`apps/api/tests` unscanned, `evaluation/tests` scanned) and compared with wrapped lines folded: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`<br>The record names each kill switch; with no pre-verified source both give the same finals: `test_ac_5_6_a_mid_response_loss_and_each_kill_switch`<br>The ZERO banner claims no checked content: `test_ac_5_6_the_degraded_banners_claim_no_check_the_learner_does_not_get`<br>Every provisional v2 sub-block carries its mark, and PD-25 calls 2/3 an engineering value: `test_v4_structural_errors_always_stop_the_load`<br>The payload policy's plane check is tested on its own: `test_a_span_record_outside_the_public_plane_is_refused_as_non_public`<br>The retired module and the loader state their scope exactly: `test_plan_e_a_retired_setting_is_named_at_start_up_and_its_value_never_logged`, `test_v4_names_the_entry_schema_whose_provenance_fields_it_fills`<br>The test strategy maps every module the phase changed: `test_phase5_docs_the_test_strategy_maps_every_test_module_the_phase_added` |
| Review 3 | the commit after `6a56107` | A fault of the shared budget or cache store fails closed, and every response keeps its ledger record (F-1): `test_ac_5_6_a_shared_store_failure_fails_closed_and_every_response_keeps_its_ledger_record`, `test_a_budget_store_failure_makes_members_unavailable_without_a_stop_or_a_raise`, `test_a_shared_cache_whose_store_fails_misses_and_skips_and_never_raises`, `test_an_embedding_budget_store_failure_sends_nothing_and_does_not_stop_the_gateway`<br>The embedding egress's model, caps (a per-input character cap for the token cap) and cost per input are package v4's `gateway.embeddings`, an unpinned model stops start-up, and `/ready` and the registry document report it: `test_the_embedding_entry_is_versioned_configuration_and_names_no_unpinned_model`, `test_ac_5_10_an_unpinned_embedding_model_makes_start_up_fail`, `test_the_embedding_caps_bound_each_request_before_anything_is_sent`, `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package`, `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome`<br>Every embedding request passes the payload policy: a query (learner text) is refused under plan H, so the gateway gives no embedder: `test_an_embedding_request_passes_the_payload_policy_before_it_leaves`, `test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes`<br>An embedding request reads the shared stop before it is sent, so a stop written during an index sync stops the next batch: `test_an_embedding_request_adopts_a_stop_another_instance_wrote`<br>Every retry an adapter sends reserves its cost first, and a retry the budget refuses is not sent: `test_every_retry_an_adapter_sends_is_reserved_and_a_refused_retry_stops_the_gateway`, `test_a_retried_embedding_call_succeeds_within_its_bound_and_each_attempt_is_reserved`, `test_every_embedding_failure_is_bounded_and_raised_with_no_cause_context_or_key`<br>A kill switch abstains (pre-verified-only too while no pre-verified source exists), and the runbook says it acts on the shadow pipeline only: `test_ac_5_6_a_mid_response_loss_and_each_kill_switch`, `test_a_kill_switch_runs_the_zero_path_with_no_call`<br>The public `/ready` reports the gateway's state only, never the stop's reason or the operator's switches: `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome`, `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`<br>A stopped instance stays stopped until it is replaced, after the operator's clear too, and every text says so: `test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it`, `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`<br>A non-fake member waits for the Q-15 review too, one rule with the embedding egress: `test_a_non_fake_member_waits_for_the_q_15_payload_review_as_the_embedding_egress_does`<br>The shared stop's fail-safe paths are tested: `test_an_unreadable_shared_stop_keeps_the_state_and_never_raises_into_a_call`, `test_an_unwritable_shared_stop_still_stops_this_instance_and_says_so`<br>The Phase 2 `/ready` test reaches the not-aligned branch again: `test_d9_ready_reports_the_p1_floor_threshold_in_force_and_the_effective_semantic_state`<br>The Phase 3 spec's test 31 (and its test, which now counts the engine's statements), the Phase 4 loader line, the cache docstring and 13.1 item 40 state the current code: `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`, `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`<br>The observability runbook and 10.4 name each Phase 5 event's logger: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly` |
| Review 3 check | the commit after `56261f1` | The start-up line `gateway.retired_setting` is named on `qcai.gateway`, where `_warn_retired_provider_settings` logs it, and only `semantic.inactive` on `qcai.api`, in the observability runbook, 10.4 and the 7.1 import rule; the security events `gateway.stopped` and `gateway.stop_cleared` on `qcai.security`; the doc test that pinned the wrong text now reads every 10.4 event's logger from the source and runs the three lines: `test_phase5_docs_name_the_logger_each_phase5_event_logs_on` |
| Merge | `c34a8c1` | PR #37 squash-merged (tree identical to `8aa4ff1`); main run 45044415408 green on every job, the cited run: `test_phase5_docs_the_records_name_the_merge_and_the_cited_main_run` |
