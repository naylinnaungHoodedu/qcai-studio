# QC+AI Studio — Phase 3 Implementation Spec (reviewed)
## Provenance-first two-channel tutor (plan L1225-1284)

Repository: `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`. Branch: `phase3/two-channel-tutor`, cut from `origin/main` `72f1b5e` (Phase 2 merged, PR #34).

Plan: `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`.
- Phase 3 block: L1225-1284.
- Architecture contracts: Section 7 (L811-983).
- What consumes Phase 3: Phase 4 (L1286-1355).

Sections 0-17 state the behaviour of the code on this branch and are authoritative. Section 18 records the departures the code forced at implementation time (18.1, 18.2), the latest verification (18.3) and the review history (18.4), which may describe behaviour that a later round superseded.

How to use this spec:
- Section 0 holds the binding rules, the measured facts, the readings of the ACs, and the points the spec review settled (0.4).
- Section 1 lists every conflict between the plan and the fixed decisions, with its resolution.
- Sections 2-5 cover the architecture, contracts, algorithms and configuration package v2.
- Sections 6-12 cover settings, file-by-file changes, the database, routes, start-up and `/ready`, and the frontend.
- Sections 13-17 cover tests, CI, docs and evidence, registers, and verification.

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (restated)

**Repository and git**
- Stay on the branch: no branch switch, no `git stash`, no push, no git-config change, no history rewrite.
- Every commit message ends with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only in the scratchpad, never in the repository root. Ledger exports (`python -m app.workers.response_ledger --export`, or `scripts/verify_ledger.py --export` for a local copy) are written outside the repository.
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local` or any `.env` file. `infra/cloudrun/api-production.env.example.yaml` does not match `*.env.yaml` and may be edited.
- No Google Cloud, gcloud, gh, or provider/LLM calls. No deploys.

**Freeze (D-05 not lifted; P1-D-18 deviation)**
- Every new learner-visible behaviour sits behind a setting. Outside development that setting's default is either today's production behaviour or strictly more conservative.
- D-31 / P1-D-07: zero assets are approved, and nothing derived from an unapproved asset is served.
- D-19 containment (`contained_answers.py`) is unchanged: a learner receives an abstention or verbatim approved document spans, and `grounded` is always false.
- R1.2 (`answer_history.py`) is unchanged.
- Production `/assistant/chat` response bodies keep today's keys and values (conflict 28).

**Privacy**
- No learner identifiers, emails, secrets or reviewer names go into fixtures, logs, docs or the repository.
- Tests use uuid4-based demo ids.
- No source string literal matches `qcai_[a-z0-9_]+` (the privacy guard reads such names as cookie names); no browser-storage key `qcai-*` is added.
- No log line carries a response id, turn id, thread id or message id (keeps ledger rows unlinkable after erasure).

**Existing tests**
- No existing test or guard is weakened.
- Every changed test keeps its intent, and the commit message gives the reason (section 13.3).
- A test that would pass vacuously after the change counts as weakened.
- No new `skip`/`xfail` markers: dialect-specific assertions branch inside the test.

### 0.2 Measured facts (working tree `72f1b5e`, 2026-11-19; indicative)

| # | Fact | Consequence |
|---|---|---|
| M1 | **Phase 2 bound-claim ratio.** Every contained (legacy) claim cites exactly one resolved span.<br>• dev, `bm25f-v1`: 166/174 in-domain answered; 473 claims, 473 bound (1.000).<br>• dev, `p1-floor`: 146/174 answered; 396/396 bound.<br>• governed empty (D-31): 0/174 answered.<br>• governed all-approved: the same as dev. | The plan L stop "bound-claim ratio falls below Phase 2" has the baseline **1.0** (pinned in the package, 5.1). |
| M2 | **Extractive prototype**, for each eligible document span: whitespace-normalised sentences split on `(?<=[.!?])\s+`, at least 4 words, sharing at least 1 package-tokenizer content term with the question; at most 2 per span and 3 in all; no fallback sentence.<br>• Answers 166/174 (`bm25f-v1`) and 146/174 (`p1-floor`), equal to the legacy rate.<br>• 2.89 and 2.77 claims per answer.<br>• Claim length p50 221 / 281 chars, max 699; 0 of 2299 dev document sentences exceed 1000 chars.<br>• The off-topic and stopword fixture (124): 0 results in every configuration.<br>• Retrieval plus selection: p50 0.97 ms / p95 1.3 ms (`bm25f-v1`); 6.1 / 11.0 ms (`p1-floor`). | A shadow run costs milliseconds. The shipped generator is stricter than this prototype: it quotes whole document sentences only, under `sentences-v2` (4.5, 4.6), so on the committed replay it answers 148 (`bm25f-v1`) and 130 (`p1-floor`) of 299 all-approved items, where the legacy contained path answers 167 and 147 (7.17). |
| M3 | Top score within the margin (`near_miss`): 1 of 174 in-domain queries (`bm25f-v1`, dev). Under `p1-floor` the margin is 0, so there is never a near_miss. | `near_miss` is rare. It is recorded; it never abstains (section 4.3). |
| M4 | **Index sizes.** Dev: 1071 spans (1030 document, 41 authored), 331 index entries, `corpus-c658893abb6440dd`. Governed empty: 41 spans and 41 entries, all authored. All-approved: the same corpus_version as dev. The API image holds no DOCX (deployment runbook), so in production only authored spans exist. | Positive-path tests run on dev or all-approved. Governed empty and the production image abstain everywhere. |
| M5 | `TutorMessage.created_at` uses `server_default=func.now()`. SQLite stores whole seconds; a Python-set value keeps microseconds. PostgreSQL `now()` is the transaction start time. | Order within a thread is ambiguous within one second on SQLite, and within one transaction on PostgreSQL. Section 7.11 sets message timestamps in Python under a thread lock, never earlier than the thread's latest message (`next_message_time`, 18.5 C12): a production change to stored data that ships only with a D-05 release. |
| M6 | `app/services/claim_gate.py` (the overlap `ClaimGate`, `evidence_digest`) is imported by no runtime module and no test. Only ADR-005 and the CS595 blueprint name it. | Safe to repurpose as the subset checker (plan E). |
| M7 | Roles in code are `learner`, `instructor` and `admin` (`require_role`, STAFF). There is no `reviewer` role. Auth0 roles come from the token claim; demo roles come from `x-demo-role` in development. | Ledger readers are `("reviewer",)`, the plan text (section 9; PD-12). |
| M8 | No frontend file renders "lexically screened"; the label exists only as the API `model`/`retrieval_mode` string `extractive-lexically-screened`. `tests/answer-wording.integration.test.ts` forbids `/grounded/i` on the answer surfaces. | The Phase 1 precondition (task 1.11 label) is met in the API string only: a recorded precondition deviation (15.10, DI-34). The new panel files join the wording list. |
| M9 | `hypothesis` is not installed in the venv. | The property test uses a seeded `random.Random`. No new dependency. |
| M10 | `scripts/calibrate_abstention.py --check` compares a fresh record to the committed one. The fresh record writes `config_package_version = package.package_version`; the committed record holds `"1.0.0"`. | A version bump would fail CI without the lineage field in section 5.3. |
| M11 | `test_phase2_acceptance.py::test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis` asserts `config_package_version == "1.0.0"` and `set(slis) == {citation_resolution, abstention, search_latency_ms, manifest_drift}`. | This test changes (section 13.3). |
| M12 | Erasure targets come from metadata: every table with a user-key column, plus every table with a foreign key to one of those. | The ledger has no user column and **no foreign key** to the tutor tables; otherwise erasure would try to DELETE append-only rows and fail. |
| M13 | **Alembic and the image.** The `alembic` library is installed in the image (`requirements.txt`), but `apps/api/alembic` and `alembic.ini` are not copied (the Dockerfile copies `apps/api/app` only). `alembic_version.version_num` is VARCHAR(32). The chain cannot build an empty database (a strict xfail). | `SCHEMA_REVISION` is a code constant, checked by a test against the Alembic head. The revision id `20261119_phase3_response_ledger` is 31 characters. A production DB built by `create_all` may carry no `alembic_version` row, so the stamp names the code's expected revision (conflict 9). |
| M14 | `get_corpus_registry(settings)` constructs a new `CorpusRegistry` on every call, re-reading the manifest. | The pipeline builds one registry per run. |
| M15 | **Ownership tests.** `test_authorization.py::OWNERSHIP_TESTED` must equal the set of owner-scoped routes; `_concrete()` has no `response_id` value; `test_a_refused_caller_is_refused` expects 401 for an anonymous caller on PRINCIPAL routes (dependencies resolve before the body is validated). | Section 13.3. |
| M16 | `test_api.py` stubs `get_tutor_orchestrator()` with objects whose only method is `.chat(db, user, payload)`; one stub returns `grounded=True`. | The routes must keep calling `.chat(...)`. Follow-ups travel on a pydantic `PrivateAttr` (section 7.12). |
| M17 | **Test database.** In-memory SQLite uses `StaticPool` (`app/core/db.py`): every session and thread shares one DBAPI connection. File SQLite gets separate pooled connections. | Concurrency, tamper and trigger tests use `fresh_database_url` (file SQLite or a fresh PostgreSQL database), never the shared session DB. |
| M18 | **Per-request headers.** `X-Request-ID` (uuid4 when not supplied), a per-request CSP nonce, and slowapi rate-limit headers (`headers_enabled=True`, reset times) differ on every response. | Response-equality tests compare a named header subset (test 23). |
| M19 | **FastAPI 0.137.2** (`fastapi/routing.py:request_response`): request-scoped `yield` dependencies (`get_db`) exit after `await response(...)`, i.e. after background tasks finish. The Starlette TestClient returns only after background tasks complete. | Background shadow tasks open their own sessions; they run before the route session closes; tests see shadow records synchronously. |
| M20 | `TeachingAssistantService.chat` already calls `contain_answer` and returns `contained.citations`, so the orchestrator's `candidate.citations` are the quoted spans, not the retrieval set. | The legacy record takes the retrieval set from a non-serialised side channel (7.10), never from `candidate.citations`. |
| M21 | `pydantic` is not pinned in `apps/api/requirements.txt` (`pydantic-settings==2.14.2` and `fastapi==0.137.2` constrain it loosely); the image installs whatever resolves at build. | A structural comparison against `model_json_schema()` must not gate production start-up (5.4). |
| M22 | NFKC changes 1 of 1030 dev document spans today (U+2011 non-breaking hyphen); in general NFKC folds superscripts, ligatures and fractions (`x²` → `x2`). | Stored and rendered claim text is whitespace-normalised verbatim text; NFKC is used only for comparisons (4.1). |
| M23 | `test_structured_logging.py::test_startup_logs_what_the_instance_started_with` requires exactly one `qcai.api` record with structured fields at start-up, equal to `_build_fields()`. | New start-up and pipeline events log through `qcai.tutor`; `_build_fields()` stays deterministic and DB-free. |
| M24 | Package v1 top-level keys: `package, package_version, schema_version, phase, status, created, span_identity, corpus_version, gates, retrieval, semantic, abstention, near_duplicate, legacy_citations, owner_decisions, boundary`; `owner_decisions` holds `D-17, D-30, Q-10, PLAN-11.3`. | v2 keeps every v1 block (5.1 lists those it copies unchanged and those it changes); `owner_decisions` keeps those four unchanged and adds `D-19`, `D-12`, `PLAN-3.3` and `PLAN-12.8` (5.1). |
| M25 | Route handlers call `get_settings()` directly (`spans.py`); `app.dependency_overrides[get_settings]` reaches only `Depends(get_settings)` (for example `get_current_user`). | Route-flag tests monkeypatch the route module's `get_settings` (Phase 2 precedent), never `dependency_overrides` (test 26). |

### 0.3 Readings

**R-a. "Delivery" in Phase 3.**
- Every learner delivery is the legacy contained answer. The ledger records it with `delivery = "legacy"` and `response_id = TutorTurn.id`.
- Every shadow run is recorded with `delivery = "shadow"` and `response_id = "shadow-<uuid4>"`, linked by `shadowed_response_id = TutorTurn.id`.
- `delivery = "delivered"` (two-pass output delivered to a learner) is reserved for Phase 4: it exists in the schema, the DB check constraint and the package, but `TwoPassPipeline.run` **refuses** it while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (`DeliveryNotImplemented`). No Phase 3 code path returns two-pass text to any caller (13.6, invariant 6).

**R-b. AC-3-4** ("Given any delivered test response, then its ledger record exists and the chain verifies") is tested on:
1. every `/assistant/chat` and `/tutor/turns` response in the test (legacy records);
2. their shadow records.
After both, `verify_response_ledger` reports `ok`. Coverage of real deliveries is measured by `python -m app.workers.response_ledger --coverage-since` (the in-image worker; `scripts/verify_ledger.py --coverage-since` for a local copy), by the log-based coverage across instances (every `tutor.ledger.attempted` line ends in one terminal line with its `attempt` id, `tutor.ledger.appended` or `tutor.ledger.append_failed`; 11.4), and by the per-process `legacy_coverage_rate` SLI.

**R-c. AC-3-6** ("Given two_pass_tutor on before Phase 4 exit, then it runs in shadow only and zero of its outputs reach a learner").
- Settings refuse `on` while `flag_policy.phase4_exit_passed` is false (E1).
- Independently, Phase 3 code downgrades `on` to `shadow` and the pipeline refuses `delivered`, because no V1 module exists (`TWO_PASS_DELIVERY_IMPLEMENTED = False`).
- The test forces `on` through a test package that claims the Phase 4 exit, and observes shadow-only behaviour.
- "Zero outputs reach a learner" means all of the following:
  - the learner's response body, the named header subset, stored messages, Q&A history and thread detail are identical to those of the `off` mode;
  - a learner reading a shadow record gets 404;
  - no learner-readable store holds shadow text.

**R-d. The "learner's own turns" (3.1, AC-3-5).**
- These are the `TutorMessage` rows with `role == "user"` in the same thread. Never assistant replies, never client-supplied `history`.
- `source_turn_ids` are those message ids.

**R-e. "No learner text in the ledger" (E3).**
- The ledger stores claim text, which is corpus text: the verbatim span sentences and the delivered quotations.
- It never stores the resolved-question text, a hash of it, the rendered text (a hash only), user ids or emails.
- The resolved question is reconstructible while the learner's data exists: re-run the deterministic `thread-resolver-v1` over `source_turn_ids`.

### 0.4 Points the spec review settled (cross-reference)

Each is specified where it is named: production response bytes (conflict 28); no unverified delivery path (R-a, conflict 31); bounded legacy append (conflict 29); start-up fatality only when the pipeline is requested (conflict 30, 5.4); StaticPool-safe concurrency tests (M17); explicit insert-then-update order (4.12); verbatim (non-NFKC) claim text and sentence-aligned binding (conflict 32); lexical-only shadow retrieval (conflict 33); a faithful legacy retrieval record (M20); `owner_decisions` extension (5.1); work order for prompt hashes (17); non-vacuous license tests (test 34); header-subset equality (test 23); route-flag tests by monkeypatch (test 26); a `qcai.tutor` logger (M23); off-DB record hashes in logs (11.4); privacy disclosure and retention (15, 16); `entry_schema` dispatch in verify (4.12); trigger `TG_OP` checks (8.2); Alembic CLI syntax (8.3); a pg8000 run (14, 17); and several cuts (18.1).

---

## 1. Conflicts between the plan and the fixed decisions, with resolutions

Every resolution is a refinement. None reverses a fixed decision except where plan text gives the reason.

**1. Lock stamps vs AC-3-2.**
- Plan 3.5: "stamped with corpus_version, generator, prompt and configuration versions". E2 adds "evidential and pedagogical prompt hashes". But the lock precedes rendering, and three plans must give the same `claim_set_hash` (AC-3-2).
- **Resolution:** `pedagogical_prompt_hash` is the sha256 of the whole `template-renderer-v1` registry, all plans included; it is plan-independent and known at lock time. The plan used is recorded per response as `presentation.plan_id`. `claim_set_hash` covers the lock, stamps included; no stamp is plan-specific, learner-specific or commit-specific.

**2. AC-3-6 "Given two_pass_tutor on" vs E1 "on is refused".**
- **Resolution:** independent locks (R-c): settings refusal, a code downgrade, and the pipeline's refusal of `delivered`.
- Basis, 13.6 (L2373): "No flag, kill switch, setting or governance override MAY disable V1 or deliver text whose verification has not completed". Phase 4 flips `TWO_PASS_DELIVERY_IMPLEMENTED` with its V1 module.

**3. Plan G "flag two_pass_tutor dual-writes one release".**
- **Resolution:** every tutor delivery is dual-written: `TutorTurn` (mutable, user-keyed, the learner link) plus a ledger record, whatever `TWO_PASS_TUTOR` is set to, behind the kill switch `TUTOR_LEDGER_ENABLED`. Removing the provenance columns of `TutorTurn` is the later contract step (DI-41). The flag controls only the shadow run.

**4. New routes under the freeze (plan 7.3).**
- `POST /tutor/turns`: 404 outside development while `TWO_PASS_TUTOR != "on"` (always before Phase 4). In development it delivers the legacy answer and runs the shadow. A body that fails validation gets 422 before the flag is read (FastAPI validates first); no side effect occurs either way.
- `GET /ledger/responses/{id}`: behind `LEDGER_ROUTE_ENABLED` (`None` = on in development, off elsewhere).
- `GET /evidence/spans/{id}`: behind the Phase 2 `SPAN_RESOLVER_ROUTE_ENABLED`.
- All three are always registered, so the authorization matrix stays static (Phase 2 precedent).

**5. "(owner or reviewer)" (7.3) with no reviewer role in code (M7).**
- **Resolution:** `LEDGER_READER_ROLES = ("reviewer",)` in `app/core/authorization.py`: the plan's own reader, nothing wider (PD-12). Any other role, admin included, reads only its own turns. Each reviewer read records `ledger.reviewer_read` per 7.6 (L937): "reviewer access is logged". Provisioning reviewers is Phase 6 (DI-38).

**6. "daily digest exported off-DB" (7.5, L915).**
- A scheduled export is a cloud write and is deferred (DI-33).
- **Resolution:** every append logs its `seq` and `record_hash` (no learner data) to the platform log, as the security log mirrors `seq` and `hash`: the platform log is a continuous off-DB copy of the chain. The in-image worker `python -m app.workers.response_ledger` verifies the chain and logs the head. `verify_ledger.py --expect-head SEQ:HASH` checks the chain against any logged head.

**7. ClaimLedgerEntry `text` (7.4) vs "no learner text" (E3).** Resolved as R-e.

**8. Plan 3.1 / 7.4 "replaces the heuristic resolver [E-44]" vs E2 "the legacy path keeps working".**
- `thread-resolver-v1` replaces the word-count heuristic on the two-pass path. `TutorOrchestrator._resolve_query` stays on the legacy path (changing it would change what learners receive). The heuristic is removed when the two-pass path delivers (Phase 4, DI-41).

**9. Plan 13.5 (L2360): "every ledger row stamps code SHA, alembic revision, corpus manifest hash, prompt hashes for both L5 passes (F-1), pinned model ids (generator, V1.3 checker, V2 verifiers), MCP contract version and config hash".**
- **Resolution:** `LedgerEntry.versions` holds `code_sha` (`GIT_SHA`), `schema_revision_expected` (the code constant `ledger.SCHEMA_REVISION`, tested against the Alembic head; it names the revision the code expects, not a value read from `alembic_version`, which a `create_all` database may lack, M13), `manifest_sha256`, `config_package_version`, `config_package_sha256`, `span_scheme`, `policy_version`, the resolver, generator and renderer ids, and `budgets` (the budgets in force and any override, R-46). `provenance` holds both prompt hashes and `generator_model_id`. `v1_3_checker_model_id`, `panel_weights_version`, `routing_table_version` and `tool_contract_version` are explicit nulls. V2 verifier ids are Phase 5 additive fields (plan Phase 4 G: "Additive ledger fields").

**10. Plan 3.6 "sole learner-tool user [E-76]".**
- No learner tools exist before Phase 8. **Resolution:** the renderer is the only component whose signature accepts a `PresentationPlan`; in Phase 3 it comes from request hints only (`/tutor/turns presentation_plan`, otherwise the package default). AC-3-1 scans that no `tutor_pipeline` module imports a learner module.

**11. Plan L (L1274) "Stop if bound-claim ratio falls below Phase 2".**
- Phase 2 defined no such SLI. **Resolution:** the baseline is measured at 1.0 (M1) and pinned in the package (`tutor_pipeline.stop.phase2_bound_claim_ratio`). The replay report gives the two-pass ratio beside the baseline. In operation the ratio is the log-based SLI over each run's `tutor.two_pass.shadow` ratio terms and, per process, `TwoPassMetrics.snapshot`, not on public `/ready`, which carries the baseline only (11.2). A null ratio (no claims proposed) is never a stop. `scripts/replay_tutor_plans.py` exits 3 when a non-null two-pass ratio is below the baseline.

**12. Plan H "Public-corpus spans only".**
- Production shadow would process real learner questions. **Resolution:** shadow is off outside development; production enablement is deferred (DI-32). The replay and every test use public fixtures and public-plane spans only.

**13. "/evidence/spans/{span_id} (public license_class only)" with no `license_class` in the code.**
- **Resolution:** `license_class` is derived, never labelled: `CorpusRegistry.license_class` gives `"public"` only when the span record's own plane is public and the manifest does not put its item or file on another plane; a span whose class is not public is never emitted (left out of the bundle and the legacy record, counted; the span routes answer 404). The field is on `SpanResolution` and `EvidenceSpan`. The license gate is tested with a private-plane fixture (test 34) and with forced non-public records (`test_c1_*`), not by the type.

**14. EvidenceBundle `conflicts[]` (7.4).** V1.7 is Phase 4. **Resolution:** an always-empty tuple, refused if non-empty in Phase 3.

**15. 7.2 "EvidenceBundle --weak--> ABSTAIN (V1.5)".** V1.5 is Phase 4. **Resolution:** sufficiency abstains exactly when the active Phase 2 gate returns no result; `near_miss` (the gate's own `near_floor` flag on the top-scored result) proceeds and is recorded (X4 queue is Phase 6). This matches V1.5's "within margin X4 mark".

**16. 3.3 "structured envelope" and R-11.** **Resolution:** the generator receives a typed, frozen `EvidentialEnvelope` (`extra="forbid"`), span text only in typed fields and never in instructions; it returns a `ClaimPlan` validated with `extra="forbid"`. A malformed plan abstains (`claim_plan_invalid`).

**17. E3 "chain-head row ... SELECT ... FOR UPDATE" vs the security log's `pg_advisory_xact_lock`.**
- **Resolution:** keep E3. The head row also detects tail truncation, and a forward-only trigger guards it. The append issues Core statements in a fixed order (head insert-if-missing, head `SELECT ... FOR UPDATE`, record INSERT, head UPDATE) so the ORM unit of work never reorders the head UPDATE before the record INSERT. On SQLite the head INSERT opens the write transaction (pysqlite emits `BEGIN` before the first DML) and serialises writers.

**18. E3 "record_hash = sha256(prev_hash || canonical payload)".**
- **Resolution:** `record_hash = sha256(canonical_json({chain, seq, created_at, prev_hash, entry_sha256}))`, `entry_sha256` = sha256 of the canonical entry. seq and time are covered; the idempotency check compares `entry_sha256` (time-free).

**19. 3.7 "regeneration (at most two)" with a deterministic renderer.** **Resolution:** a generic loop `render(..., attempt=n)` for n = 1..1+`max_regenerations`, `max_regenerations = 2` from the package (the loader refuses values above 2). The template renderer ignores `attempt`; regeneration matters for test renderers and the Phase 5 model renderer.

**20. AC-3-4 "any delivered test response".** Resolved as R-b.

**21. The calibration record pins `config_package_version` "1.0.0" (M10).** **Resolution:** v2's `abstention` block gains `"calibrated_with_package_version": "1.0.0"`; `calibrate_abstention.compute()` writes that value when present, otherwise `package.package_version`. The committed Phase 2 record is not rewritten.

**22. Plan G "Reversible migration" vs append-only evidence (R-22).** **Resolution:** the Alembic downgrade refuses while `response_ledger` holds rows, unless run as `alembic -x allow_ledger_drop=true downgrade 20261119_phase2_corpus_spans` (an absolute target after `alembic current`; never `-1`) after `python -m app.workers.response_ledger --export <path outside the application tree>`, and `python -m app.workers.response_ledger --restore <that path>` re-inserts the record once the revision is applied again. A digest rollback needs no downgrade.

**23. 3.2 "Retrieval request = resolved text, lesson scope, corpus_version".** The client's `top_k` is a request field. **Resolution:** `RetrievalRequest` has exactly those three fields; depth is `tutor_pipeline.retrieval.top_k` (4) from the package.

**24. E5 "evidence panel" vs E9 "evidence-panel production rollout deferred".** **Resolution:** the API adds `evidence` only when `EVIDENCE_PANEL_ENABLED` (`None` = on in development, off elsewhere); the frontend renders the panel only when `evidence` is present.

**25. Task 1.11 (L1095): "a "lexically screened" label MAY accompany only that contained output".** **Resolution:** the panel's `lexically_screened` label appears only when `decision == "answer"` on the legacy contained answer; never on two-pass output.

**26. AC-3-5 "references only thread-A turns".** `TutorTurn` rows do not link to their message. **Resolution:** `source_turn_ids` are the user `TutorMessage` ids (R-d). No column is added to `tutor_turns`.

**27. E4 "guests get 403/404 consistently with the authorization matrix".** `GET /ledger/responses` is `PRINCIPAL` + `OWNER`; anonymous callers get 401 (matrix rule); a guest who is not the owner gets the same 404 as a missing id; a guest owner reads their own non-shadow record when the route is enabled; shadow ids are 404 for every non-reviewer. `scripts/authorization_matrix.py` needs no code change; the doc is regenerated.

**28. "Byte-identical" production responses vs a new response field.**
- Adding `evidence: EvidencePanel | None = None` to `AssistantChatResponse` would put `"evidence": null` into every production response.
- **Resolution:** `AssistantChatResponse.evidence` is `Field(default=None, exclude_if=lambda value: value is None)`, which omits the key when it is None; every other key serialises as today. Test 38 pins the production key set and body. Because the exclusion is field-level, not a model serializer, both chat response schemas keep every field in `/openapi.json` (`test_the_chat_response_schemas_keep_every_field_in_openapi`).

**29. E1 "never ... delays the learner's legacy response beyond a bounded budget" vs a synchronous legacy append.**
- **Resolution:** the legacy append runs after the turn commits, before the response is returned, under a total deadline: the configuration package's `tutor_pipeline.budgets.ledger_append_ms` (1500 ms; `TUTOR_LEDGER_APPEND_BUDGET_MS` overrides it and is unset by default). It makes at most `ledger_append_attempts` (3) attempts. Each PostgreSQL attempt first sets `lock_timeout`, `statement_timeout` and `idle_in_transaction_session_timeout` to the remaining budget. An `IntegrityError`, a deadlock (SQLSTATE 40P01) or a serialization failure (40001) is retried within the budget; any other error (lock or statement timeout, busy, trigger refusal) fails open at once. The wait for a connection is far longer than the budget (the pool's 30 s checkout timeout, and a new Cloud SQL connection's 30 s bound, `app.core.db.CONNECT_TIMEOUT_S`), so the append runs on a small worker pool (`ledger_append_workers` 4 threads, at most `ledger_append_max_in_flight` 16 appends running or queued; past that an append is refused at once and counted), and the request waits for it at most the budget plus the package's `ledger_wait_grace_ms` (250 ms). An append still running then finishes in the background and is counted when it ends (`tutor.ledger.append_deferred`, then the attempt's terminal line). That is the worst-case added latency on every dialect. SQLite (development and tests) keeps the driver's busy timeout.

**30. Start-up checks for a feature that is off.**
- **Resolution:** at start-up `check_tutor_pipeline_package(package, structural=False)` verifies schema file hashes and prompt hashes (deterministic from code and package). A governed build stops on a problem only when `TWO_PASS_TUTOR != "off"`; otherwise it logs `tutor.two_pass.unavailable`, reports `tutor_pipeline.available: false` in `/ready`, and keeps `effective_mode` off. The pydantic structural comparison (`structural=True`) runs in tests and `config_package.py --check` (CI) only, because the image's pydantic version is not pinned (M21).

**31. Plan 7.2 "[L7 ledger append] --> DELIVER" vs invariant 6 and 13.6.**
- **Resolution:** Phase 3 has no delivered two-pass path (R-a). The ledger-before-delivery order is Phase 4's, behind V1. The pipeline's refusal of `delivered` is tested (test 12).

**32. D-19 "verbatim" vs comparison normalisation; and the binding rule.**
- **Resolution:** claim text stored, locked, ledgered and rendered is the whitespace-normalised verbatim sentence of the span (`whitespace()`), never the generator's text: bind locks the span's own sentence that the normalised claim matched, and the subset check requires the rendered text to equal the locked text, whitespace runs aside. NFKC (`normalise()`) is used only to find the matching sentence (M22). The Phase 3 binding rule `resolver-bundle-sentence-v2` requires the normalised claim to equal a whole sentence of every cited span. A whole sentence of a span is a sentence of the span's section text under the package's sentence rule (`sentences-v2`) that lies wholly inside the span: a span is a splitter chunk (700 characters, 120 overlap) that can start and end inside a document sentence. So no generator can bind a truncated sentence that drops a qualification or negation (R-16 class), whether the generator cut it or the span's edge did (`partial_sentence`). Plan M's residual "misleading wording within locked claims" for sentence splits at abbreviations is addressed by `sentences-v2`, which keeps abbreviations, initials and numbers inside their sentence: 1 of 2177 dev sentences still ends at an initial (a bibliography line).

**33. Provider egress from the shadow (D-12, D-23, R-10).**
- `RetrievalEngine._search` could call the OpenAI embeddings backend if semantic retrieval were ever aligned in the API process; the shadow would send the resolved text (possibly two learner turns) to a provider.
- **Resolution:** `RetrievalEngine.evidence()` is lexical only (`store.evaluate`), whatever `SEMANTIC_RETRIEVAL_ENABLED` says; `retrieval_mode` is always `"lexical"` in Phase 3 bundles.

**34. Task 3.3 "atomic claims" vs D-19 verbatim sentences.**
- Plan 3.3: "Claim plan: atomic claims bound to span ids from a structured envelope; unbound dropped [Risk R-11]." The plan defines no atomicity rule.
- Under D-19 extractive mode a claim is quoted, never written. The smallest verbatim unit that cannot drop a qualification or a negation is a whole sentence of the span (conflict 32): binding refuses a sub-sentence cut (`not_verbatim`) and a span-edge fragment of a longer document sentence (`partial_sentence`), so a generator that emitted clause-level claims would bind none of them.
- **Resolution (an engineering reading, not a plan default):** in Phase 3 the claim unit is one verbatim whole sentence of every cited span (`sentences-v2`, at most `max_sentence_chars` 1000, at most `max_claims` 3). A compound sentence is one claim, so Phase 4's V1.3 entailment and Phase 5's V2 votes give it one verdict for what may be several facts. Atomic decomposition needs a generator that writes its own claims (Phase 5, D-12, through the gateway) and per-claim V1.3 entailment (Phase 4); until then the sentence unit stands.
- Recorded in configuration package v2 as `owner_decisions.PLAN-3.3` (`status: provisional`, `ratified: false`), in ADR-001's revision and as DI-47: the Principal Investigator or the Research Lead accepts the reading or sets an atomicity rule (as PLAN-11.3 records the 11.3 deviations, PD-07).

---

## 2. Architecture

```
POST /assistant/chat | POST /tutor/turns (dev)
   └─ TutorOrchestrator.chat  (legacy, unchanged containment, D-19)
        ├─ TeachingAssistantService.chat → contain_answer → learner response  ── delivered (legacy)
        │     (response._retrieval = RetrievalResponse, never serialised)
        └─ response._followups = TurnFollowups(legacy=LegacyDelivery?, shadow=ShadowJob?)
   route: db.commit()
        ├─ record_legacy_delivery(legacy)   after the commit, own session, waits ≤ append budget + grace, fail-open → response_ledger
        └─ BackgroundTasks: orchestrator.run_shadow(job)   after the response body is sent; fail-open, counted
               resolve_thread (learner's own user turns)  → ResolvedQuestion
               build_request (text, lesson scope, corpus_version) → RetrievalRequest
               retrieve (lexical, active gate; RetrievalEngine.evidence) → EvidenceBundle
               build_envelope → EvidentialEnvelope → generator.propose → ClaimPlan   [evidential pass]
               bind (SpanResolver; bundle; sentence-verbatim; D-19 quotable) → bound claims
               lock → LockedClaimSet (claim_set_hash)
               render (PresentationPlan; ≤ 1+2 attempts) → claim_gate.check_subset    [pedagogical pass]
               ledger append (delivery=shadow, id=shadow-…, shadowed_response_id=turn id)
```

**Where each AC is enforced**

| AC | Mechanism | Primary test |
|---|---|---|
| AC-3-1 | `RetrievalRequest` and `EvidentialEnvelope` allowlisted, frozen, `extra="forbid"`; signature and import scans; a spy capture of evidential inputs under three learner contexts | `test_ac_3_1_*` |
| AC-3-2 | Lock before render; plan-independent `claim_set_hash` | `test_ac_3_2_*`, replay `--check` |
| AC-3-3 | Typed segments; exact normalised mapping; up to 2 regenerations, then abstain | `test_ac_3_3_*` (property test) |
| AC-3-4 | Hash chain, head row, triggers, `verify_response_ledger` | `test_ac_3_4_*` |
| AC-3-5 | `resolve_thread` reads only that thread's user messages | `test_ac_3_5_*` |
| AC-3-6 | Settings refuse `on`; code downgrade; pipeline refuses `delivered`; shadow as a background task; learner-invisible records | `test_ac_3_6_*`, test 12 |

---

## 3. Data shapes

All new contracts live in `apps/api/app/services/tutor_pipeline/contracts.py`, and the API additions in `app/schemas.py`. The listings below are the code's class bodies, without docstrings and validator methods (`test_k3_spec_section_3_lists_the_code_s_fields` compares every field). Each contract subclasses:

```python
class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

Collections are tuples. The patterns are:
```python
SPAN_ID = r"^span-[0-9a-f]{64}$"
HEX64 = r"^[0-9a-f]{64}$"
CLAIM_ID = r"^claim-[0-9a-f]{32}$"
# turn- a tutor turn (TutorTurn.id); shadow- a two-pass shadow run; qa- a /qa/ask delivery (a random id that names no
# learner; the record matches the asker's Q&A row by its answer hash while that row exists, spec 18.6 D10).
RESPONSE_ID = r"^(turn|shadow|qa)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
```

### 3.1 Evidential channel

```python
class ResolverRef(Contract):
    model_id: str
    prompt_hash: str = Field(pattern=HEX64)

class ResolvedQuestion(Contract):
    text: str = Field(min_length=1, max_length=4001)
    resolver: ResolverRef
    source_turn_ids: tuple[str, ...] = Field(min_length=1, max_length=2)
    contains_learner_state: Literal[False] = False

class RetrievalRequest(Contract):
    text: str = Field(min_length=1, max_length=4001)
    lesson_slug: str | None = Field(default=None, max_length=255)
    corpus_version: str = Field(min_length=1, max_length=64)

class EvidenceSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    item_id: str
    item_version: str
    kind: Literal["document", "authored"]
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    content_hash: str = Field(pattern=HEX64)
    # None only on legacy records without a retrieval side channel (the delivered quotations).
    score: float | None
    near_floor: bool
    license_class: Literal["public"]
    # D-19: a public-plane, bound, indexable document span (contained_answers.span_is_quotable).
    quotable: bool

class Sufficiency(Contract):
    score: float | None
    gate: Literal["p1-floor", "bm25f-v1"]
    threshold_version: str
    floor: float
    margin: float
    decision: Literal["answer", "abstain", "near_miss"]
    reason: str

class EvidenceBundle(Contract):
    bundle_schema: Literal["evidence-bundle-v1"] = "evidence-bundle-v1"
    corpus_version: str
    index_version: str
    retrieval_mode: Literal["lexical"]
    spans: tuple[EvidenceSpan, ...] = Field(max_length=12)
    sufficiency: Sufficiency
    conflicts: tuple[str, ...] = ()
    # validator: _no_conflicts_before_phase_4 (see the rules below)

class EnvelopeSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    # The span's own characters from its first whole document sentence to its last (bind.whole_sentence_text): a
    # leading or trailing span-edge fragment of a longer sentence is never sent (spec 18.10 H1).
    text: str = Field(min_length=1)

class EvidentialInstructions(Contract):
    rule_id: str
    prompt_hash: str = Field(pattern=HEX64)
    max_claims: int = Field(ge=1, le=10)
    max_claims_per_span: int = Field(ge=1, le=10)
    min_sentence_words: int = Field(ge=1, le=50)

class EvidentialEnvelope(Contract):
    envelope_schema: Literal["evidential-envelope-v1"] = "evidential-envelope-v1"
    question: str = Field(min_length=1, max_length=4001)
    corpus_version: str
    evidence: tuple[EnvelopeSpan, ...] = Field(min_length=1, max_length=12)
    instructions: EvidentialInstructions

class GeneratorRef(Contract):
    generator_id: str
    model_id: str
    kind: Literal["extractive", "generative"]
    prompt_hash: str = Field(pattern=HEX64)

class ProposedClaim(Contract):
    text: str = Field(min_length=1, max_length=2000)
    span_ids: tuple[str, ...] = Field(default=(), max_length=8)

class ClaimPlan(Contract):
    plan_schema: Literal["claim-plan-v1"] = "claim-plan-v1"
    generator: GeneratorRef
    claims: tuple[ProposedClaim, ...] = Field(max_length=20)

class LockedClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    # Verbatim, whitespace-normalised corpus text (tutor_pipeline.text.whitespace); never NFKC-folded.
    text: str
    span_ids: tuple[str, ...] = Field(min_length=1)
    source_order: tuple[str, int]

class ConfigStamp(Contract):
    version: str
    sha256: str = Field(pattern=HEX64)

class LockedClaimSet(Contract):
    lock_schema: Literal["locked-claim-set-v1"] = "locked-claim-set-v1"
    claims: tuple[LockedClaim, ...]
    span_ids: tuple[str, ...]
    corpus_version: str
    index_version: str
    generator: GeneratorRef | None
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str
    resolver: ResolverRef
    config_package: ConfigStamp
    claim_set_hash: str = Field(pattern=HEX64)
    # validator: _consistent (see the rules below)
```

`lock_hash(s) = sha256(ledger_canonical(s.model_dump(mode="json", exclude={"claim_set_hash"})))`. The `LockedClaimSet` validator requires `span_ids` to be the sorted union of the claims' span ids, unique claim ids, each claim's span ids sorted and unique, and `claim_set_hash == lock_hash(self)`. A copy made with `model_copy(update=...)` skips validation, so the renderer, the subset check and the ledger call `verify_locked(locked)`, which recomputes the same checks and raises `LockedClaimSetTampered` on a mismatch. The lock holds no learner, request or commit value. `EvidenceBundle` refuses a non-empty `conflicts` (V1.7 is Phase 4).

### 3.2 Pedagogical channel

```python
class PresentationPlan(Contract):
    plan_id: Literal["concise", "stepwise", "socratic"]
    source: Literal["request", "default"]

class Segment(Contract):
    kind: Literal["connective", "question", "claim", "citation"]
    line: int = Field(ge=0)
    text: str
    template_id: str | None = None
    params: tuple[int, ...] = ()
    claim_id: str | None = None
    span_id: str | None = None

class RenderedResponse(Contract):
    renderer_id: str
    plan_id: str
    attempt: int = Field(ge=1, le=3)
    segments: tuple[Segment, ...]
    citations: tuple[str, ...]
    text: str
```

### 3.3 Ledger entry (`ledger-entry-v1`)

```python
class Provenance(Contract):
    generator_model_id: str
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str | None
    v1_3_checker_model_id: None = None
    corpus_version: str
    threshold_set_version: str
    panel_weights_version: None = None
    routing_table_version: None = None
    tool_contract_version: None = None

class ClaimLedgerEntry(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    response_id: str = Field(pattern=RESPONSE_ID)
    text: str
    span_ids: tuple[str, ...] = Field(min_length=1)
    entailment_score: None = None
    locked: Literal[True] = True
    provenance: Provenance

class ResolvedQuestionRef(Contract):
    resolver: ResolverRef
    source_turn_ids: tuple[str, ...]
    contains_learner_state: Literal[False] = False

class RetrievalRecord(Contract):
    corpus_version: str
    index_version: str
    gate: str
    threshold_version: str
    floor: float
    margin: float
    mode: str
    evidence_scope: Literal["retrieved", "delivered_citations"]
    sufficiency: Sufficiency | None
    evidence: tuple[EvidenceSpan, ...]

class PresentationRecord(Contract):
    plan_id: str
    source: str
    renderer_id: str
    attempts: int = Field(ge=1, le=3)
    subset_check: Literal["passed", "failed"]
    # What the passing rendering showed, in render order: the locked claims it rendered and the spans it cited
    # (both empty when no rendering passed). The locked set is LedgerEntry.claims; a renderer may leave a claim out
    # (spec 4.9), so the record never implies that a claim or a citation it did not render was shown.
    rendered_claim_ids: tuple[str, ...] = ()
    rendered_span_ids: tuple[str, ...] = ()

BUDGET_OVERRIDES = ("shadow_ms", "ledger_append_ms")

class BudgetStamp(Contract):
    shadow_ms: int | None = Field(ge=1)
    ledger_append_ms: int = Field(ge=1)
    overridden: tuple[Literal["shadow_ms", "ledger_append_ms"], ...] = ()

class VersionStamps(Contract):
    pipeline_version: str
    code_sha: str
    schema_revision_expected: str
    config_package_version: str
    config_package_sha256: str
    manifest_sha256: str | None
    span_scheme: str
    policy_version: str
    resolver_id: str | None
    generator_id: str | None
    renderer_id: str | None
    budgets: BudgetStamp

class PipelineCounts(Contract):
    proposed_claims: int = Field(ge=0)
    # The locked claims (len(LedgerEntry.claims) for a two-pass entry).
    bound_claims: int = Field(ge=0)
    dropped: dict[str, int]
    render_attempts: int = Field(ge=0)
    # validator: _reconciles (see the rules below)

class LedgerEntry(Contract):
    entry_schema: Literal["ledger-entry-v1"] = "ledger-entry-v1"
    response_id: str = Field(pattern=RESPONSE_ID)
    delivery: Literal["shadow", "delivered", "legacy"]
    shadowed_response_id: str | None
    pipeline: Literal["two-pass-v1", "legacy-contained-v1"]
    decision: Literal["answer", "abstain"]
    abstention_reason: str | None
    resolved_question: ResolvedQuestionRef | None
    retrieval: RetrievalRecord
    claim_set_hash: str | None
    claims: tuple[ClaimLedgerEntry, ...]
    span_ids: tuple[str, ...]
    presentation: PresentationRecord | None
    rendered_text_sha256: str | None
    provenance: Provenance
    versions: VersionStamps
    # No V1/V2/V3 verdict exists before Phase 4: such a record reads as "no-verdict".
    verification: None = None
    counts: PipelineCounts
    # validator: _rules (see the rules below)
```

`PipelineCounts` validator: every drop reason is one of `DROP_REASONS` and listed only with a positive count, and `proposed_claims == bound_claims + sum(dropped)`.

`LedgerEntry` model validator:
- `delivery == "shadow"`: `response_id` starts with `shadow-` and `shadowed_response_id` with `turn-`;
- `legacy`: a `turn-` or `qa-` id and no `shadowed_response_id`; `delivered`: a `turn-` id and no `shadowed_response_id`;
- `delivered` is refused while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (no Phase 3 code builds one);
- `decision == "abstain"` iff `abstention_reason` is set, and the reason is in `ABSTENTION_REASONS` or is `no_approved_span` (the legacy reason);
- `decision == "answer"` requires claims and `rendered_text_sha256`;
- `span_ids == sorted(union(claim.span_ids))`;
- every `claim.response_id == response_id` and `claim.provenance == provenance`;
- `counts.bound_claims == len(claims)`;
- with a `presentation`: `rendered_claim_ids` names recorded claims, each once; `rendered_span_ids` names recorded spans; an answer's rendering passed and shows at least one claim and one citation.

```python
# Two reasons for an empty evidential envelope (spec 18.11 I1; evidential.no_envelope_reason):
#   no_quotable_evidence  the bundle holds no quotable span: nothing approved under D-31, or the license gate excluded
#                         every result (retrieve.py)
#   no_whole_sentence     it holds quotable spans, but none holds a whole document sentence (spec 18.10 H1), so there
#                         is nothing to quote whole
NO_QUOTABLE_EVIDENCE = "no_quotable_evidence"
NO_WHOLE_SENTENCE = "no_whole_sentence"
# Every render attempt raised (in the renderer, or in the subset check on its output) instead of producing a
# rendering that the subset check could refuse (spec 18.12 J3). Each such attempt logs tutor.two_pass.render_failed;
# subset_check_failed stays for a run in which at least one rendering was checked and every checked one failed.
RENDER_FAILED = "render_failed"
ABSTENTION_REASONS = (
    "no_query_terms",
    "no_match",
    "insufficient_coverage",
    "below_floor",
    "corpus_version_mismatch",
    NO_QUOTABLE_EVIDENCE,
    NO_WHOLE_SENTENCE,
    "claim_plan_invalid",
    "no_claims",
    "no_bound_claims",
    "subset_check_failed",
    RENDER_FAILED,
    "budget_exceeded",
)
# The legacy contained path's own abstention reason (contained_answers.contain_answer). A legacy ledger record keeps
# it only for a gate that matched passages none of which could be quoted (not approved under D-31, or not verified);
# when the gate itself returned nothing, the record carries the gate's reason.
LEGACY_ABSTENTION_REASON = "no_approved_span"
# The Phase 2 retrieval gate's own abstention reasons (lexical_index.Reason without "evidence").
GATE_ABSTENTION_REASONS = ("no_query_terms", "no_match", "insufficient_coverage", "below_floor")

# Why a proposed claim is not a locked claim of its own (PipelineCounts.dropped). Every proposed claim is either
# locked or counted under exactly one reason, so proposed_claims == bound_claims + sum(dropped).
# partial_sentence (spec 18.10 H1): a piece of a cited span's own text that the span cuts out of a longer document
# sentence (it starts or ends at the span's edge), so it is not a whole sentence and never binds.
PARTIAL_SENTENCE = "partial_sentence"
BINDING_FAILURES = ("unbound", "outside_bundle", "unresolvable", "not_quotable", PARTIAL_SENTENCE, "not_verbatim")
# Not binding failures, so the plan L bound-claim ratio treats them apart (bound_claim_ratio_terms):
#   merged           it bound, onto the spans of an earlier claim with the same sentence (bind.py)
#   duplicate        it bound too: its sentence was already bound on every span it cites, so it adds nothing. It
#                    passed every binding check, exactly as a merged claim did, so the ratio counts it as bound, and
#                    two claim plans that lock one claim set give one ratio whatever the order of their claims
#   budget_exceeded  bind never ran: the shadow budget ran out after the generator returned (pipeline.py)
MERGED = "merged"
DUPLICATE = "duplicate"
BUDGET_SKIPPED = "budget_exceeded"
# The legacy contained path: a citation the Phase 2 pipeline produced but could not verify (a binding failure).
LEGACY_UNRESOLVED = "unresolved_citation"
# The legacy contained path: a delivered quotation whose span's derived license class is not public. Its claim is
# kept out of the ledger (no non-public text is ever recorded) and counted; any such count is an upstream breach.
LEGACY_NOT_PUBLIC = "not_public"
DROP_REASONS = (*BINDING_FAILURES, MERGED, DUPLICATE, BUDGET_SKIPPED, LEGACY_UNRESOLVED, LEGACY_NOT_PUBLIC)

LEARNER_STATE_FIELDS = ("mastery", "mastery_band", "band", "preference", "preferences", "user_id", "learner_id",
                        "guest_id", "account_id", "email", "history", "page_path", "pedagogical_context",
                        "learner_state", "profile", "quiz_attempts", "notes", "cursor", "target_role", "focus_area",
                        "self_ratings", "preferred_pace", "presentation", "presentation_plan", "plan_id",
                        "thread_id")
SCHEMA_MODELS = {"ResolvedQuestion": ResolvedQuestion, "RetrievalRequest": RetrievalRequest, "EvidenceBundle": EvidenceBundle,
                 "EvidentialEnvelope": EvidentialEnvelope, "ClaimPlan": ClaimPlan, "LockedClaimSet": LockedClaimSet,
                 "PresentationPlan": PresentationPlan, "LedgerEntry": LedgerEntry}
# verify_response_ledger dispatches on a row's entry_schema; Phase 4 adds ledger-entry-v2.
ENTRY_SCHEMAS: dict[str, type[LedgerEntry]] = {"ledger-entry-v1": LedgerEntry}
```

(`ledger_write_failed` is not an abstention reason in Phase 3: there is no delivered two-pass path; a failed shadow append is a counted failure, a failed legacy append a counted coverage gap.)

### 3.4 API additions (`app/schemas.py`)

```python
class EvidenceSpanLink(BaseModel):
    span_id: str
    label: str
    # True when GET /evidence/spans/{span_id} is enabled (SPAN_RESOLVER_ROUTE_ENABLED); otherwise a plain label.
    resolvable: bool

class EvidencePanel(BaseModel):
    panel_schema: Literal["evidence-panel-v1"] = "evidence-panel-v1"
    decision: Literal["answer", "abstain"]
    labels: list[Literal["lexically_screened"]] = Field(default_factory=list)
    degraded: list[Literal["extractive_only", "retrieval_fallback", "citations_provisional"]] = Field(default_factory=list)
    spans: list[EvidenceSpanLink] = Field(default_factory=list)
    verdict: Literal["no-verdict"] = "no-verdict"

class AssistantChatResponse(BaseModel):  # Phase 3 additions only
    # Phase 3 (task 3.8): present only when EVIDENCE_PANEL_ENABLED (development by default). When absent the key is
    # omitted, so production bodies keep today's keys and values (spec conflict 28). A field-level exclude_if, not a
    # model serializer, so the response schema in /openapi.json keeps every field.
    evidence: EvidencePanel | None = Field(default=None, exclude_if=lambda value: value is None)
    # Never serialised: the turn's ledger and shadow follow-ups, and the retrieval behind a contained answer.
    _followups: Any = PrivateAttr(default=None)
    _retrieval: Any = PrivateAttr(default=None)

class QAResponse(BaseModel):  # Phase 3 additions only
    # Phase 3 (task 3.8, E-46 "Citation cards omit provenance", the Q&A panel; spec 18.8 F3): the evidence panel,
    # present only when EVIDENCE_PANEL_ENABLED (development by default). When absent the key is omitted, so production
    # bodies keep today's keys and values, as on the tutor chat (spec conflict 28).
    evidence: "EvidencePanel | None" = Field(default=None, exclude_if=lambda value: value is None)
    # Never serialised: the delivery's ledger record (plan task 3.8), appended by the route after the commit.
    _ledger: Any = PrivateAttr(default=None)

class TutorTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=8, max_length=64)
    lesson_slug: str | None = Field(default=None, max_length=255)
    # A presentation hint for the two-pass renderer only; it never reaches retrieval or the evidential pass.
    presentation_plan: Literal["concise", "stepwise", "socratic"] | None = None
    # validator: validate_message

class TutorTurnResponse(AssistantChatResponse):
    # Phase 3 delivers the legacy contained answer only; Phase 4 adds "delivered" behind V1 (AC-3-6).
    delivery: Literal["legacy"] = "legacy"

class LedgerClaimRead(BaseModel):
    claim_id: str
    text: str
    span_ids: list[str]

class LedgerRecordRead(BaseModel):
    response_id: str
    delivery: str
    decision: str
    abstention_reason: str | None = None
    created_at: datetime
    claim_set_hash: str | None = None
    span_ids: list[str] = Field(default_factory=list)
    claims: list[LedgerClaimRead] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    versions: dict[str, Any] = Field(default_factory=dict)
    resolved_question: dict[str, Any] | None = None
    # Reviewers only (None for owners, so a learner never learns chain position or traffic volume).
    seq: int | None = None
    prev_hash: str | None = None
    record_hash: str | None = None
    entry_sha256: str | None = None
    shadowed_response_id: str | None = None

class LedgerResponseRead(BaseModel):
    response_id: str
    # Plan Phase 3 G: "legacy turns marked no-verdict"; no V1-V3 verdict exists before Phase 4.
    verdict: Literal["no-verdict"] = "no-verdict"
    recorded: bool
    # With recorded false: true for a turn an image that keeps no ledger created (before Phase 3, or during a rollback
    # window), false for a turn a Phase 3 image created (TutorTurn.ledger_record_expected). unrecorded_reason says which:
    # earlier_image (legacy_turn true), ledger_disabled (made while TUTOR_LEDGER_ENABLED was off) or missing (it
    # expected a record and has none: a lost record, a plan L stop). Null when recorded.
    legacy_turn: bool
    unrecorded_reason: Literal["earlier_image", "ledger_disabled", "missing"] | None = None
    record: LedgerRecordRead | None = None
```

`AssistantChatResponse.evidence` and `QAResponse.evidence` are omitted from serialisation when None (`exclude_if`, conflict 28), so production bodies keep today's keys; the private attributes are never serialised. `SpanResolution` gains `license_class: Literal["public"] = "public"` (additive; the route is off outside development).

---

## 4. Algorithms

### 4.1 Text helpers (`tutor_pipeline/text.py`)

```python
def normalise(text: str) -> str:            # comparisons only (bind, subset check)
    return " ".join(unicodedata.normalize("NFKC", text).split())
def whitespace(text: str) -> str:           # the verbatim surface that is stored, locked and rendered
    return " ".join(text.split())
SENTENCE_RULE = "sentences-v2"
def split_sentences(text: str) -> list[str]:  # boundaries after . ! ?, never after an abbreviation, an initial or
    ...                                       # before a lowercase word (text.py docstring)
def sentences(text: str, *, min_words: int, max_chars: int) -> list[str]:   # both from the package
    return [s for s in split_sentences(text) if len(s.split()) >= min_words and len(s) <= max_chars]
def sentence_bounds(text: str) -> tuple[tuple[int, int], ...]:  # the same cuts as (start, end) offsets into
    ...                                                         # text; whitespace(text[a:b]) is the split_sentences piece
def content_terms(text: str, params: RetrievalParams) -> frozenset[str]:
    return frozenset(lexical_index.tokenize(text, params))   # package tokenizer + stopwords-v1
```

### 4.2 Resolver `thread-resolver-v1` (`tutor_pipeline/resolve.py`)

```python
@dataclass(frozen=True)
class LearnerTurn: message_id: str; text: str       # a role=="user" TutorMessage
RESOLVER_ID = "thread-resolver-v1"
RESOLVER_TEMPLATE = "{anchor}\n{current}"
def resolver_prompt_hash(params: TutorPipelineParams, retrieval: RetrievalParams) -> str:
    return canonical_sha256({"id": RESOLVER_ID, "template": RESOLVER_TEMPLATE,
        "min_content_terms": params.min_content_terms, "continuation_cues": list(params.continuation_cues),
        "max_lookback": params.max_lookback, "tokenizer": retrieval.tokenizer_version,
        "stopwords": retrieval.stopwords_version, "inputs": "the learner's own user messages of one thread"})
def resolve_turns(prior: Sequence[LearnerTurn], current: LearnerTurn, *, package: ConfigPackage) -> ResolvedQuestion
def resolve_thread(db: Session, thread_id: str, current_message_id: str, *, package: ConfigPackage) -> ResolvedQuestion
```

**`resolve_turns` rule**
1. `cur = whitespace(current.text)`. The message is a **follow-up** if either holds:
   - `len(content_terms(cur)) < min_content_terms` (2);
   - `cur.lower()` starts with a continuation cue (`"and "`, `"also "`, `"but "`, `"so "`, `"then "`, `"what about "`, `"how about "`).

   Not a word-count rule: an 8-word question with 2 or more content terms is standalone.
2. If it is a follow-up, `anchor` is the most recent of the last `max_lookback` (4) prior turns with at least 2 content terms.
3. If an anchor exists: `text = f"{whitespace(anchor.text)}\n{cur}"`, `source_turn_ids = (anchor.message_id, current.message_id)`. Otherwise `text = cur`, `source_turn_ids = (current.message_id,)`.

**`resolve_thread`**
- Load the current message. It must belong to `thread_id` and have `role == "user"`; otherwise raise `ResolverInputError`.
- Load the prior user messages:
  ```
  WHERE thread_id = :t AND role = 'user' AND id != :cur_id
    AND (created_at < cur.created_at OR (created_at = cur.created_at AND id < cur.id))
  ORDER BY created_at DESC, id DESC
  LIMIT max_lookback
  ```
  then reverse. (`id != :cur_id` guards SQLite's string comparison of whole-second legacy rows against microsecond rows.)
- It never reads assistant messages, client `history`, or any other table.

### 4.3 Retrieve (`tutor_pipeline/retrieve.py`)

```python
def build_request(resolved: ResolvedQuestion, *, lesson_slug: str | None, corpus_version: str) -> RetrievalRequest
def retrieve(engine: RetrievalEngine, request: RetrievalRequest, *, top_k: int, registry: CorpusRegistry) -> EvidenceBundle
```

- If `request.corpus_version != engine.store.corpus_version`, abstain with reason `corpus_version_mismatch` and no spans.
- Call `engine.evidence(request.text, lesson_slug=request.lesson_slug, top_k=top_k)`: lexical only (conflict 33), records no Phase 2 retrieval SLI (7.5).
- `spans` are built from `response.results`, in result order, joined with `store.span_registry.get(span_id)` for kind and offsets (`evidence_span_for`); `quotable = span_is_quotable(record, registry)`. The license gate drops a result whose derived license class is not public (`CorpusRegistry.license_class` is None): it never enters the bundle, and it is counted (`LICENSE_METRICS.excluded("two_pass")`) and logged (`tutor.evidence.non_public_excluded`).
- `floor, margin, threshold_version = store.index.thresholds`.
- **Sufficiency**
  - No results: `abstain`, reason `response.reason`.
  - Results, but the license gate dropped every one: `abstain`, reason `no_quotable_evidence`, at this retrieval step (the bundle has no span, so the envelope step never runs).
  - Otherwise `top` = the first result the license gate kept (lexical results are score-descending, so it is the top-ranked result unless the gate dropped results above it). Decision `near_miss` when `top.near_floor` (the gate's own flag; never re-derived from rounded scores), else `answer`. `score = top.score`. Reason `"evidence"`.
- `conflicts = ()`.

### 4.4 D-19 eligibility (`contained_answers.py`, additive only)

```python
def span_is_quotable(record: SpanRecord, registry: CorpusRegistry) -> bool:
    return (record.item_kind == "document" and record.plane == "public" and bool(record.source_filename)
            and registry.is_indexable(record.source_filename))
```

`contain_answer` is **not modified**. A unit test proves that, for every span in the dev and governed-empty registries, `span_is_quotable(span)` equals `contain_answer([native_citation(span)])` deciding `answer`.

### 4.5 Evidential pass (`tutor_pipeline/evidential.py`)

```python
def build_envelope(request: RetrievalRequest, bundle: EvidenceBundle, *, store: CourseStore, params) -> EvidentialEnvelope | None
class ClaimGenerator(Protocol):        # the provider-generator interface (E2); Phase 5 wires one through the gateway
    ref: GeneratorRef
    def propose(self, envelope: EvidentialEnvelope) -> ClaimPlan: ...
class ExtractiveD19Generator:          # id "extractive-d19-v1", model_id "extractive-d19-v1", kind "extractive"
GENERATORS: dict[str, Callable[[ConfigPackage], ClaimGenerator]] = {"extractive-d19-v1": ExtractiveD19Generator}
def get_generator(package: ConfigPackage) -> ClaimGenerator    # id must be in package generators_allowed and GENERATORS
def no_envelope_reason(bundle: EvidenceBundle, *, store: CourseStore) -> str   # why build_envelope gave None
EXTRACTIVE_RULE = ("D-19 extractive mode: each claim is one verbatim whole sentence (sentences-v2) of an approved, "
                   "public-plane document span in the envelope, whose text holds only the span's whole document "
                   "sentences, that shares at least {min_question_overlap_terms} content terms with the question; at most "
                   "{max_claims_per_span} per span and {max_claims} in all, in evidence order.")
def evidential_prompt_hash(params) -> str:
    return canonical_sha256({"id": "extractive-d19-v1", "rule": EXTRACTIVE_RULE, "sentence_rule": SENTENCE_RULE,  # "sentences-v2"
        "max_claims": params.max_claims, "max_claims_per_span": params.max_claims_per_span,
        "min_sentence_words": params.min_sentence_words, "max_sentence_chars": params.max_sentence_chars,
        "min_question_overlap_terms": params.min_question_overlap_terms})
```

No provider class exists in Phase 3 (D-12 open, hold H6): the Protocol is the interface, and `get_generator` refuses any id outside `WIRED_GENERATORS`.

**`build_envelope`**
- `evidence` holds the bundle spans with `quotable` true, in bundle order, each with its whole-sentence text (`bind.whole_sentence_text`): the span's own characters from the start of its first whole document sentence to the end of its last. A span that holds no whole sentence is left out, so a leading or trailing fragment of a longer document sentence never reaches a generator.
- If no span is left, return `None`. The pipeline abstains with the reason `no_envelope_reason(bundle, store=...)` gives: `no_quotable_evidence` when the bundle holds no quotable span (nothing approved under D-31), and `no_whole_sentence` when it holds quotable spans none of which holds a whole document sentence. A bundle the license gate emptied never reaches this step: it abstained at retrieval, with `no_quotable_evidence` too (4.3). Non-quotable span text never reaches a generator (D-19, D-31).

**`ExtractiveD19Generator.propose`**
- `q = content_terms(envelope.question)`.
- For each envelope span, in order: candidates are the `sentences(span.text)` (rule `sentences-v2`) that share at least `min_question_overlap_terms` content terms with the question (`len(content_terms(sentence) ∩ q) >= min_question_overlap_terms`, 1 in the package); take the first `max_claims_per_span`; stop at `max_claims`.
- Each claim is `ProposedClaim(text=whitespace(sentence), span_ids=(span.span_id,))`.

**Wrapping.** A generator exception, or a `ValidationError` when the result is coerced with `ClaimPlan.model_validate(...)`, abstains with `claim_plan_invalid`. Zero claims abstain with `no_claims`.

### 4.6 Bind (`tutor_pipeline/bind.py`; binding rule `resolver-bundle-sentence-v2`)

```python
@dataclass(frozen=True)
class BindResult: bound: tuple[LockedClaimDraft, ...]; dropped: Counter[str]; proposed: int
def bind(plan: ClaimPlan, bundle: EvidenceBundle, *, resolver: SpanResolver, store: CourseStore, registry: CorpusRegistry, params) -> BindResult
```

For each proposed claim, in order, the claim is **dropped whole** on the first failing check:

| Check | Drop reason |
|---|---|
| `span_ids` is empty | `unbound` |
| a span id is not in `bundle.spans` | `outside_bundle` |
| `resolver.resolve_current(id)` is None, or its `content_hash` differs from the bundle span's | `unresolvable` |
| `not span_is_quotable(store.span_registry.get(id), registry)` | `not_quotable` |
| `normalise(text)` is a `sentences(span.text)` piece of every cited span, but on at least one it is not a whole sentence: the span starts or ends inside that document sentence | `partial_sentence` |
| `normalise(text)` is not equal to `normalise(s)` for some whole sentence `s` of **every** cited span (`whole_sentences`: a `sentences-v2` sentence of the span's section text that lies wholly inside the span; no entailment checker exists before Phase 4) | `not_verbatim` |
| the cited spans hold the matching sentence in different characters | `not_verbatim` |
| the same sentence was already bound on every span it cites | `duplicate` (not a failure: it passed every check, as a merged claim does, so the ratio counts it as bound) |
| the same sentence was already bound on other spans | `merged` (not a failure: its spans join that claim's) |

The section text comes from `store.items` (the canonical item the span was cut from); a store that does not hold it exactly binds nothing from that span.

A claim is never re-bound to a span it did not cite. Phase 1's overlap rebinding is gone (plan 3.4, R-13). The draft keeps the span's own sentence (`whitespace()` form) as the claim text, never the generator's text (conflict 32). One sentence can sit in two adjacent spans (the splitter overlaps chunks by 120 characters), and the extractive generator then proposes it once per span: the merge locks it once, citing both spans, each of which holds it verbatim.

`claim_id = "claim-" + sha256(ledger_canonical({"text": normalise(text), "span_ids": sorted(span_ids)}))[:32]`: content-addressed, identical across plans and responses.

### 4.7 Lock (`tutor_pipeline/lock.py`)

```python
def lock(drafts, *, bundle, generator: GeneratorRef | None, evidential_prompt_hash: str | None,
         pedagogical_prompt_hash: str, resolver: ResolverRef, package: ConfigPackage) -> LockedClaimSet
def verify_locked(locked: LockedClaimSet) -> None
```

`source_order` is the claim's own place in the source, from binding: `(item_id, item offset of the sentence's first character)`, the earliest over its cited spans, so two sentences of one span keep their text order under the stepwise lead "in source order".

### 4.8 Renderer `template-renderer-v1` (`tutor_pipeline/render.py`)

```python
TEMPLATES = {   # (kind, text); params are integers only
  "concise.lead":   ("connective", "These sentences are quoted from the approved course sources:"),
  "stepwise.lead":  ("connective", "The approved course sources make these points, in source order:"),
  "stepwise.point": ("connective", "Point {0}:"),
  "socratic.open":  ("question",   "What do the approved course sources say about your question?"),
  "socratic.close": ("question",   "Which of these points would you like to look at more closely?"),
  "citation":       ("citation",   "[{0}]"),
}
RENDERER_ID = "template-renderer-v1"
PEDAGOGICAL_PROMPT_HASH_INPUT = {"id": RENDERER_ID, "templates": TEMPLATES, "plans": PLANS_LAYOUT, "join": "lines \\n, segments ' '"}
def pedagogical_prompt_hash() -> str: return canonical_sha256(PEDAGOGICAL_PROMPT_HASH_INPUT)
class Renderer(Protocol):
    renderer_id: str
    def render(self, locked: LockedClaimSet, plan: PresentationPlan, *, attempt: int) -> RenderedResponse: ...
class TemplateRenderer: ...
def layout_text(segments) -> str:      # "\n".join(" ".join(seg.text for seg in line) for line in lines)
```

**Layouts** (the renderer may reorder and add questions, and must not add claims or citations):
- **concise.** Line 0: `concise.lead`. Then one line per claim, in locked order: the claim segment, then one citation segment per span id.
- **stepwise.** Line 0: `stepwise.lead`. Then one line per claim, ordered by `(source_order, claim_id)`: `stepwise.point` with `params=(i,)`, the claim, then its citations.
- **socratic.** Line 0: `socratic.open`. Then claim lines in locked order, then a last line with `socratic.close`.

**Citations.** `citations` is the unique span ids by first appearance. A citation segment has `text=f"[{n}]"`, `params=(n,)` and `span_id`.

**Rules.** The template renderer renders every locked claim exactly once, using `LockedClaim.text` unchanged. It is never called for an abstention.

### 4.9 Subset check (`app/services/claim_gate.py`, repurposed; rule `segment-exact-whitespace-v3`)

```python
@dataclass(frozen=True)
class SubsetCheckResult: passed: bool; problems: tuple[str, ...]; factual_segments: int; mapped: int; missing_claims: int
def check_subset(rendered: RenderedResponse, locked: LockedClaimSet, *, templates=TEMPLATES) -> SubsetCheckResult
```

It first calls `verify_locked(locked)`. Each problem has a code:

| Code | Raised when |
|---|---|
| `empty` | there are no segments |
| `text_not_segments` | `layout_text(segments) != rendered.text`, a segment contains `"\n"`, or lines are not contiguous from 0 in order |
| `unmapped_factual_sentence` | a claim segment whose `claim_id` names no locked claim, or whose `whitespace(text)` differs from that claim's text (never NFKC-folded: a rendering that turns `x²` into `x2` changes what a learner reads). Claims are looked up by id, so two claims with one sentence both map. |
| `unmapped_factual_sentence` | a connective or question segment with an unknown `template_id`, a wrong kind, or `text != template.format(*params)`. Untyped text in a non-factual slot is treated as factual. |
| `duplicate_claim` | a locked claim is rendered twice |
| `citation_outside_locked_set` | a citation `span_id` not in `locked.span_ids`, or `set(rendered.citations) - set(locked.span_ids)` is non-empty |
| `citation_not_on_claim` | a citation on a line with no mapped claim, or a span not in that claim's span_ids |
| `citation_marker_mismatch` | marker text other than `"[{index+1}]"` |
| `no_claim_rendered` | the rendering shows no locked claim at all (connectives and questions only) |
| `claim_uncited` | a shown claim has no citation of one of its own locked spans on its line |
| `citation_list_mismatch` | `rendered.citations` is not exactly `displayed_span_ids(rendered)`: the spans the citation segments display, each once, in the order they first appear (a declared span no segment shows, a duplicate, or another order) |

- `passed = not problems`. `missing_claims` is reported, not failed (plan 3.7 requires a subset only), but a rendering that shows no claim, or a claim without its citation, fails.
- The ledger records what the passing rendering showed: `presentation.rendered_claim_ids` and `presentation.rendered_span_ids`, both taken from the segments (`pipeline.rendered_claim_ids`, `pipeline.rendered_span_ids`), never from the renderer's own citation list. `LedgerEntry` refuses an answer whose rendering showed no claim or no citation, or ids outside the record.
- The rule id is `segment-exact-whitespace-v3` (`claim_gate.SUBSET_CHECK_RULE`); `package_check` fails when the package names another id.
- The overlap `ClaimGate` and `evidence_digest` are deleted (M6; plan 3.4 "overlap rebinding removed").

### 4.10 Pipeline (`tutor_pipeline/pipeline.py`)

```python
@dataclass(frozen=True)
class PipelineInput:
    resolved: ResolvedQuestion; lesson_slug: str | None; presentation: PresentationPlan
    response_id: str; delivery: Literal["shadow"]; shadowed_response_id: str
@dataclass(frozen=True)
class PipelineResult:
    response_id: str; decision: Literal["answer", "abstain"]; abstention_reason: str | None
    request: RetrievalRequest; bundle: EvidenceBundle; envelope: EvidentialEnvelope | None; plan: ClaimPlan | None
    locked: LockedClaimSet; rendered: RenderedResponse | None; render_attempts: int
    entry: LedgerEntry; appended: AppendedRecord | None        # no learner-facing text field in Phase 3
class DeliveryNotImplemented(RuntimeError)
class TwoPassPipeline:
    def __init__(self, engine: RetrievalEngine, settings: Settings, *, generator: ClaimGenerator | None = None,
                 renderer: Renderer | None = None, session_factory=SessionLocal, clock=time.perf_counter): ...
    def run(self, item: PipelineInput, *, budget_ms: int | None = None, record: bool = True) -> PipelineResult
```

At `__init__`: `package = get_config_package(settings)`, raise `PipelineUnavailable` if `package.tutor_pipeline is None`; `store = engine.store`; `resolver = SpanResolver(store)`; `manifest_sha256` once (`CorpusRegistry.manifest_sha256`, 7.6); generator and renderer default to `get_generator(package)` and `TemplateRenderer(package)`.

**`run`, step by step.** `item.delivery != "shadow"` raises `DeliveryNotImplemented` while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (R-a). A budget check (`elapsed > budget_ms` abstains with `budget_exceeded`) runs after retrieval (step 2), generation (step 4) and binding (step 5), each only when that step has not already abstained, and between render attempts (step 7): never after a passing attempt or the last one, so a passing answer never depends on timing.
1. `request = build_request(item.resolved, lesson_slug=..., corpus_version=store.corpus_version)`.
2. `bundle = retrieve(...)`. If the sufficiency decision is `abstain`, abstain with its reason: the gate's own reason, `corpus_version_mismatch`, or `no_quotable_evidence` when the license gate dropped every result (4.3).
3. `envelope = build_envelope(...)`. None abstains with `no_envelope_reason(...)`: `no_quotable_evidence` when no bundle span is quotable, `no_whole_sentence` when the quotable spans hold no whole document sentence.
4. `plan = generator.propose(envelope)`, guarded; on error, a malformed plan or a plan that names another generator, abstain with `claim_plan_invalid`; zero claims abstain with `no_claims`. A budget overrun after generation counts the proposed claims as `dropped.budget_exceeded` (bind never runs).
5. `result = bind(...)`. No bound claims abstain with `no_bound_claims`.
6. `locked = lock(...)`. Always runs, so `claim_set_hash` exists for every two-pass response.
7. **Render loop.** For `attempt` in `1..1+max_regenerations`, render and check the subset; stop on the first pass. After a failed attempt that is not the last, the budget check runs, and an overrun abstains with `budget_exceeded`. If none passes, abstain with `subset_check_failed` (`rendered=None`; the locked claims are kept in the entry, withheld). An attempt that raises, in the renderer or in the subset check on its output, is a failed attempt that logs `tutor.two_pass.render_failed` (`step`, `render_attempt`, `error`); when every attempt raised, the run abstains with `render_failed` instead, so a crashing renderer is told apart from one that adds a claim. `LockedClaimSetTampered` still propagates.
8. `entry = self._entry(...)`, with `rendered_text_sha256 = sha256(text if answer else ABSTENTION)` and `versions.budgets` the budgets in force (`ledger.budget_stamp`).
9. If `record`, `appended = append_ledger_entry(entry, ..., budget_ms=ledger_budget_ms(...), attempts=ledger_append_attempts)`; any exception is raised as `LedgerWriteFailed`, which the runner counts.

### 4.11 Shadow runner (`tutor_pipeline/shadow.py`)

```python
# TWO_PASS_DELIVERY_IMPLEMENTED lives in contracts.py; shadow.delivery_implemented() reads it.
PIPELINE_UNAVAILABLE_REASON: str | None = None   # set (or cleared) by each start-up check (11.1)
@dataclass(frozen=True)
class ShadowJob:
    shadow_response_id: str; shadowed_response_id: str; thread_id: str; user_message_id: str
    lesson_slug: str | None; presentation: PresentationPlan
def effective_mode(settings: Settings, package: ConfigPackage) -> Literal["off", "shadow"]
def shadow_budget_ms(settings: Settings, package: ConfigPackage) -> int   # the override, else the package's
def run_shadow(job: ShadowJob, *, pipeline_factory: Callable[[], TwoPassPipeline], settings: Settings,
               session_factory=SessionLocal) -> None   # never raises
```

**`effective_mode` returns `"off"`** when any of: `package.tutor_pipeline is None`; `PIPELINE_UNAVAILABLE_REASON` is set; `not settings.tutor_ledger_enabled`; `settings.two_pass_tutor` is `"off"` or None. **`"on"`** returns `"shadow"` while `not TWO_PASS_DELIVERY_IMPLEMENTED`, and logs `tutor.two_pass.on_downgraded` once per process.

**`run_shadow`** (everything inside one `try`, pipeline construction included):
1. `pipeline = pipeline_factory()` (failure → `failed["pipeline"]`).
2. Open a session; `resolved = resolve_thread(db, job.thread_id, job.user_message_id, package=...)`; close it (failure → `failed["resolve"]`).
3. `pipeline.run(PipelineInput(resolved, ..., delivery="shadow", ...), budget_ms=shadow_budget_ms(settings, pipeline.package))`: `TWO_PASS_SHADOW_BUDGET_MS` when set, else the package's `tutor_pipeline.budgets.shadow_ms` (2000 ms, PD-11) (a ledger exception → `failed["ledger"]`, anything else → `failed["pipeline"]`).
4. Update the metrics and log `tutor.two_pass.shadow`.
5. Every exception is caught, counted, and logged as `tutor.two_pass.shadow_failed` with `{"step", "error": type(exc).__name__}` at ERROR. No message text and no id is logged.

### 4.12 Ledger (`app/services/ledger.py`; plan E "new ledger module", 7.1 L7 "modules ledger")

```python
CHAIN = "tutor-responses"; GENESIS_HASH = "0" * 64; SCHEMA_REVISION = "20261119_phase3_response_ledger"
def ledger_canonical(value) -> bytes:  # sort_keys, (",", ":"), ensure_ascii=False, allow_nan=False, UTF-8
def entry_bytes(entry: LedgerEntry) -> bytes: return ledger_canonical(entry.model_dump(mode="json"))
def record_hash_for(*, seq: int, created_at: datetime, prev_hash: str, entry_sha256: str) -> str:
    return sha256(ledger_canonical({"chain": CHAIN, "seq": seq, "created_at": _utc(created_at).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                                    "prev_hash": prev_hash, "entry_sha256": entry_sha256})).hexdigest()
@dataclass(frozen=True) class AppendedRecord: seq: int; record_hash: str; duplicate: bool
class LedgerConflict(RuntimeError)     # same response_id, different entry_sha256
class LedgerAppendError(RuntimeError)  # attempts or budget exhausted
def append_ledger_entry(entry: LedgerEntry, *, session_factory=SessionLocal, now=None, budget_ms: int,
                        attempts: int | None = None, log_fields: dict | None = None) -> AppendedRecord
def chain_head(db) -> tuple[int, str] | None
@dataclass(frozen=True) class LedgerCheck: count; first_seq; last_seq; head_hash; head_row: tuple[int, str] | None; problems: tuple[str, ...]; ok (property)
def verify_response_ledger(db, *, expected_head: tuple[int, str] | None = None) -> LedgerCheck
@dataclass(frozen=True) class LegacyDelivery: ...   # section 7.12
LEGACY_PIPELINE_VERSION = "legacy-contained-v1"; LEGACY_GENERATOR_ID = "contained-answers-v1"   # pinned in v2 tutor_pipeline.legacy
LEGACY_CONTAINMENT_RULE_HASH = canonical_sha256({"id": "contained-answers-v1", "mode": EXTRACTIVE_MODE,
    "max_quoted_spans": MAX_QUOTED_SPANS, "quotation_lead": QUOTATION_LEAD, "abstention": ABSTENTION})
def build_legacy_entry(delivery: LegacyDelivery, *, settings, package, manifest_sha256) -> LedgerEntry
def record_legacy_delivery(delivery: LegacyDelivery | LegacyPreparationFailed, *, settings=None, session_factory=SessionLocal) -> AppendedRecord | None   # fail-open
def ledger_budget_ms(settings, package) -> int          # TUTOR_LEDGER_APPEND_BUDGET_MS, else tutor_pipeline.budgets.ledger_append_ms
def attempt_horizon_s(params, budget_ms: int) -> int    # 360 s with the package's values (the coverage horizon, 7.15)
def dead_peer_horizon_s(params, budget_ms: int) -> int  # 840 s: the horizon with DEAD_PEER_READS (2) dead-peer reads per append
def ledger_coverage(db, since, *, now=None, horizon_s=None) -> dict   # 7.15, 7.16
def ledger_provenance(db, package) -> dict              # F-2's audit until a provider prompt exists (DI-49); 7.15, 7.16
def export_ledger(db, path) -> int; def restore_ledger(db, path) -> tuple[int, tuple[int, str] | None]
```

**Append** (at most `attempts` attempts within `budget_ms`, the package's `ledger_append_attempts` (3) by default; `created_at` fixed before the first attempt; small jitter between attempts as in the security log). Each attempt is one session and uses Core statements in this exact order:
1. On PostgreSQL: `SET LOCAL lock_timeout = '<remaining>ms'` (an int; no `%`; no bind parameter), then `statement_timeout` and `idle_in_transaction_session_timeout` to the same value, so every later statement of the attempt, the read in step 2 included, is bounded by the budget left. The last ends the session, and frees the head row's lock, if a stalled process holds it between statements.
2. If a row with `response_id` exists: an equal `entry_sha256` returns `duplicate=True`; a different one raises `LedgerConflict`.
3. `insert(ResponseLedgerHead).values(chain=CHAIN, seq=0, record_hash=GENESIS_HASH, updated_at=now, started_at=now).on_conflict_do_nothing(index_elements=["chain"])` (dialect insert). Start-up writes no head: the first append writes it, with `started_at`.
4. `head = SELECT seq, record_hash ... WHERE chain=CHAIN FOR UPDATE` (`with_for_update()`; a no-op on SQLite).
5. `seq = head.seq + 1`, `prev = head.record_hash`; `INSERT` the record (`entry = entry_bytes(entry).decode()`, `entry_sha256`, `record_hash`).
6. `UPDATE response_ledger_head SET seq, record_hash, updated_at WHERE chain=CHAIN`; commit.
7. An `IntegrityError` rolls back and retries if budget remains (a duplicate `response_id` is re-read as in step 2). A deadlock (SQLSTATE 40P01) or a serialization failure (40001) rolls back and retries the same way: the server rolled the whole attempt back (`RETRYABLE_SQLSTATES`). Every other `DBAPIError` (lock timeout, statement timeout, SQLite busy, trigger refusal) rolls back and raises at once.

On success it logs `tutor.ledger.appended` with `delivery`, `seq`, `record_hash`, `duplicate` and the caller's `log_fields` (the legacy `attempt` id): the off-DB copy, conflict 6.

**`record_legacy_delivery`** runs after the delivery's own commit, so a request that rolls back is never an attempt. It counts the attempt and what was delivered (decision and abstention reason, `LEDGER_METRICS`), and logs `tutor.ledger.attempted` with a random `attempt` id. It builds the entry and submits the append (`ledger_budget_ms(settings, package)`, `ledger_append_attempts`) to the appender's worker pool (`_LegacyAppender`: `ledger_append_workers` threads, at most `ledger_append_max_in_flight` running or queued, past which the append is refused at once and counted as failed). The request waits at most the budget plus `ledger_wait_grace_ms`; an append still running then logs `tutor.ledger.append_deferred` and ends in the background. Every attempt ends in exactly one terminal line with its `attempt` id: `tutor.ledger.appended`, or `tutor.ledger.append_failed` (ERROR; `delivery`, `stage`, `error` class), which also increments `failed["legacy"]`. It never raises and never changes the learner response.

**`attempt_horizon_s`** bounds how long a legacy attempt takes from its `attempted` line to its terminal line, and a turn from its `created_at` to its record, on an instance that keeps its CPU after the response: one append's connection wait (the pool's 30 s checkout timeout, `POOL_CHECKOUT_TIMEOUT_S`, and the 30 s connect bound `app.core.db.CONNECT_TIMEOUT_S`, which `cloud_sql_creator` enforces, since the Cloud SQL connector bounds no part of a new connection), `ATTEMPT_STATEMENTS` (6) statements of at most the budget each, after retries that all ended within the budget, times `ceil(ledger_append_max_in_flight / ledger_append_workers)` (4) appends in turn, plus `HORIZON_MARGIN_S` (60 s), rounded up to whole minutes: 360 s. One wait is not in the horizon: a reply on a connection that is already open, which the server's timeouts bound only while the server answers (the pre-ping and the first `SET LOCAL` run before any `statement_timeout` applies). The connector opens its socket with no timeout and no keepalive, and pg8000 keeps a given socket as it is, so `cloud_sql_creator` turns TCP keepalive on for each new connection's socket (`app.core.db.enable_tcp_keepalive`, 7.19). When the database host or the network to it is gone, the kernel then ends the read within `DEAD_PEER_BOUND_S` (60 s) of the connection's last traffic, and an append meets at most two such reads (`DEAD_PEER_READS`: a pooled connection's pre-ping, after which the pool replaces it, and one statement, after which the append fails), so **`dead_peer_horizon_s`** is the same sum with 120 s more per append: 840 s. When the server keeps the connection up and never replies, nothing in the code ends the read: it lasts until the server replies or the process exits, holding one of the appender's workers. So on an always-on instance an attempt later than the horizon means such a stall (a stop), and one still without a terminal line after 840 s is held by a server that never replies: the runbook replaces the instance (infra/cloudrun/deployment.md, Phase 3). With request-based CPU allocation nothing bounds it (DI-48).

**`verify_response_ledger`** reads the head first, then streams the rows up to it by `seq` ascending (`yield_per(500)`); rows past that head are appends that committed during the check, counted as `appended_during_check`, and a problem only when a head read afterwards still does not cover them, so a check under live traffic never reads a sound chain as broken. No retention applies, so the first row must be seq 1. Each row's entry is validated with `ENTRY_SCHEMAS[row.entry_schema]` (an unknown schema is a problem). Problem messages:

| Message | Meaning |
|---|---|
| `"seq {a} to {b} missing"` | a gap |
| `"seq 1 does not start from the genesis hash"` | a bad start |
| `"seq {n} does not chain onto seq {m}"` | a broken link |
| `"seq {n} entry does not match its entry_sha256"` | an edited entry |
| `"seq {n} does not match its record_hash"` | an edited row |
| `"seq {n} entry is not canonical JSON"` | `ledger_canonical(json.loads(entry)) != entry` |
| `"seq {n} entry fails {entry_schema}"` / `"seq {n} has an unknown entry_schema"` | it does not validate |
| `"seq {n} columns disagree with its entry"` | response_id, delivery, decision, shadowed_response_id, claim_set_hash or entry_schema differ |
| `"the chain head is missing"` / `"the chain head (seq {h}) does not match the last record (seq {l})"` | the head row disagrees |
| `"seq {n} lies past the chain head (seq {h})"` | a record no head covers (inserted without moving the head) |
| `"the chain no longer reaches the logged head seq {s}"` | `expected_head` is not in the chain with an equal hash |

**`ledger_provenance(db, package)`** is F-2's audit until a provider prompt exists (plan 15.1 "Zero learner-state fields in evidential-pass prompts"; DI-49): no evidential prompt is logged or ledgered, so every record must instead name the pinned, learner-free evidential input of its pipeline. It reads `seq` and `entry` in `seq` order (`yield_per(500)`; read-only) and compares each record stamped with the package in force (`versions.config_package_sha256 == package.sha256`) with that package's pins. A legacy record (`pipeline == tutor_pipeline.legacy.pipeline_version`) must carry `provenance.evidential_prompt_hash == legacy.containment_rule_hash`, `provenance.generator_model_id == legacy.generator_model_id`, no pedagogical prompt hash, and `versions.pipeline_version` and `versions.generator_id` equal to the legacy ids. A two-pass record (`pipeline == tutor_pipeline.version`) must carry the package's evidential and pedagogical prompt hashes, its version, a generator in `generators_allowed` and the resolver prompt hash in `resolved_question.resolver.prompt_hash`. Every claim must carry its record's provenance. A record stamped with another package is counted (`other_package`) and not compared; one naming another pipeline, or whose entry is not a JSON object, is a problem. It returns `package_version`, `package_sha256`, `records`, `checked`, `other_package`, `problem_count` and the first 50 `problems` (`"seq {n} provenance.evidential_prompt_hash is not the package pin"` and the like: seq numbers and field names, never record text). The worker's and the script's `--check-provenance` run it (7.15, 7.16).

### 4.13 Evidence panel (`app/services/evidence_panel.py`)

```python
def build_evidence_panel(*, decision: str, citations: list[Citation], retrieval_mode: str, settings: Settings) -> EvidencePanel
```

- `labels = ["lexically_screened"] if decision == "answer" else []`.
- `degraded = ["extractive_only"]` (D-19: generation is off), plus `"retrieval_fallback"` when `retrieval_mode.startswith("lexical-fallback")`, plus `"citations_provisional"` when any citation is provisional.
- `spans = [EvidenceSpanLink(span_id=c.span_id, label=f"{c.source_title} — {c.section_title}", resolvable=settings.span_resolver_route_enabled)]` for the delivered citations.
- The panel never reads shadow output. `/qa/ask` carries the same panel under `EVIDENCE_PANEL_ENABLED` (E-46 names the Q&A citation cards).

---

## 5. Configuration package v2 (`apps/api/app/config_package/v2.json`)

### 5.1 File
- v2 is a copy of v1 with: `package_version: "2.0.0"`, `schema_version: 2`, `phase: "3"`, `created: "2026-11-19"`, and the additions below.
- Blocks copied unchanged: `span_identity`, `corpus_version`, `gates`, `retrieval`, `semantic`, `near_duplicate`, `legacy_citations`, `boundary`. `abstention` gains only `calibrated_with_package_version`. `owner_decisions` keeps `D-17`, `D-30`, `Q-10` and `PLAN-11.3` unchanged and adds `D-19`, `D-12`, `PLAN-3.3` and `PLAN-12.8`.
- `retrieval_sha256` is unchanged, so `index_version` and `corpus_version` are unchanged.
- Sidecar: `v2.json.sha256`. `v1.json` and its sidecar stay readable for one release (DI-42).
- The listing below is `v2.json` with long strings shortened (`…`) and the v1 blocks left out; `v2.json` is the source of truth. The `owner_decisions.D-12` path and the `evidential` block are given in full, and a test compares the D-12 path with the package. Every block whose values have no plan text is marked `provisional: true` with an `authority` naming its register row (`tutor_pipeline`, `budgets`, `idempotency`, `flag_policy`), and the loader refuses it unmarked (5.2).

```json
"supersedes": {"package_version": "1.0.0", "sha256": "060c59f2ac94dcd20b16f9e7bd3e21128b952b067135ac29a91821b02bc04403", "readable_until": "the release after the Phase 3 merge"},
"abstention": {"...v1 fields...": "...", "calibrated_with_package_version": "1.0.0"},
"tutor_pipeline": {
  "version": "two-pass-v1", "status": "provisional", "provisional": true, "phase": "3", "authority": "plan Phase 3 tasks 3.1-3.8; every value without plan text is an engineering para…",
  "schemas": {
    "ResolvedQuestion": {"version": "resolved-question-v1", "path": "schemas/resolved-question.v1.schema.json", "sha256": "418b57092b72…"},
    "RetrievalRequest": {"version": "retrieval-request-v1", "path": "schemas/retrieval-request.v1.schema.json", "sha256": "2c53d4186caa…"},
    "EvidenceBundle": {"version": "evidence-bundle-v1", "path": "schemas/evidence-bundle.v1.schema.json", "sha256": "4ed6eb773cbd…"},
    "EvidentialEnvelope": {"version": "evidential-envelope-v1", "path": "schemas/evidential-envelope.v1.schema.json", "sha256": "df47a128da24…"},
    "ClaimPlan": {"version": "claim-plan-v1", "path": "schemas/claim-plan.v1.schema.json", "sha256": "1b65d4dcacc0…"},
    "LockedClaimSet": {"version": "locked-claim-set-v1", "path": "schemas/locked-claim-set.v1.schema.json", "sha256": "73682a185c3a…"},
    "PresentationPlan": {"version": "presentation-plan-v1", "path": "schemas/presentation-plan.v1.schema.json", "sha256": "148887672600…"},
    "LedgerEntry": {"version": "ledger-entry-v1", "path": "schemas/ledger-entry.v1.schema.json", "sha256": "cc84fa000eb7…"}
  },
  "resolver": {"id": "thread-resolver-v1", "prompt_hash": "c7409f113bf7…", "min_content_terms": 2, "continuation_cues": ["and ", "also ", "but ", "so ", "then ", "what about ", "how about "], "max_lookback": 4, "inputs": "the learner's own user messages of the same thread (plan 3.1)"},
  "retrieval": {"request_fields": ["text", "lesson_slug", "corpus_version"], "top_k": 4, "mode": "lexical", "near_miss_rule": "gate-near-floor-flag-of-top-result-v1"},
  "evidential": {"generator_default": "extractive-d19-v1", "generators_allowed": ["extractive-d19-v1"], "prompt_hash": "6bf3f1f10303…", "max_claims": 3, "max_claims_per_span": 2, "min_sentence_words": 4, "max_sentence_chars": 1000, "min_question_overlap_terms": 1, "sentence_rule": "sentences-v2", "binding_rule": "resolver-bundle-sentence-v2"},
  "pedagogical": {"renderer": "template-renderer-v1", "prompt_hash": "452fbef12b51…", "presentation_plans": ["concise", "stepwise", "socratic"], "default_plan": "concise", "max_regenerations": 2, "max_regenerations_authority": "plan 3.7: at most two", "subset_check": "segment-exact-whitespace-v3"},
  "ledger": {"chain": "tutor-responses", "entry_schema": "ledger-entry-v1", "record_hash_rule": "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1", "genesis": "0000000000000000000000000000000000000000000000000000000000000000", "deliveries": ["legacy", "shadow", "delivered"], "retention": "retain"},
  "legacy": {"pipeline_version": "legacy-contained-v1", "generator_id": "contained-answers-v1", "generator_model_id": "extractive-lexically-screened", "containment_rule_hash": "aa942034579c…", "authority": "the D-19 contained path (task 1.11) that every legacy ledger record names, production's only records; pinned so…"},
  "stop": {"phase2_bound_claim_ratio": 1.0, "authority": "plan Phase 3 L; measured, spec M1"},
  "budgets": {"provisional": true, "authority": "PD-11: engineering parameters with no plan value (E1 'bounded budget'; spec conf…", "shadow_ms": 2000, "ledger_append_ms": 1500, "ledger_append_attempts": 3, "ledger_wait_grace_ms": 250, "ledger_append_workers": 4, "ledger_append_max_in_flight": 16},
  "idempotency": {"provisional": true, "authority": "plan 7.3 'mutations carry client keys' (DI-40); the values are engineering param…", "header": "Idempotency-Key", "key_pattern": "^[A-Za-z0-9._:-]{8,128}$", "ttl_hours": 24, "in_progress_lease_seconds": 600},
  "unused_provenance_fields": ["v1_3_checker_model_id", "panel_weights_version", "routing_table_version", "tool_contract_version"]
},
"flag_policy": {"provisional": true, "authority": "PD-10: the Phase 3 switches outside development (plan Phase 3 G; AC-3-6; 13.6);…", "two_pass_tutor": {"values": ["off", "shadow", "on"], "default_development": "shadow", "default_elsewhere": "off", "on_requires": "phase4_exit_passed", "authority": "plan Phase 3 G; AC-3-6; 13.6"}, "phase4_exit_passed": false, "phase4_exit_evidence": null},
"owner_decisions": { "D-17": "...unchanged", "D-30": "...unchanged", "Q-10": "...unchanged", "PLAN-11.3": "...unchanged",
  "D-19": {"option": "RECOMMENDATION (no-provider extractive mode)", "text": "no-provider extractive mode quoting spans only from manifest-approved public-pla…", "status": "provisional", "authority": "P1-D-18 (owner delegation, 2026-11-19)", "ratified": false, "applied_to": ["legacy contained answers (task 1.11)", "two-pass evidential generator extractive-d19-v1"], "record": "PD-08"},
  "PLAN-3.3": {"status": "provisional", "ratified": false, "authority": "P1-D-18 (engineering reading under D-19); acceptance needs the Principal Investi…", "deviations": [{"plan": "3.3: \"Claim plan: atomic claims bound to span ids from a structured envelope; un…", "applied": "under D-19 extractive mode the claim unit is one verbatim whole sentence of ever…"}], "record": "Phase 3 spec conflict 34; DI-47"},
  "D-12": {"state": "open", "path": "hold H6 blocks the provider interim path (D-12, a single pinned provider; plan 9.4 H6 'P3 interim path') and stays held; no provider generator is wired, and Phase 3 runs D-19 extractive mode instead, which sends no provider payload", "ratified": false, "record": "PD-09"},
  "PLAN-12.8": {"state": "open", "text": "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted…", "path": "unresolved: the response ledger is retained; no job deletes ledger rows (the app…", "behaviour": "retain", "ratified": false, "record": "DI-45", "proposed_default": "release life plus 24 months", "proposed_default_applied": false, "why_not_applied": "a 12.8 'proposed default' is not one of the default forms the provisional-defaul…"}
}
```

### 5.2 Loader (`app/core/config_package.py`)

**Constants:** `DEFAULT_PACKAGE_PATH` becomes `.../v2.json`; add `V1_PACKAGE_PATH`; `WIRED_GENERATORS = frozenset({"extractive-d19-v1"})` ("D-12 open: no provider generator is wired (hold H6)"); `TUTOR_SCHEMA_NAMES` (the 8 names in 5.1).

**Parsing.** `parse_config_package` accepts `schema_version` 1 or 2. For 1: `tutor_pipeline=None`, `flag_policy=FlagPolicy(False, None)`. For 2, any failure raises `ConfigPackageError`, governed or not:
- `supersedes` is an object with `package_version` and a 64-hex `sha256`;
- every v1 block, by the existing v1 rules;
- `tutor_pipeline` (next table);
- `flag_policy`: marked `provisional: true`; `two_pass_tutor.values == ["off", "shadow", "on"]`; `default_elsewhere` and `default_development` equal the code's `TWO_PASS_DEFAULT_ELSEWHERE` ("off") and `TWO_PASS_DEFAULT_DEVELOPMENT` ("shadow"); `on_requires == "phase4_exit_passed"`; `phase4_exit_passed` is a bool, and when true `phase4_exit_evidence` is a non-empty string;
- `owner_decisions`: `D-12` and `D-19` are objects; `D-12.state == "open"` implies `generators_allowed == ["extractive-d19-v1"]`; `PLAN-12.8` is an object whose `state` is `"open"` and whose `behaviour`, like `tutor_pipeline.ledger.retention`, is `"retain"` (no retention job exists, DI-45).

| `tutor_pipeline` check | Rule |
|---|---|
| schema names | exactly `TUTOR_SCHEMA_NAMES` |
| schema `path` | relative, under `schemas/`, no `..`, no drive letter or colon (existence is checked in 5.4, not here) |
| hashes | each `sha256` and each prompt hash is 64 lowercase hex characters |
| resolver | `min_content_terms` and `max_lookback` 1-20; the continuation cues are lowercase |
| retrieval | `1 ≤ top_k ≤ 12`; `request_fields == ["text", "lesson_slug", "corpus_version"]`; `mode == "lexical"` |
| generators | `generators_allowed` ⊆ `WIRED_GENERATORS` and `generator_default` is in it |
| claim and sentence limits | `1 ≤ max_claims ≤ 10`, `1 ≤ max_claims_per_span ≤ max_claims`, `min_sentence_words` 1-50, `max_sentence_chars` 50-100000, `min_question_overlap_terms` 1-20 |
| plans | `presentation_plans` ⊇ {concise, stepwise, socratic}, `default_plan` is in them, `max_regenerations` 0-2 |
| ledger | `deliveries` exactly legacy, shadow and delivered; `genesis` is 64 zeros; `retention` a string (the PLAN-12.8 rule above) |
| legacy | an object with `pipeline_version`, `generator_id` and `generator_model_id` (strings) and `containment_rule_hash` (64 lowercase hex characters) |
| stop | `0 < phase2_bound_claim_ratio ≤ 1` |
| `budgets` | marked `provisional: true`; `shadow_ms` 100-30000, `ledger_append_ms` 100-5000, `ledger_append_attempts` 1-5, `ledger_wait_grace_ms` 0-1000, `ledger_append_workers` 1-16, `ledger_append_max_in_flight` from the worker count to 256 |
| `idempotency` | marked `provisional: true`; `key_pattern` compiles, is anchored and refuses the empty key and any key over 256 characters; `ttl_hours` 1-168; `in_progress_lease_seconds` 60-3600 and below the TTL |
| `unused_provenance_fields` | equals the four names |

**New dataclasses:** `TutorPipelineParams` (every value above, plus `schemas: Mapping[str, SchemaPin(version, path, sha256)]` and the derived `schemas_sha256`), `FlagPolicy(phase4_exit_passed: bool, phase4_exit_evidence: str | None)`. **`ConfigPackage`** gains `schema_version`, `tutor_pipeline`, `flag_policy`, `supersedes`. `AbstentionParams` gains `calibrated_with_package_version: str | None`.

### 5.3 Calibration lineage (`scripts/calibrate_abstention.py`)
- Line 373 becomes `"config_package_version": package.abstention.calibrated_with_package_version or package.package_version`. Nothing else changes; `--check` passes on v2 with the committed record unchanged.

### 5.4 Pipeline/package consistency check (`tutor_pipeline/package_check.py`)

```python
def check_tutor_pipeline_package(package: ConfigPackage, *, structural: bool) -> list[str]
```

Always:
- a schema file missing, or its canonical sha256 differing from its pin;
- `resolver_prompt_hash(...)`, `evidential_prompt_hash(...)` or `pedagogical_prompt_hash()` differing from the pinned values;
- the `GENERATORS` keys differing from `WIRED_GENERATORS`;
- a rule id or name the package records differing from the code's: `evidential.sentence_rule` (`SENTENCE_RULE`), `evidential.binding_rule` (`BINDING_RULE`), `pedagogical.subset_check` (`SUBSET_CHECK_RULE`), `retrieval.near_miss_rule` (`NEAR_MISS_RULE`), `ledger.chain` (`CHAIN`), `ledger.entry_schema` (`LedgerEntry`'s literal), `ledger.record_hash_rule` (`RECORD_HASH_RULE`) and `ledger.genesis` (`GENESIS_HASH`);
- `tutor_pipeline.version` against `PIPELINE_VERSION`, `resolver.id` against `RESOLVER_ID`, `pedagogical.renderer` against `RENDERER_ID` and `idempotency.header` against `turn_idempotency.IDEMPOTENCY_HEADER` (the header the route reads);
- `presentation_plans` and `default_plan` against the renderer's `PLANS_LAYOUT` and the `PresentationPlan` contract (exactly those plans, no repeats, the default one of them);
- the legacy contained path that every legacy ledger record stamps: `legacy.pipeline_version` against `ledger.LEGACY_PIPELINE_VERSION`, `legacy.generator_id` against `ledger.LEGACY_GENERATOR_ID`, `legacy.generator_model_id` against `contained_answers.EXTRACTIVE_MODE` and `legacy.containment_rule_hash` against `ledger.LEGACY_CONTAINMENT_RULE_HASH` (the provenance audit's reference values, DI-49);
- `tutor_pipeline.version` and `legacy.pipeline_version` each one of the pipelines the `LedgerEntry` contract accepts.

With `structural=True` (tests and `config_package.py --check` only, M21): a committed schema whose structure differs from `SCHEMA_MODELS[name].model_json_schema(mode="validation")`. The structure is the property names, the required set, `additionalProperties` at every object, the `$ref` targets and the leaf constraints (`package_check.LEAF_KEYWORDS`: `type`, `enum`, `const`, `pattern`, `format`, the length, value, item and property bounds, `multipleOf`, `uniqueItems` and `default`), recursively through `$defs`. Annotations (`title`, `description`) are not compared.

**Start-up policy** (11.1, conflict 30): `structural=False`. A problem stops a governed build only when `TWO_PASS_TUTOR != "off"`; otherwise (and always in development) it sets `PIPELINE_UNAVAILABLE_REASON`, logs `tutor.two_pass.unavailable`, and `effective_mode` is off. The unit test requires zero problems with `structural=True`.

### 5.5 Scripts (`scripts/config_package.py`)
- **`--check [--path P]`:** the existing checks, plus, for schema 2, `check_tutor_pipeline_package(..., structural=True)`. Prints the version, sha and two-pass ids.
- **`--rehash [--path P]`:** the stopword hash and, for schema 2, the schema pins from the files, and the three prompt hashes and `legacy.containment_rule_hash` from the code; then rewrites the sidecar.
- **`--write-schemas`:** writes `SCHEMA_MODELS[name].model_json_schema(mode="validation")` to the eight files as `json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"` (LF). Then `--rehash`.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `TWO_PASS_TUTOR` | `Literal["off","shadow","on"] \| None = None`; `None` → `"shadow"` in development, `"off"` elsewhere | Plan G (L1255): "two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners". `on` is refused (below). `shadow` outside development records a `config.override` (`two_pass_tutor_shadow`). |
| `TWO_PASS_SHADOW_BUDGET_MS` | `int \| None = Field(None, ge=100, le=30000)`; None = the package's `tutor_pipeline.budgets.shadow_ms` (2000) | E1 "bounded budget". The shadow runs after the response body is sent; the budget bounds how long it holds a worker thread and the connection's next request (19). |
| `TUTOR_LEDGER_ENABLED` | `bool = True` | Not learner-visible. Kill switch for the new request-path write, like `SPAN_REGISTRY_WRITE_THROUGH`. Disabling it outside development is a `config.override` (`tutor_ledger_disabled`): it relaxes the audit control (R-22). |
| `TUTOR_LEDGER_APPEND_BUDGET_MS` | `int \| None = Field(None, ge=100, le=5000)`; None = the package's `tutor_pipeline.budgets.ledger_append_ms` (1500) | Bounds the legacy append (conflict 29); also the PostgreSQL lock, statement and idle-in-transaction timeouts of each attempt. Setting either budget outside development records a `config.override` (`shadow_budget_overridden`, `ledger_append_budget_overridden`). |
| `LEDGER_ROUTE_ENABLED` | `bool \| None = None`: development true, elsewhere false | A new route under the freeze (conflict 4). Enabling it outside development is a `config.override` (`ledger_route_enabled`). |
| `EVIDENCE_PANEL_ENABLED` | `bool \| None = None`: development true, elsewhere false | E5 and E9 (conflict 24). Enabling it outside development is a `config.override` (`evidence_panel_enabled`). |
| `LEDGER_RATE_LIMIT` | `"30/minute"` | Like `SPANS_RATE_LIMIT` (PD-11). |

`POST /tutor/turns` has no rate-limit setting of its own: it and `POST /assistant/chat` deliver the same tutor turn and share one window, scope `tutor-turn`, at `ASSISTANT_CHAT_RATE_LIMIT` (8/minute), so alternating them never doubles a client's budget.

Derived property `tutor_turns_route_enabled = environment == "development" or two_pass_tutor == "on"`.

**Validator additions** (in `validate_allowed_origins`, after `enforce_corpus_governance` is resolved):

```python
if self.two_pass_tutor is None:   # TWO_PASS_DEFAULT_DEVELOPMENT, TWO_PASS_DEFAULT_ELSEWHERE (flag_policy, 5.2)
    self.two_pass_tutor = "shadow" if env == "development" else "off"
if self.ledger_route_enabled is None: self.ledger_route_enabled = env == "development"
if self.evidence_panel_enabled is None: self.evidence_panel_enabled = env == "development"
if self.two_pass_tutor == "on":
    from app.core.config_package import ConfigPackageError, get_config_package   # lazy: avoids the import cycle
    try: package = get_config_package(self)
    except ConfigPackageError as exc: raise ValueError(f"TWO_PASS_TUTOR=on needs a valid configuration package: {exc}") from exc
    if not package.flag_policy.phase4_exit_passed:
        raise ValueError("TWO_PASS_TUTOR=on is refused before the Phase 4 exit (configuration package "
                         "flag_policy.phase4_exit_passed is false; plan Phase 3 G, AC-3-6). Use off or shadow.")
    if env != "development" and not (package.is_default_path and package.hash_verified):
        raise ValueError("TWO_PASS_TUTOR=on outside development needs the shipped, hash-verified package.")
```

- The package is loaded only when `on` is set, so every other construction of `Settings` is unaffected.
- `TWO_PASS_TUTOR=on` in the environment makes `get_settings()` raise at import (API, workers, Alembic `env.py`), so nothing starts and no table is touched.
- `infra/cloudrun/api-production.env.example.yaml` sets five of these settings to their non-development values, each with its rationale: `TWO_PASS_TUTOR: "off"`, `TUTOR_LEDGER_ENABLED: "true"`, `LEDGER_ROUTE_ENABLED: "false"`, `EVIDENCE_PANEL_ENABLED: "false"` and `LEDGER_RATE_LIMIT: "30/minute"`. It leaves the two budgets unset, so the package values hold; its comments name `TWO_PASS_SHADOW_BUDGET_MS` and `TUTOR_LEDGER_APPEND_BUDGET_MS` as overrides only. `POST /tutor/turns` uses the existing `ASSISTANT_CHAT_RATE_LIMIT`. `test_api_cloud_run_example_disables_demo_auth_and_documents_secret_injection` must keep passing.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/services/tutor_pipeline/` (plan 7.1 L5: "module tutor_pipeline")

| Module | Contents |
|---|---|
| `__init__.py` | Re-exports `TwoPassPipeline`, `PipelineInput`, `PipelineResult`, `ShadowJob`, `run_shadow`, `effective_mode`. |
| `contracts.py` | 3.1-3.3; `ABSTENTION_REASONS`, `LEARNER_STATE_FIELDS`, `SCHEMA_MODELS`, `ENTRY_SCHEMAS`. |
| `text.py` | 4.1 |
| `resolve.py` | 4.2 |
| `retrieve.py` | 4.3 |
| `evidential.py` | 4.5 |
| `bind.py` | 4.6 |
| `lock.py` | 4.7 |
| `render.py` | 4.8 |
| `pipeline.py` | 4.10 |
| `shadow.py` | 4.11 |
| `metrics.py` | 11.3 |
| `package_check.py` | 5.4 |

**Import rule (scanned by AC-3-1).** No module in the package may import `app.services.learner_record`, `learner_progress`, `learning_intelligence` or `microlearning`; `app.core.auth`; `app.api.routes.*`; `app.services.answer_history` or `app.services.retrieval_legacy_p1`. `resolve.py` may import `app.db_models.TutorMessage`. All loggers in the package and in `ledger.py` are `logging.getLogger("qcai.tutor")` (M23).

### 7.2 MOD `app/services/claim_gate.py`
- The overlap gate is replaced by 4.9. Docstring: "Subset checker (plan Phase 3 E: "claim_gate becomes the subset checker"; 3.4 overlap rebinding removed). Phase 4 V1.4 subsumes it."

### 7.3 NEW `app/services/ledger.py` (4.12) and `app/services/evidence_panel.py` (4.13)

### 7.4 MOD `app/services/contained_answers.py`
- Add `span_is_quotable` (4.4) only (`SpanRecord` imported under `TYPE_CHECKING`). `contain_answer` is byte-for-byte unchanged.

### 7.5 MOD `app/services/retrieval_engine.py`
- Add `def evidence(self, query, lesson_slug=None, top_k=8) -> RetrievalResponse`: `store.evaluate(query, lesson_slug, top_k=max(top_k * 2, top_k))`, lexical results `[:top_k]`, `mode="lexical"`, the same `RetrievalResponse` fields as the lexical branch of `_search`. It never calls the semantic backend (conflict 33) and records no Phase 2 SLI, so shadow runs never double-count learner-facing abstention. The AC-2-9 signature allowlist covers it (`query, lesson_slug, top_k`).

### 7.6 MOD `app/core/corpus_governance.py`
- Add `CorpusRegistry.manifest_sha256: str | None`, a cached property: `canonical_sha256(json.loads(manifest bytes))`, or `None` without a manifest.

### 7.7 MOD `app/core/config_package.py` (5.2), `app/core/config.py` (6), `scripts/config_package.py` (5.5), `scripts/calibrate_abstention.py` (5.3)

### 7.8 NEW `apps/api/app/config_package/v2.json`, `v2.json.sha256`, `schemas/*.v1.schema.json` (8 files)

### 7.9 MOD `app/db_models.py` and `app/core/schema_upgrades.py` (section 8)
- NEW `apps/api/alembic/versions/20261119_phase3_response_ledger.py` (8.3). MOD `apps/api/alembic/versions/20261119_phase2_corpus_spans.py`: its docstring only (the append-only triggers are checked at each start and re-created when not current).

### 7.10 MOD `app/services/teaching_assistant.py`
- `chat()` sets `response._retrieval = retrieval` (the `RetrievalResponse`) on the response it returns; nothing serialised changes (M20).
- Add the pipeline (plan E "teaching_assistant (two passes)"):
  ```python
  @cached_property
  def pipeline(self) -> "TwoPassPipeline":
      from app.services.tutor_pipeline import TwoPassPipeline
      return TwoPassPipeline(self.retrieval_engine, self.settings)
  ```
- The Vertex helpers are unchanged; the provider path is Phase 5.

### 7.11 MOD `app/services/tutor_orchestrator.py`
- `chat(self, db, user, payload, *, presentation_plan: str | None = None) -> AssistantChatResponse`. The legacy logic and `_resolve_query` are unchanged, with these additions:
  1. Message times are set in Python under a per-thread lock, never earlier than the thread's latest message (`next_message_time`): the user message gets `now`, the assistant message `now + 1 µs`, the turn and `thread.updated_at` `now`, so a thread's messages are strictly ordered on every dialect. Ids kept in locals (`user_message_id`, `turn_id`). (A production stored-data change: Python time replaces database time for these rows; 18.1.)
  2. `evidence = build_evidence_panel(...) if self.settings.evidence_panel_enabled else None`, set on the response.
  3. `response._followups = TurnFollowups(legacy, shadow)`, each prepared separately so a failure in one never loses the other (18.2 item 7):
     - `legacy = LegacyDelivery(...)` if `settings.tutor_ledger_enabled`, else None; a preparation failure becomes a `LegacyPreparationFailed`, which `record_legacy_delivery` counts after the commit as a failed attempt (`tutor.ledger.append_failed`, stage `prepare`);
     - `shadow = ShadowJob(shadow_response_id=f"shadow-{uuid4()}", shadowed_response_id=turn_id, thread_id=thread.id, user_message_id=..., lesson_slug=payload.lesson_slug, presentation=PresentationPlan(plan_id=presentation_plan or package default, source="request" if presentation_plan else "default"))` if `effective_mode(...) == "shadow"`, else None.
- `run_shadow(self, job)` calls `tutor_pipeline.run_shadow(job, pipeline_factory=self._pipeline, settings=self.settings)`; it never raises.
- `_pipeline()` returns `self.assistant.pipeline` when the assistant is a `TeachingAssistantService`, else `TwoPassPipeline(get_retrieval_engine(), self.settings)` (lazy import of `app.services.store` to avoid the cycle).

### 7.12 `LegacyDelivery` (in `ledger.py`) and the follow-ups
- `LegacyDelivery` holds: `response_id` (a turn id, or a random `qa-` id for `/qa/ask`), `decision`, `reason` (the gate's own abstention reason when the gate returned nothing, else `no_approved_span`; `delivered_abstention_reason`), `claims: tuple[(text, span_ids)]`, `quoted: tuple[EvidenceSpan]` (delivered citations, `score=None`), `retrieved: tuple[EvidenceSpan] | None` (from `candidate._retrieval` when present, with scores and `near_floor`; None otherwise, giving `evidence_scope="delivered_citations"`), `answer_sha256`, `retrieval_mode`, `provider`, `model`, `corpus_version`, `index_version`, `gate`, `threshold_version`, `floor`, `margin` (from the orchestrator's store), `policy_version`, `dropped_unresolved`, `manifest_sha256`, `dropped_not_public`, `surface` (`tutor` or `qa`) and `sufficiency` (the gate's decision). `legacy_delivery_for` builds it for both surfaces.
- **NEW `app/services/tutor_followups.py`:**
  ```python
  def run_turn_followups(response, orchestrator, background_tasks) -> None:
      followups = getattr(response, "_followups", None)
      if not isinstance(followups, TurnFollowups): return
      if followups.legacy is not None:
          record_legacy_delivery(followups.legacy, settings=getattr(orchestrator, "settings", None))   # never raises
      if followups.shadow is not None and hasattr(orchestrator, "run_shadow"):
          TWO_PASS_METRICS.scheduled()
          background_tasks.add_task(orchestrator.run_shadow, followups.shadow)
  ```

### 7.13 Routes

**MOD `app/api/routes/assistant.py`**
- Add a `background_tasks: BackgroundTasks` parameter.
- Factor the body into `deliver_tutor_turn(request, response, payload: AssistantChatRequest, background_tasks, db, user, *, presentation_plan=None) -> AssistantChatResponse`:
  1. `orchestrator = get_tutor_orchestrator()`, from this module's globals so the existing monkeypatches work;
  2. `orchestrator.chat(...)`, passing `presentation_plan` only when not None (stubs keep working);
  3. the `QAInteraction` row, `persist_cited_spans` and `db.commit()`, as today;
  4. `run_turn_followups(...)`;
  5. the existing headers.
- The `/chat` handler calls it.

**NEW `app/api/routes/tutor.py`** (`APIRouter(prefix="/tutor", tags=["tutor"])`):

```python
@router.post("/turns", response_model=TutorTurnResponse)
@limiter.shared_limit(tutor_turn_rate_limit, scope=TUTOR_TURN_RATE_LIMIT_SCOPE)   # /assistant/chat's window
def create_tutor_turn(request: Request, response: Response, payload: TutorTurnRequest, background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    if not get_settings().tutor_turns_route_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not Found"}, headers={"Cache-Control": "no-store"})
    clean = sanitize_user_text(payload.message)   # 422 if empty, as /assistant/chat
    chat = AssistantChatRequest(message=clean, thread_id=payload.thread_id, lesson_slug=payload.lesson_slug)
    delivered = deliver_tutor_turn(request, response, chat, background_tasks, db, user, presentation_plan=payload.presentation_plan)
    return TutorTurnResponse(**delivered.model_dump(), delivery="legacy")
```

In development the route also honours an optional `Idempotency-Key` header (`app/services/turn_idempotency.py`; package `tutor_pipeline.idempotency`): the sha256 of the key, scoped to the caller, and of the request (message, thread, lesson scope, presentation plan) are claimed in `tutor_turn_idempotency` (user-keyed) before the turn; a retry with the same key and request returns the first turn's stored response with `Idempotent-Replayed: true`; the same key with another request is 422; a malformed key is 422; a retry while the first request still holds its claim is 409, until the claim's `in_progress_lease_seconds` (600 s) pass, after which a retry takes the key over. Each claim carries a random claim token that the turn's own transaction must still hold at commit (`ClaimLost`, 409), so one key never yields two turns. Keys expire after `ttl_hours` (24).

**NEW `app/api/routes/ledger.py`** (`APIRouter(prefix="/ledger", tags=["ledger"])`). `GET /responses/{response_id}`, rate-limited, `Depends(get_current_user)`; `get_settings()` called directly (monkeypatchable, M25):
1. If not `ledger_route_enabled`, or the id does not match `RESPONSE_ID`: 404 `{"detail": "Response not found."}`, `Cache-Control: no-store`.
2. **Reviewer** (`user.role in LEDGER_READER_ROLES`): read the row by `response_id`; if missing and the id is a `turn-` id with an existing turn, return the no-record result of step 3 (`_unrecorded`); `record_security_event("ledger.reviewer_read", "success", connection=request, actor_role=user.role, subject=user.user_id, details={"route": route_template(request), "delivery": row.delivery if row else "none"})`; return the record with the chain fields and `shadowed_response_id`.
3. **Everyone else:** a `shadow-` id is 404 whether or not it exists (AC-3-6); `turn = db.get(TutorTurn, response_id)`; missing or `turn.user_id != user.user_id` is 404; if the row exists, `LedgerResponseRead(recorded=True, legacy_turn=False, record=...)` with the chain fields and `shadowed_response_id` None; otherwise `_unrecorded(response_id, turn)` returns `LedgerResponseRead(recorded=False, legacy_turn=turn.ledger_record_expected is None, unrecorded_reason=..., record=None)` (plan G "legacy turns marked no-verdict"; no write). The turn's own `ledger_record_expected` decides: null is a turn that an image keeping no ledger served, before Phase 3 or in a rollback window (`earlier_image`, `legacy_turn` true); false is a turn made while `TUTOR_LEDGER_ENABLED` was off (`ledger_disabled`); true with no record is a lost record, a plan L stop (`missing`). `ledger_started_at` decides nothing (8.1). The reviewer's no-record result uses the same function.
4. Every response carries `Cache-Control: no-store`.

**MOD `app/api/routes/spans.py`**
- Move the handler body into `_resolve_span(span_id, request, response, db)`, still calling this module's `get_settings` and `get_span_resolver` (Phase 2 monkeypatches keep working).
- Add `evidence_router = APIRouter(prefix="/evidence", tags=["evidence"])` with `GET /spans/{span_id}`, the same decorator stack and the same call. Both handlers use `limiter.shared_limit(..., scope="span-resolver")`, so the two paths share one `SPANS_RATE_LIMIT` window per client.
- Return `license_class="public"`.

**MOD `app/main.py`**
- Import `ledger` and `tutor`. `ROUTERS` becomes: …, `qa.router`, `spans.router`, `spans.evidence_router`, `assistant.router`, `tutor.router`, `ledger.router`, …
- Plus section 11.

### 7.14 MOD `app/core/authorization.py`
- Add `LEDGER_READER_ROLES = ("reviewer",)` (PD-12) and three policies:

```python
("GET", "/evidence/spans/{span_id}"): _p(PUBLIC, NONE, "Alias of /spans/{span_id} (plan 7.3): the same SPAN_RESOLVER_ROUTE_ENABLED flag, rate limit and D-31 rules; public license_class only."),
("POST", "/tutor/turns"): _p(PRINCIPAL, OWNER, "Two-pass tutor endpoint (plan 7.3). 404 outside development unless TWO_PASS_TUTOR is on, which settings refuse before the Phase 4 exit; returns the legacy contained answer and runs the two-pass pipeline in shadow. A thread_id in the body must be the caller's thread. Rate-limited."),
("GET", "/ledger/responses/{response_id}"): _p(PRINCIPAL, OWNER, "404 unless LEDGER_ROUTE_ENABLED. The turn's owner reads its legacy record (a pre-ledger turn reads as no-verdict); the reviewer role reads any record, shadow records included, and each such read is a security event. Any other role, admin included, reads only its own turns. A learner never sees a shadow record (AC-3-6)."),
```

- Regenerate `docs/security/authorization-matrix.md` with `python scripts/authorization_matrix.py`.

### 7.15 NEW `app/workers/response_ledger.py`
- Modelled on `workers/security_log.py`: verify, then log one JSON line `{"job": "response_ledger", "status", "records", "first_seq", "last_seq", "head_hash", "head_row", "problems", "duration_ms"}`. Exit 1 if the chain is broken or the job fails. `python -m app.workers.response_ledger [--expect-head SEQ:HASH]`.
- The worker also takes `--coverage-since ISO8601` (a `coverage` block in its line) and `--export PATH` (refused inside the application tree; an `exported` block), sharing `ledger.ledger_coverage` and `ledger.export_ledger` with the script, so the runbook's production steps run through the API's own Cloud SQL connector; its line adds `appended_during_check`. Exit 2 is a usage error.
- `--coverage-horizon-s N` sets the coverage horizon (7.16): a turn that expects a record counts as `unrecorded` only once it is older than the horizon, and as `pending` before that. The default is `ledger.coverage_horizon_s()`, `attempt_horizon_s` for the package and the ledger budget in force (360 s, 4.12); 0 counts every turn, for a check once traffic has stopped. A negative value is a usage error.
- `--restore PATH` first re-inserts an `--export` file into an empty ledger (`ledger.restore_ledger`: every line must extend the chain from the genesis with its exported seq, time and hashes, which are recomputed, and validate; one transaction; a non-empty ledger or a refused line writes nothing and exits 1, status `restore_refused`), then verifies as usual, so `--restore PATH --expect-head SEQ:HASH` proves the exported chain is back. `--export` and `--restore` together are a usage error.
- `--check-provenance` adds a `provenance` block (`ledger.ledger_provenance` for the configuration package in force, 4.12: F-2's audit until a provider prompt exists, DI-49). A problem in it logs the line at ERROR with status `provenance_mismatch` and exits 1; a broken chain still reads `broken`.

### 7.16 NEW `scripts/verify_ledger.py`

```
python scripts/verify_ledger.py [--database-url URL] [--report PATH] [--expect-head SEQ:HASH]
                                [--coverage-since ISO8601] [--coverage-horizon-s N] [--export PATH.jsonl]
                                [--check-provenance]
```

- Read-only; builds its own engine. The URL comes from `--database-url`, else `DATABASE_URL`; never printed.
- The report holds counts, head and problems, plus an optional `coverage` block (`ledger.ledger_coverage`): `since`, `turns_since` (tutor turns created since the time), and the turns with no record whose `response_id` equals the turn id, split by what each turn expected (`TutorTurn.ledger_record_expected`): `unrecorded` (it expected a record and was created before `settled_before`: a lost record, a plan L stop), `pending` (it expected a record and is newer), `not_expected_earlier_image` (an image that keeps no ledger created it) and `ledger_disabled` (created under the kill switch); `horizon_s` and `settled_before` (the check's start less the horizon); and `qa_records_since`. Coverage is report-only. A newer turn that expects a record and has none yet is `pending`, not lost: the turn commits first and its append runs after the commit, so a check during live traffic would otherwise count every append still running as a lost record. `--coverage-horizon-s` sets the horizon, as in 7.15.
- `--export` writes one JSON object per row (all columns) to a path outside the repository (refuses a path inside it); it is the step before a downgrade (conflict 22).
- `--check-provenance` adds the worker's `provenance` block for the shipped package; a problem sets status `provenance_mismatch`.
- Exit codes: 0 ok, 1 broken or a provenance mismatch, 2 usage or connection error.
- The script is for development, CI and local copies (a plain engine from the URL, no Cloud SQL connector); production uses the worker (7.15).

### 7.17 NEW `scripts/replay_tutor_plans.py` (the three-plan replay, plan F)

```
python scripts/replay_tutor_plans.py --write docs/evaluation/phase3/three_plan_replay_v1.json
python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
```

- **Fixture.** `apps/api/tests/data/score_floor_queries.json`: in_domain 174, off_topic 100, stopword_only 24 (298 public items), plus the regression items of `apps/api/tests/data/phase3_replay_regressions.json` (1, a sentence held by two overlapping spans; replayed in full even with a subset). It refuses any path under `lqs/` (like `calibrate_abstention._refuse_lqs`).
- **Configurations:** `governed_empty` with `p1-floor`; `all_public_approved` (a temporary `with_all_public_approved` manifest) with `bm25f-v1`; `all_public_approved` with `p1-floor`.
- **Per item:** `resolved = resolve_turns([], LearnerTurn("fixture-" + sha256(query)[:12], query), package=...)`; for each plan, `TwoPassPipeline(engine, settings).run(PipelineInput(..., delivery="shadow", response_id=f"shadow-{uuid5(...)}", shadowed_response_id=f"turn-{uuid5(...)}"), record=False)` (no database); record `decision`, `abstention_reason`, `claim_set_hash`, `span_set_sha256 = span_set_digest(locked.span_ids)` and `rendered_text_sha256`. Also the legacy Phase 2 path over the same lexical retrieval: `contain_answer` claims, bound = claims with at least one cited span.
- The report holds hashes and counts only, never query, claim or span text.

**Report shape**

```json
{"report": "qcai-three-plan-replay", "format_version": 1, "created_at": "...", "commit": "...",
 "evidence_class": "engineering replay on public-corpus fixtures; NOT E3 or LQ-1 evidence (plan Phase 3 H)",
 "public_corpus_only": true, "excluded_sources": ["private plane", "lqs/ (ULQS)", "learner records, tutor turns, ratings"],
 "fixture": {"path": "...", "sha256": "...", "items": 298}, "config_package": {"version": "2.0.0", "sha256": "..."},
 "tutor_pipeline": {"resolver": "...", "generator": "...", "renderer": "...", "prompt_hashes": {...}},
 "plans": ["concise", "stepwise", "socratic"],
 "configurations": [{"name": "...", "gate": "...", "corpus_version": "...", "index_version": "...", "items": 298,
   "answered": 0, "abstained": 0, "abstention_by_reason": {}, "claim_set_hash_equal": 298, "span_set_equal": 298,
   "rendered_text_distinct_among_answers": 0, "mismatches": [],
   "two_pass": {"proposed_claims": 0, "bound_claims": 0, "bound_claim_ratio": null},
   "phase2_legacy": {"answered": 0, "claims": 0, "bound": 0, "bound_claim_ratio": null},
   "stop": false, "items_digest": "sha256 of sorted (query_sha, decision, claim_set_hash, span_set_sha256) tuples"}],
 "result": "pass",
 "inputs": {"rule": "imported-repository-modules-sha256-lf-v1", "files": {"apps/api/app/...py": "<sha256 of its LF text>"}, "sha256": "..."}}
```

- `result`: `"pass"`, `"mismatch"` (any `claim_set_hash` or span set differing across plans) or `"stop"` (a non-null two-pass ratio below `tutor_pipeline.stop.phase2_bound_claim_ratio`; null never stops).
- **Exit codes:** `--write` 0 on pass, 1 on mismatch, 3 on stop, 4 when the working tree differs from HEAD (refused unless `--allow-dirty`); `--check` 1 if the record differs from a fresh run (ignoring `created_at` and `commit`), else as `--write`.
- **`inputs`** names the code the record replayed by content: every repository module the replay imported (under `apps/api/app/` and `scripts/`) with the sha256 of its text, CRLF read as LF, and the digest of that map (rule `imported-repository-modules-sha256-lf-v1`). The AC-3-2 record test recomputes each listed hash from the checkout, and `--check` compares the whole block with a fresh run.
- **`commit`** is informational: HEAD when `git status --porcelain` is empty, else HEAD + `-dirty`, the HEAD the record was written on. It does not identify the code; `inputs` does. `compute(commit_source=...)` takes another source, so a test can run the replay without starting a process. The report also has `answered_by_stratum` and `two_pass.merged_claims`; the `two_pass` counts are `bound_claim_ratio_terms`.
- **The committed record** (authoritative; any package change or replayed-module change needs a re-`--write`): governed_empty abstains on all 299 items (`no_quotable_evidence` or a retrieval reason); all-approved `bm25f-v1` answers 148 and `p1-floor` 130, where the legacy contained path answers 167 and 147; the other answerable items abstain with `no_whole_sentence` or `no_claims`, because their spans hold no whole document sentence that shares a content term with the question; 0 off-topic items answered; 0 mismatches; two-pass ratio 1.0 beside the Phase 2 legacy 1.0.

### 7.18 MOD `apps/api/app/services/store.py`
- No change. The pipeline hangs off `TeachingAssistantService`, so `rebuild_course_store()` clears it.

### 7.19 MOD `app/core/db.py` (the production database path: error classes, connect bound, keepalive)
- **`classify_pg8000_errors`**, a `handle_error` listener on every `Engine`: on the pg8000 dialect a server error that SQLAlchemy raises in a catch-all class (`ProgrammingError`, `InternalError` or `DatabaseError`) is re-raised as the PEP 249 class its SQLSTATE class names, psycopg's mapping (`_SQLSTATE_CLASSES`: 22 `DataError`; 23 `IntegrityError`; 08, 40, 53, 54, 55, 57 and 58 `OperationalError`). The driver error stays the wrapped `.orig`, so SQLSTATE checks (`ledger.sqlstate`, `main._sqlstate`) and disconnect handling are unchanged. Other drivers and disconnects are left alone.
- **pg8000's two interfaces raise different classes** (pg8000 1.31.6 here; the connector's `pg8000` extra resolves the version at build). Production connects through the Cloud SQL connector, whose pg8000 adapter calls `pg8000.dbapi.connect`; that interface raises every server error as a plain `DatabaseError`, 23505 included. Without the listener no `except IntegrityError` (the ledger's retry, `guest_sessions`, `public_handles`, `security_log`, the tutor route) fired in production, and no server error there was a `DataError` or an `OperationalError`. A `postgresql+pg8000://` URL, which CI's pg8000 leg uses, goes through the legacy `pg8000.connect`, which raises `IntegrityError` for 23505 and `ProgrammingError` for every other server error, so that leg alone does not reproduce production's classes (DI-46). With the listener both interfaces give psycopg's class for every mapped SQLSTATE class. A SQLSTATE class outside the map (a syntax error, 42601) keeps the class SQLAlchemy raised: `DatabaseError` on production's interface, `ProgrammingError` on the legacy one and on psycopg; no code catches either. `test_m1_*` runs production's interface on both PostgreSQL legs, through an engine built as `app.core.db` builds production's (`URL.create("postgresql+pg8000")` with a `pg8000.dbapi.connect` creator): the raw classes, the classes the listener gives, and the ledger retrying a real duplicate key.
- **`cloud_sql_creator`** is the engine's creator when `CLOUD_SQL_CONNECTION_NAME` is set: one pg8000 connection through the connector, run by **`bounded_connect`** on a daemon thread and given up after `CONNECT_TIMEOUT_S` (30 s; the connector bounds no part of a new connection) with `ConnectTimeout`, a pg8000 `OperationalError` that SQLAlchemy raises as `OperationalError`. At most `CONNECT_MAX_PENDING` (30: the pool's 20 connections and 10 overflow) connects run at once; waiting for a slot counts toward the bound. A connection that arrives after the caller gave up is closed and never reaches the pool. Each timeout logs `db.connect.timeout` (`timeout_s`, `slot_free`).
- **`enable_tcp_keepalive`**: `cloud_sql_creator` turns TCP keepalive on for each new connection's socket (pg8000's `Connection._usock`, the connector's TLS socket): `SO_KEEPALIVE`, and where the platform has them `TCP_KEEPIDLE` (`KEEPALIVE_IDLE_S`, 30 s), `TCP_KEEPINTVL` (`KEEPALIVE_INTERVAL_S`, 10 s), `TCP_KEEPCNT` (`KEEPALIVE_PROBES`, 3) and, on Linux, `TCP_USER_TIMEOUT` (`DEAD_PEER_BOUND_S`, 60 s, in milliseconds). A read whose peer is gone then ends within `DEAD_PEER_BOUND_S` of the connection's last traffic (4.12). A socket it cannot reach, or an option the kernel refuses, logs `db.connect.keepalive_unset` (`option`, `error`) and the connection is kept, without that bound. A server that keeps the connection up and never replies is not detected.
- `treat_dead_sockets_as_disconnects` (unchanged from `main`) lets the pre-ping reconnect when pg8000 reports a dead socket as a raw `OSError`.

### 7.20 MOD `app/schemas.py` (the API additions of 3.4, and a start-up refusal)
- The additions listed in 3.4.
- **`_ExcludeIfProbe`**: at import, a model with a `Field(exclude_if=...)` field must omit its None value from `model_dump()` and `model_dump(mode="json")`; otherwise `app.schemas` raises `RuntimeError` ("pydantic >= 2.12.4 is required ..."), so the API does not start. An older pydantic takes `exclude_if` as deprecated extra schema data and keeps the key, so production chat bodies would gain `"evidence": null` (conflict 28).

### 7.21 MOD `apps/api/requirements.txt`
- Adds the floor `pydantic>=2.12.4,<3` (a floor, not a pin; M21 measured the base): `Field(exclude_if)` keeps `"evidence"` out of production chat bodies (conflict 28), and 2.12.4 is the first release whose JSON schema treats such fields correctly (`test_the_chat_response_schemas_keep_every_field_in_openapi`).

### 7.22 MOD `app/api/routes/qa.py` and `app/services/qa_engine.py` (the `/qa/ask` ledger record and panel)
- `QAEngine.ask` prepares the answer's legacy ledger record when `TUTOR_LEDGER_ENABLED` (`legacy_delivery_for(response_id=f"qa-{uuid4()}", ..., surface="qa")`; a preparation failure becomes a `LegacyPreparationFailed`), and with `EVIDENCE_PANEL_ENABLED` sets `evidence` (4.13). The response body is unchanged outside development.
- `ask_question` calls `record_legacy_delivery` after `db.commit()`, so an answer whose commit fails is never an attempt; it never raises and never changes the response.

### 7.23 MOD `app/services/retention.py`
- A comment only: no retention rule touches `response_ledger` or `response_ledger_head` (PLAN-12.8 open, DI-45; the triggers refuse DELETE).

### 7.24 MOD `apps/api/alembic/env.py`
- With `CLOUD_SQL_CONNECTION_NAME` set and a PostgreSQL `DATABASE_URL`, migrations connect through the API's own engine (`app.core.db.engine`, the Cloud SQL connector, 7.19); otherwise `engine_from_config` with `NullPool` as before.

---

## 8. Database

### 8.1 ORM (`app/db_models.py`)

```python
class ResponseLedgerRecord(Base):
    # Append-only, hash-chained provenance record of every tutor response (plan 3.8, 7.5; R-22). No user id and no
    # learner text: the learner link is tutor_turns (user-keyed, erasable), so after erasure a row stays but is
    # unlinkable. No foreign key to any tutor table, so erasure never reaches it. Triggers refuse UPDATE, DELETE and
    # TRUNCATE (schema_upgrades); an insert must extend the chain.
    __tablename__ = "response_ledger"
    __table_args__ = (
        UniqueConstraint("response_id", name="uq_response_ledger_response_id"),
        CheckConstraint("delivery IN ('shadow', 'delivered', 'legacy')", name="ck_response_ledger_delivery"),
        CheckConstraint("decision IN ('answer', 'abstain')", name="ck_response_ledger_decision"),
        Index("ix_response_ledger_shadowed_response_id", "shadowed_response_id"),
        Index("ix_response_ledger_created_at", "created_at"),
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    response_id: Mapped[str] = mapped_column(String(64))
    delivery: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16))
    shadowed_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_schema: Mapped[str] = mapped_column(String(32))
    entry: Mapped[str] = mapped_column(Text)                 # canonical JSON of LedgerEntry (exact hashed bytes)
    entry_sha256: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # aware UTC, set in Python

class ResponseLedgerHead(Base):
    __tablename__ = "response_ledger_head"
    chain: Mapped[str] = mapped_column(String(32), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    record_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class TutorTurnIdempotency(Base):   # Idempotency-Key claims of POST /tutor/turns (7.13); user-keyed, so erasure covers it
    __tablename__ = "tutor_turn_idempotency"

# TutorTurn gains:
    ledger_record_expected: Mapped[bool | None]   # true: a Phase 3 image made it with the ledger on; false: kill switch;
                                                  # null: an image that keeps no ledger made it (before Phase 3, a rollback window)
```

`started_at` is informational: when the chain began, written by the first append (`ledger.ledger_started_at` takes the earlier of it and the first record's `created_at`). It decides nothing: whether a turn without a record is a lost record is the turn's own `ledger_record_expected`. The head triggers keep it unchanged; `run_schema_upgrades` adds the column to a head table made by an earlier build, where it stays null and `ledger_started_at` falls back to the first record. The Alembic revision creates it too (it had been applied nowhere).

The entry is TEXT holding the exact canonical bytes (no JSON round-trip differences between SQLite, psycopg and pg8000). No column name matches the erasure identity pattern `(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$`.

### 8.2 Triggers (`schema_upgrades.run_schema_upgrades`)

Created when the tables exist and checked on every start. On PostgreSQL they are re-created only when the catalogs do not already hold exactly these definitions, with the tables locked head first, the append's own order (`_postgres_guard`), so a start never deadlocks a live append; SQLite drops and re-creates its triggers on every start. No `%` in any statement (psycopg, pg8000).

**PostgreSQL**
- `response_ledger_append_only()` raises `'response_ledger is append-only: ' || TG_OP || ' refused'`. Triggers `response_ledger_append_only` (BEFORE UPDATE OR DELETE, FOR EACH ROW) and `response_ledger_no_truncate` (BEFORE TRUNCATE, FOR EACH STATEMENT).
- `response_ledger_links_to_chain()`, BEFORE INSERT FOR EACH ROW:
  ```sql
  DECLARE last_seq integer; last_hash text;
  BEGIN
    SELECT seq, record_hash INTO last_seq, last_hash FROM response_ledger ORDER BY seq DESC LIMIT 1;
    IF last_seq IS NULL THEN last_seq := 0; last_hash := repeat('0', 64); END IF;
    IF NEW.seq <> last_seq + 1 OR NEW.prev_hash <> last_hash THEN
      RAISE EXCEPTION USING MESSAGE = 'response_ledger appends must extend the chain';
    END IF;
    RETURN NEW;
  END
  ```
- `response_ledger_head_forward_only()`: first `IF TG_OP <> 'UPDATE' THEN RAISE ...` (DELETE and statement-level TRUNCATE, where NEW/OLD are NULL); an UPDATE is allowed only if `NEW.chain = OLD.chain AND NEW.seq = OLD.seq + 1 AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at AND EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash)`; otherwise it raises `'response_ledger_head moves forward only: ' || TG_OP || ' refused'`. Triggers `response_ledger_head_forward_only` (BEFORE UPDATE OR DELETE FOR EACH ROW) and `response_ledger_head_no_truncate` (BEFORE TRUNCATE FOR EACH STATEMENT).

**SQLite** (each `DROP TRIGGER IF EXISTS` first)
- `response_ledger_no_update`, `response_ledger_no_delete`: `RAISE(ABORT, ...)`.
- `response_ledger_links_to_chain`: BEFORE INSERT `WHEN NEW.seq != (SELECT COALESCE(MAX(seq), 0) + 1 FROM response_ledger) OR NEW.prev_hash != COALESCE((SELECT record_hash FROM response_ledger ORDER BY seq DESC LIMIT 1), '<64 zeros>')`.
- `response_ledger_head_forward_only`: BEFORE UPDATE `WHEN NEW.seq != OLD.seq + 1 OR NEW.chain != OLD.chain OR NEW.started_at IS NOT OLD.started_at OR NOT EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash)`.
- `response_ledger_head_no_delete`.

### 8.3 Alembic (`apps/api/alembic/versions/20261119_phase3_response_ledger.py`)

```python
revision = "20261119_phase3_response_ledger"; down_revision = "20261119_phase2_corpus_spans"
def upgrade():  create the three tables exactly as 8.1 (response_ledger, response_ledger_head, tutor_turn_idempotency;
                same constraint and index names; seq autoincrement=False; tutor_turn_idempotency sqlite_autoincrement),
                and add tutor_turns.ledger_record_expected
def downgrade():
    allow = context.get_x_argument(as_dictionary=True).get("allow_ledger_drop") == "true"
    rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM response_ledger")).scalar() or 0
    if rows and not allow:
        raise RuntimeError(f"response_ledger holds {rows} rows (append-only evidence, R-22); export first with "
                           "python -m app.workers.response_ledger --export <path outside the application tree>, then: "
                           "alembic -x allow_ledger_drop=true downgrade 20261119_phase2_corpus_spans")
        # the worker (in the image, Cloud SQL connector) and an absolute target, never -1
    if op.get_bind().dialect.name == "postgresql":  drop the 5 triggers and 3 functions (IF EXISTS)
    drop tutor_turn_idempotency, then tutor_turns.ledger_record_expected, then the ledger indexes,
    response_ledger_head and response_ledger
```

- Docstring: additive and reversible (expand step, plan 13.3); triggers come from `schema_upgrades`; the chain still cannot build an empty database (the strict xfail stays).
- `ledger.SCHEMA_REVISION` must equal this revision; a test parses `apps/api/alembic/versions/*.py` and asserts it is the single head.

### 8.4 Erasure and retention
- **No code change.** Not user-keyed and no foreign keys, so `user_keyed_tables()` and `_covered_tables()` exclude the tables and erasure never touches them.
- **Retention.** No rule in Phase 3: plan 12.8 leaves the retention period an OPEN owner decision (DI-45). The ledger holds no learner identifier; after erasure of `tutor_turns`/`tutor_messages` its turn and message ids are dangling. Residual: platform access logs of `GET /ledger/responses/{turn id}` and record timestamps could support re-linking outside the database; no application log carries a turn, thread or message id (0.1).
- **Tests** (13.1): `test_ac_3_4_erasure_leaves_ledger_rows_unlinkable` and `test_the_ledger_is_outside_erasure_and_guarded_at_start_up`.
- **Machine-readable retention state.** Package v2 `owner_decisions.PLAN-12.8` = `{state: open, behaviour: retain}` and `tutor_pipeline.ledger.retention` = `retain`; the loader refuses anything else while no retention job exists. `test_c4_no_retention_or_erasure_job_deletes_a_ledger_row` runs `run_retention_cleanup` with a cutoff in 2100 over old ledger rows.
- **Q&A records** carry a random `qa-` id stored nowhere else, which names no learner. They are not unlinkable while the asker's `qa_interactions` row exists: it holds the same answer (the record's `rendered_text_sha256` is its sha256), the same cited spans and a close time. Erasure or guest retention deletes the row, and the record then cannot be tied to anyone.
- **`tutor_turn_idempotency`** is user-keyed: erasure deletes it and guest retention covers it like every user-keyed table.

---

## 9. Routes and request-path behaviour

| Path | Outside development (defaults) | Development |
|---|---|---|
| `POST /assistant/chat` | Body and keys identical to today (no `evidence` key; conflict 28), plus a legacy ledger record per turn (`TUTOR_LEDGER_ENABLED`, ≤ append budget). No shadow. | Legacy answer, `evidence` panel, legacy record, and the shadow pipeline as a background task (a shadow record). |
| `POST /tutor/turns` | 404 `{"detail": "Not Found"}` after authentication (anonymous 401; an invalid body 422), whatever `Idempotency-Key` holds | Like `/assistant/chat`, plus `delivery: "legacy"`. Honours `presentation_plan`. `extra="forbid"`. An optional `Idempotency-Key` (7.13): a retry returns the first turn (`Idempotent-Replayed: true`); another body with the key 422; a retry while the first runs 409, until its lease passes. Shares `/assistant/chat`'s rate-limit window. |
| `GET /ledger/responses/{id}` | 404 | Owner: own legacy record (no chain fields), or `legacy_turn` no-verdict. Reviewer: any record with chain fields, logged. Shadow ids: 404 to everyone else, admin included. |
| `GET /evidence/spans/{id}` | 404 (`SPAN_RESOLVER_ROUTE_ENABLED` false) | Identical to `/spans/{id}`, plus `license_class` |
| `GET /assistant/threads/{id}` | Unchanged | Unchanged (shadow writes no message) |
| `POST /qa/ask`, `GET /qa/history` | Response bytes unchanged. Each `/qa/ask` delivery is ledgered like a tutor turn (`TUTOR_LEDGER_ENABLED`, bounded, fail-open) under a random `qa-` id that names no learner (matchable to the asker's Q&A row while it exists); the plan I SLI is reported per surface (`legacy_by_surface`). | The same, plus the `evidence` panel on the answer |

**Rate limits.** Learner-facing tests use a fresh `demo()` principal and a distinct `x-forwarded-for` per call (8/minute limits).

**Connection note.** uvicorn processes one request at a time per HTTP/1.1 connection and the ASGI cycle ends after background tasks, so a keep-alive connection's next request can wait for the shadow (bounded by the shadow budget, `shadow_budget_ms`: the package's 2000 ms unless `TWO_PASS_SHADOW_BUDGET_MS` overrides it); shadow tasks also share the AnyIO thread pool with sync routes. Both matter for DI-32.

---

## 10. (reserved; numbering kept aligned with the order of work)

---

## 11. Start-up, `/ready`, logs and SLIs

### 11.1 Start-up order (`main.py`)
1. `require_guest_token_secret`.
2. `_check_corpus_before_any_table()`, as in Phase 2, plus, after `get_config_package(settings)`: if `package.tutor_pipeline`, `problems = check_tutor_pipeline_package(package, structural=False)`; on problems a governed build with `TWO_PASS_TUTOR != "off"` raises `ConfigPackageError("tutor pipeline: ...")`; otherwise set `tutor_pipeline.shadow.PIPELINE_UNAVAILABLE_REASON` and log `tutor.two_pass.unavailable` (WARNING, logger `qcai.tutor`). With no problems the reason is cleared. `TWO_PASS_TUTOR=on` has already failed in `Settings`.
3. `create_all` (the new tables) and `run_schema_upgrades` (the new columns, each in its own short transaction, then the new triggers, re-created only when they differ from the catalogs, the ledger's tables locked head first). No ledger row and no chain head is written at start-up.
4. `_record_configuration_overrides()` adds `("two_pass_tutor_shadow", settings.two_pass_tutor == "shadow")`, `("tutor_ledger_disabled", not settings.tutor_ledger_enabled)`, `("ledger_route_enabled", settings.ledger_route_enabled)`, `("evidence_panel_enabled", settings.evidence_panel_enabled)`, `("shadow_budget_overridden", ...)` and `("ledger_append_budget_overridden", ...)`, the last two set when either budget override is set. Keys appear only when active, so the existing exact-details tests are unchanged.
5. The single `qcai.api` start-up line stays the only `qcai.api` structured record (M23).

### 11.2 `/ready`
- **`_build_fields()` additions** (deterministic per process, no DB read):

```json
"two_pass_tutor": "off|shadow", "two_pass_tutor_setting": "off|shadow|on", "phase4_exit_passed": false,
"tutor_pipeline": {"version": "two-pass-v1", "resolver": "thread-resolver-v1", "generator": "extractive-d19-v1",
                   "renderer": "template-renderer-v1", "presentation_plans": ["concise","stepwise","socratic"],
                   "max_regenerations": 2, "schemas_sha256": "<sha256 of the sorted schema pins>",
                   "prompt_hashes": {"resolver": "…", "evidential": "…", "pedagogical": "…"},
                   "subset_check": "segment-exact-whitespace-v3",
                   "legacy": {"pipeline_version": "legacy-contained-v1", "generator_id": "contained-answers-v1",
                              "generator_model_id": "extractive-lexically-screened", "containment_rule_hash": "…"},
                   "budgets": {"shadow_ms": 2000, "ledger_append_ms": 1500, "overridden": []}, "available": true},
"tutor_ledger_enabled": true, "ledger_route_enabled": true, "evidence_panel_enabled": true, "tutor_turns_route_enabled": true
```

  `tutor_pipeline` is `null` with a v1 package. `legacy` is the package's `tutor_pipeline.legacy` pins, which every legacy ledger record stamps (the provenance audit's reference values, DI-49).
- **`readiness_check` (200 path) adds** `"ledger": {"chain": "tutor-responses", "status": "ok"}` when the head is readable, wrapped in try/except (`"status": "unavailable"`); never changes readiness (the ledger fails open). `/ready` is public, so it never reports the head's sequence number, which is the all-time count of tutor responses; the head is in the verification job's log line and in every `tutor.ledger.appended` line.
- **`slis` adds two blocks:**

```json
"tutor_ledger": {"attempted": {"legacy": 0}, "appended": {"legacy": 0}, "duplicates": 0, "failed": {"legacy": 0},
                 "conflicts": 0, "legacy_coverage_rate": null, "legacy_by_surface": {"tutor": {...}, "qa": {...}},
                 "delivered": {"decisions": {"answer": 0, "abstain": 0}, "abstention_rate": null,
                               "abstention_by_reason": {}, "by_surface": {"tutor": {...}, "qa": {...}}},
                 "non_public_spans_excluded": {"legacy": 0, "qa": 0}, "write_stop": false},
"two_pass_shadow": {"scheduled": 0, "phase2_bound_claim_ratio_baseline": 1.0}
```

  The public blocks carry nothing that changes with a shadow run's outcome, since on a quiet instance a learner comparing `/ready` before and after a turn would otherwise read the shadow's outcome for that turn (AC-3-6): `two_pass_shadow` keeps `scheduled` (a turn schedules a run whatever its outcome) and the baseline; `tutor_ledger` keeps the legacy deliveries (a shadow record is a shadow output) and the legacy and Q&A license-gate counts. `LedgerMetrics.public_snapshot`, `TwoPassMetrics.public_snapshot` and `LicenseMetrics.public_snapshot` build them; `metrics.detail_snapshot` and the per-class `snapshot()` keep every counter in process (decisions, reasons, completion, failures by step, claim counts, the ratio and its stop), and each run's log lines (11.4) carry them for the log-based SLIs.

### 11.3 Metrics (`tutor_pipeline/metrics.py`)
- `TwoPassMetrics` and `LedgerMetrics` are locked counter classes, like `RetrievalMetrics`, with the `snapshot()` shapes above.
- `delivered`: every legacy delivery's decision and abstention reason, counted at the attempt whatever the append then does, per surface and in all, with `abstention_rate` (null with no delivery). Public: a legacy decision is what the learner already received.
- `legacy_coverage_rate = appended.legacy / attempted.legacy` (null when attempted is 0; `attempted` counts every legacy delivery that committed, including those whose preparation failed, counted by `record_legacy_delivery` after the commit: a request that rolls back is no attempt).
- `write_stop = failed.legacy + failed.shadow + conflicts > 0` in process (plan L "a ledger write fails"); the public block's `write_stop` counts legacy failures and legacy conflicts only.
- `bound_claim_ratio = bound / proposed`, null when proposed is 0; `bound_claim_ratio_stop = ratio is not None and ratio < baseline` (baseline from the package). Each run adds `contracts.bound_claim_ratio_terms(counts)`: claims dropped as `budget_exceeded` (bind never ran) are in neither term, so a latency event never trips the binding stop; `merged` and `duplicate` claims passed every binding check and are in both, so two claim plans that lock one claim set give one ratio whatever the order of their claims.

### 11.4 Structured log events (logger `qcai.tutor`; counts, hashes and enumerations only; no question, claim or rendered text; no response, turn, thread or message id)

| Event | Fields | Severity |
|---|---|---|
| `tutor.ledger.attempted` | `delivery` (`legacy`), `decision`, `abstention_reason`, `attempt`; `surface: qa` on a Q&A answer | INFO (after the commit, before the append) |
| `tutor.ledger.appended` | `delivery`, `seq`, `record_hash`, `duplicate`; `attempt` on a legacy line; `surface: qa` on a Q&A record | INFO (the off-DB chain copy; a legacy attempt's terminal line) |
| `tutor.ledger.append_failed` | `delivery`, `stage`, `error` (class); `attempt` on a legacy line; `surface: qa` on a Q&A record | ERROR, a stop condition (plan L); a legacy attempt's terminal line |
| `tutor.ledger.append_deferred` | `delivery`, `budget_ms`, `attempt`; `surface: qa` on a Q&A record (conflict 29) | WARNING (not terminal: the attempt's terminal line follows) |
| `tutor.evidence.non_public_excluded` | `surface` (`two_pass`, `legacy`, `qa`) | WARNING (an upstream guard failed) |
| `tutor.ledger.conflict` | `delivery` | ERROR |
| `tutor.two_pass.shadow` | `decision`, `reason`, `proposed`, `bound` (raw counts), `ratio_proposed`, `ratio_bound` (the plan L ratio terms, `contracts.bound_claim_ratio_terms`), `dropped`, `attempts`, `plan_id`, `gate`, `latency_ms`, `seq` | INFO |
| `tutor.two_pass.shadow_failed` | `step`, `error` | ERROR |
| `tutor.two_pass.render_failed` | `step` (`render` or `subset_check`), `render_attempt`, `error` (class): a render attempt raised | ERROR (the run goes on; every attempt raising abstains with `render_failed`) |
| `tutor.two_pass.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms` | WARNING |
| `tutor.two_pass.on_downgraded` | — | WARNING (once per process) |
| `tutor.two_pass.unavailable` | `reason` | WARNING |
| Security event `ledger.reviewer_read` | `route`, `delivery` (actor role; subject digest) | success |
| Job `response_ledger` | see 7.15 | INFO, or ERROR when broken or on a provenance mismatch |
| `db.connect.timeout` (logger `qcai.db`) | `timeout_s`, `slot_free`: a new Cloud SQL connection outlived `CONNECT_TIMEOUT_S`, or no connect slot came free | WARNING |
| `db.connect.keepalive_unset` (logger `qcai.db`) | `option`, `error`: a new Cloud SQL connection's socket could not be reached (`no_socket`) or refused a keepalive option; the connection is kept without that bound (7.19) | WARNING |

---

## 12. Frontend (`apps/frontend`, E5)

| File | Change |
|---|---|
| `src/lib/types.ts` | `export type EvidencePanelPayload = { panel_schema: "evidence-panel-v1"; decision: "answer" \| "abstain"; labels: Array<"lexically_screened">; degraded: Array<"extractive_only" \| "retrieval_fallback" \| "citations_provisional">; spans: Array<{ span_id: string; label: string; resolvable: boolean }>; verdict: "no-verdict" };` and `AssistantChatResponse.evidence?: EvidencePanelPayload \| null`. |
| NEW `src/lib/evidence-panel.ts` | Pure module, `import type` only. Exports `DECISION_TEXT`, `LABEL_TEXT`, `DEGRADED_TEXT`, `VERDICT_TEXT`, `spanHref(spanId) = \`/api/backend/evidence/spans/${encodeURIComponent(spanId)}\`` and `evidencePanelView(payload) → { decision: string; labels: string[]; degraded: string[]; verdict: string; spans: Array<{ key: string; label: string; href: string \| null }> }`. No "grounded"; no `qcai_`/`qcai-` literal; no storage. |
| NEW `src/components/evidence-panel.tsx` | `export function EvidencePanel({ evidence }: { evidence: EvidencePanelPayload })`: `<div role="group" aria-label="Evidence for this answer" className="assistant-evidence-panel">` (a group, so N answers make no N region landmarks of one name) with the decision line, label badges, degraded notes, the verdict line, and a span list: "Passage {n}: {label}", an underlined accent-coloured `<a rel="nofollow">` when `href`, else text. |
| MOD `src/components/teaching-assistant-chat.tsx` | `ChatBubble.evidence?: AssistantChatResponse["evidence"]`; the assistant bubble gets `evidence: response.evidence ?? null`; render `{message.evidence ? <EvidencePanel evidence={message.evidence} /> : null}` after the citation list. Stored history bubbles have none. |
| MOD `src/app/globals.css` | `.assistant-evidence-panel` styles: links and labels at least 4.5:1 and a 3 px accent focus outline on the chat bubble in both themes; the opt-in light theme keeps the compose field readable. |
| MOD `src/lib/guest-session.ts` | `PUBLIC_API_ROUTE_PATTERNS` holds `/^\/spans\/span-[0-9a-f]{64}$/` and `/^\/evidence\/spans\/span-[0-9a-f]{64}$/`: the proxy (`app/api/backend/[...path]/route.ts`) does not resolve or mint a guest session for a well-formed span link, since the API reads no credential on the span routes. Malformed ids and every other route still require a session. |
| MOD `src/components/qa-panel.tsx` | Renders `<EvidencePanel>` under a Q&A answer only when the API sent `evidence` (development by default). |
| MOD `src/lib/privacy-disclosures.ts` | A `RETENTION_SCHEDULE` row (accurate disclosure: the ledger runs in production), data class "Tutor response ledger". Stored: for each tutor answer and each lesson Q&A answer, the passages the search matched with their match scores and positions, the approved passages quoted and the quotations, the decision and version stamps; for the internal two-step check, the ids of the tutor messages the question was taken from; a tutor record is linked to the turn by a random id; a Q&A record names no one but can be matched to the learner's Q&A history while it is kept; no name, email, account id or question text. Retention: "Kept as an audit record; the retention period is an open owner decision." Trigger: deleting the account deletes the tutor turns and the Q&A history, so the records can no longer be tied to the learner; for a guest, automatic retention cleanup does the same for history older than one year; records cannot be edited or deleted. `tests/evidence-panel.integration.test.ts` pins the wording. |

**Copy (fixed, conservative):** decision `answer`: "Quoted word for word from approved course sources"; `abstain`: "No answer: no approved course passage matched this question closely enough" (what a floor miss means; it claims no coverage fact); `lexically_screened`: "Lexically screened: matched on words, not checked for meaning"; `extractive_only`: "Explanations are switched off; only quotations are shown"; `retrieval_fallback`: "Search ran in a reduced mode"; `citations_provisional`: "Citations are provisional"; `no-verdict`: "Not yet verified".

**Production.** The API sends no `evidence` key outside development, so no panel renders. Two frontend changes ship to production. One is the privacy row. The other is the proxy's public route patterns (`guest-session.ts`): an unauthenticated request for `/spans/span-<64 hex>` or `/evidence/spans/span-<64 hex>` does not resolve or mint a guest session, and the API answers 404 on both paths outside development. That is more conservative, never a new capability.

---

## 13. Tests

### 13.1 NEW `apps/api/tests/test_phase3_acceptance.py`

**Helpers and fakes**
- Copy the Phase 2 helpers (`settings_for`, `store_for` with `dev`, `governed_empty`, `all_public_approved`, `demo`, `anonymous`, `fresh_sessions`, `load_script`) rather than importing a test module.
- Fakes in NEW `apps/api/tests/tutor_fakes.py` (pytest's prepend import mode puts `apps/api/tests` on `sys.path`; check on the first run, inline if the import fails): `ScriptedGenerator(claims_by_call)` (unbound, outside-bundle, invented, non-verbatim, truncated-sentence or cross-span claims); `SpyGenerator(inner)`; `FaultyRenderer(inner, schedule, rng)`; `FailingLedger`.
- **Isolation rule (M17).** Concurrency, tamper and trigger tests use only `fresh_database_url` (`create_all`, `run_schema_upgrades`, `sessionmaker`), never the shared StaticPool session DB.
- **Guard-lifting helper** `_guards_lifted(engine)`: PostgreSQL `ALTER TABLE ... DISABLE/ENABLE TRIGGER USER` on both tables; SQLite drops the five triggers, then `run_schema_upgrades` restores them.
- **Header subset** for equality: `content-type`, `cache-control`, `x-assistant-provider`, `x-assistant-model` (M18).
- **No skips.** Dialect-specific assertions branch on `engine.dialect.name`.

**AC-3-1**
1. `test_ac_3_1_the_retrieval_request_and_evidential_envelope_hold_only_allowlisted_fields`: `set(RetrievalRequest.model_fields) == {"text", "lesson_slug", "corpus_version"}`; `EvidentialEnvelope` and `ResolvedQuestion` equal their documented sets; parametrised over `LEARNER_STATE_FIELDS`, adding the field to each raises `ValidationError`; `ResolvedQuestion(contains_learner_state=True)` raises.
2. `test_ac_3_1_the_evidential_pass_takes_no_learner_input_and_imports_no_learner_module`: signature allowlist over `build_request`, `retrieve`, `RetrievalEngine.evidence`, `build_envelope`, `ExtractiveD19Generator.propose`, `bind`, `lock`, `check_subset`; AST import scan of every `tutor_pipeline/*.py` and `claim_gate.py`; no evidential function has a `presentation` parameter; `TemplateRenderer.render` is the only function accepting `PresentationPlan`.
3. `test_ac_3_1_what_the_evidential_pass_receives_holds_zero_learner_state_under_three_learner_contexts`: three demo learners seeded with mastery 0.1/0.5/0.9, a note, a quiz attempt, Q&A history and a profile `focus_area` holding a unique `MARKER-<uuid>`; requests to `/assistant/chat` carry `page_path` and `history` markers; the orchestrator is monkeypatched to a `TeachingAssistantService` subclass whose `pipeline` uses `SpyGenerator(ExtractiveD19Generator)`; `retrieve` (called through its module attribute) and `RetrievalEngine.search` (the legacy path) are wrapped to capture inputs; four questions, one off-topic. The captured JSON at any depth has no `LEARNER_STATE_FIELDS` key and no marker. Per learner and question the fixture (`observe_three_learners`) records the retrieval call (the request and `top_k`), the envelopes the generator was sent, the `ClaimPlan`s it returned and the whole shadow record but its ids (`learner_independent`): the EvidenceBundle with every span field, the sufficiency, the threshold version, floor and margin; the locked claims and `claim_set_hash`; the decision, the abstention reason, the counts and the presentation. All are identical across the learners: plan 7.8 invariant 1, "identical EvidenceBundle, ClaimPlan and abstain decision", and 12.4(c), "retrieval query, top-k and abstention threshold are identical across mastery levels". `learner_independent` keeps every field of the shadow record but `response_id`, `shadowed_response_id`, each claim's `response_id` and `resolved_question.source_turn_ids`; `test_j2_*` makes the ClaimPlan and the threshold version learner-dependent, and `test_k1_*` the abstention reason, the counts, the floor, the margin, the sufficiency score and `top_k`, each in turn, and each fails the fixture.
4. `test_ac_3_1_post_tutor_turns_refuses_learner_state_fields`: `page_path`, `history`, `mastery`, `user_id` in the body each give 422.

**AC-3-2**
5. `test_ac_3_2_three_presentation_plans_give_the_same_claim_set_hash_and_span_set`: over `dev`, `governed_empty`, `all_public_approved` and both gates; 40 in-domain and 10 off-topic queries, one run per plan (`record=False`); equal `claim_set_hash` and `span_ids`; `plan_id` differs; for answers the three rendered texts are pairwise distinct; governed_empty abstains everywhere with equal hashes.
6. `test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1`: `replay_tutor_plans.compute(subset=60)`; `result == "pass"`, `mismatches == []`, `evidence_class` contains "NOT E3 or LQ-1", `public_corpus_only` true; an `lqs/` path is refused; the report contains no fixture query text.

**AC-3-3**
7. `test_ac_3_3_every_factual_sentence_of_a_rendered_response_maps_to_a_locked_claim`: the real renderer, 3 plans, locked sets from 50 dev queries; `check_subset` passes on the first attempt; `missing_claims == 0`; every claim segment maps and every citation lies in the locked span ids; rendered claim text equals the locked (verbatim) text.
8. `test_ac_3_3_property_an_unmapped_sentence_regenerates_at_most_twice_then_abstains`: `rng = random.Random(20261119)`, 300 trials, random locked sets from dev spans; `FaultyRenderer` injects per scheduled attempt one of the 12 `tutor_fakes.FAULT_MODES`: an invented sentence; a claim with a digit changed; a sentence from a span outside the set; a fact in a connective; an extra citation; a citation on the wrong claim; a duplicate claim; text not matching the segments; a non-contiguous line order; every claim dropped; every citation dropped; a declared citation no segment displays. Every mode is placed as itself at least once. Schedule: a random boolean list of length 3. **Property:** decision `answer` iff some attempt ≤ 3 is clean; `render_attempts` equals the first clean attempt (or 3); an answer's rendered response passes `check_subset`; an abstention has reason `subset_check_failed` and `rendered is None`.
9. `test_ac_3_3_a_renderer_that_adds_a_claim_a_citation_or_a_fact_in_a_connective_is_caught`: each plan J failure mode, deterministic, on a several-claim answer (at least two claims on two spans and two claim lines); the fault is placed as itself on every attempt (`FaultyRenderer(exact=True)`), and each subset check raises the mode's own problem code (`tutor_fakes.FAULT_SIGNATURES`); every exact injection asserts what it placed.
10. `test_ac_3_3_the_overlap_gate_is_gone_and_claims_are_never_rebound`: `claim_gate` has no `ClaimGate` or `evidence_digest`; a claim verbatim from span A citing span B is dropped `not_verbatim`, not rebound; a truncated sentence of a cited span (a qualifying clause removed) is dropped `not_verbatim`; a cited span outside the bundle is `outside_bundle`; an unbound claim is `unbound`; a forged content hash is `unresolvable`.

**AC-3-4**
11. `test_ac_3_4_every_delivered_tutor_response_has_a_ledger_record_and_the_chain_verifies`: 6 `/assistant/chat` and 3 `/tutor/turns` calls (answers and abstentions); each turn has a record with `response_id == turn_id`, delivery `legacy`, decision equal to the response's, `span_ids` equal to the sorted citation span ids, `rendered_text_sha256 == sha256(answer)`, claim texts equal to the response claims, and `retrieval.evidence_scope == "retrieved"` with scores; each turn has exactly one shadow record (`shadowed_response_id == turn_id`); `verify_response_ledger(session db).ok`.
12. `test_ac_3_4_the_pipeline_refuses_delivered_mode_before_the_phase_4_exit`: `PipelineInput(delivery="delivered")` (constructed bypassing the Literal via `model_construct`-style dataclass replace) makes `run` raise `DeliveryNotImplemented` before any retrieval or append; no `delivered` row exists after the whole module; a `LedgerEntry(delivery="delivered")` is refused by its validator; with `FailingLedger` a shadow run propagates to `run_shadow`, which counts `failed["ledger"]`.
13. `test_ac_3_4_ledger_tamper_is_detected` (isolated DB), parametrised: an edited entry; an edited `record_hash` column; an edited `decision` column; a middle row deleted; the tail truncated; the head forged with the tail truncated and `expected_head` taken from the worker log line; two rows' seq swapped; an unknown `entry_schema`. Each yields its problem message; `scripts/verify_ledger.py` exits 1 on each; a clean chain exits 0 and the worker exits 0.
14. `test_ac_3_4_update_delete_and_truncate_are_refused_and_the_head_moves_forward_only` (isolated DB): raw UPDATE and DELETE raise `DBAPIError` with "append-only"; on PostgreSQL TRUNCATE of either table raises; a raw INSERT with the wrong `prev_hash` or seq raises; a head rewind, a head delete, or a head pointing at a non-existent record raises.
15. `test_ac_3_4_appends_are_idempotent_on_response_id_and_a_changed_entry_is_refused`.
16. `test_ac_3_4_two_concurrent_appends_never_fork_the_chain` (isolated DB, both dialects): `threading.Barrier(2)` gives seq {1, 2} and verify ok; then 4 threads × 10 in the same database give `(42, 1, 42)` and ok (generous budget for the test).
17. `test_ac_3_4_ledger_rows_hold_no_learner_identifier_or_learner_text`: scan every entry for demo user ids, emails, marker text in questions, pages and history; no user-like columns; `resolved_question` has no `text`; captured `qcai.tutor` log records carry no response, turn, thread or message id.
18. `test_ac_3_4_erasure_leaves_ledger_rows_unlinkable`: after `erase_user`, rows remain and verify passes; `GET /ledger/responses/{turn_id}` by the same principal returns 404.

**AC-3-5**
19. `test_ac_3_5_a_follow_up_in_thread_a_references_only_thread_a_turns`: the same learner opens thread A ("What is QUBO optimization in logistics?"), then thread B ("Explain routing depth under hardware constraints"), then posts "Why does it matter?" in A; another learner posts in thread C meanwhile; the follow-up's shadow record has `resolved_question.source_turn_ids == (A1.id, A3.id)`, both in A's user message ids (via `GET /assistant/threads/A`); `resolve_thread` text equals `"What is QUBO optimization in logistics?\nWhy does it matter?"` and contains no thread-B text.
20. `test_ac_3_5_the_resolver_reads_only_the_learners_own_user_turns`: assistant messages and client `history` never contribute; a `current_message_id` from another thread, or an assistant message, raises `ResolverInputError`.
21. `test_ac_3_5_the_resolver_is_deterministic_and_not_a_word_count_rule`: "How does QUBO routing work under noise?" is standalone; "Why?" and "And for finance?" are follow-ups; no anchor in the last 4 user messages → standalone; repeated runs equal; the prompt hash equals the package pin.

**AC-3-6**
22. `test_ac_3_6_settings_refuse_two_pass_tutor_on_before_the_phase_4_exit`: `Settings(two_pass_tutor="on")` raises in development and production and names `phase4_exit_passed`; a start-up subprocess with `TWO_PASS_TUTOR=on` exits non-zero before any table exists; `Settings(environment="production").two_pass_tutor == "off"`, `Settings().two_pass_tutor == "shadow"`.
23. `test_ac_3_6_in_shadow_the_learner_response_is_byte_identical_to_the_legacy_contained_answer_and_a_shadow_record_exists`: 8 questions (in-domain, off-topic, follow-up), each in a fresh thread, as fresh principals, with orchestrators in modes `off` and `shadow`; `ledger_canonical(response.json() minus thread_id and turn_id)` equal across modes; the header subset equal; stored assistant `TutorMessage.content` and `QAInteraction.answer` equal `response.answer`; `tutor_messages`, `tutor_turns`, `qa_interactions` grow identically; only the shadow-mode turn has a shadow record; the renderer's lead and question template strings appear in no learner response, thread detail or Q&A history.
24. `test_ac_3_6_a_learner_never_reads_a_shadow_record_and_a_reviewer_read_is_logged`: the owner gets 404 on `GET /ledger/responses/{shadow id}` (equal to the missing-id body) and 200 for their own turn with `verdict == "no-verdict"` and no chain fields; another learner gets 404 on the turn id; a demo `reviewer` gets 200 on the shadow id with `shadowed_response_id`, and a `ledger.reviewer_read` event exists; a guest owner 200, a guest non-owner 404.
25. `test_ac_3_6_on_forced_past_settings_still_runs_shadow_only`: a temporary package directory (a copy of `v2.json` with `schemas/` copied beside it) with `phase4_exit_passed: true`, evidence `"test-only"` and a matching sidecar; `Settings(two_pass_tutor="on", config_package_path=...)` in development; the learner response equals that of `off`; the only two-pass record has delivery `shadow`; no `delivered` record exists; `tutor.two_pass.on_downgraded` is logged.
26. `test_ac_3_6_the_tutor_turns_route_is_404_outside_development`: production settings via `monkeypatch.setattr(tutor_route, "get_settings", ...)` (M25) give 404 `{"detail": "Not Found"}` and no turn, message or ledger row is written; anonymous callers get 401.
27. `test_ac_3_6_flag_combinations_never_deliver_two_pass_output` (plan 13.2): every combination of environment × `TWO_PASS_TUTOR` (None/off/shadow/on) × `TUTOR_LEDGER_ENABLED` × `EVIDENCE_PANEL_ENABLED` × `LEDGER_ROUTE_ENABLED` constructs `Settings`: either it raises (`on` only) or `effective_mode ∈ {"off", "shadow"}` and `tutor_turns_route_enabled` is false outside development. Then one representative orchestrator per effective mode runs a chat with `TwoPassPipeline.run` patched to record arguments: no call has `delivery != "shadow"`; an AST scan finds no `delivery="delivered"` literal in `app/`.

**Plan L / I / G / H, task 3.8, freeze**
28. `test_plan_l_a_shadow_or_ledger_failure_never_changes_the_learner_response_and_is_counted`: parametrised: the pipeline raises; the shadow append raises; the budget is exceeded (a slow fake generator, `TWO_PASS_SHADOW_BUDGET_MS=100`); the legacy append raises; follow-up preparation raises. The response equals that of `off`; each case increments its counter in the in-process snapshots (`TWO_PASS_METRICS.snapshot()`, `LEDGER_METRICS.snapshot()`) and emits its event; `write_stop` is true for the ledger cases; public `/ready` `slis.two_pass_shadow` holds only `scheduled` and `phase2_bound_claim_ratio_baseline`.
29. `test_plan_l_flag_off_restores_the_labelled_legacy_path`: with `off`, no shadow record; legacy records still exist; the panel labels are present.
30. `test_plan_l_the_bound_claim_ratio_is_reported_and_a_drop_below_phase_2_is_a_stop`: the extractive generator gives 1.0 and no stop; a `ScriptedGenerator` with 1 unbound claim in 4 gives 0.75, `bound_claim_ratio_stop` true, and replay `compute(...)` gives `result == "stop"` and exit 3; a null ratio is not a stop.
31. `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`: `config_package_version == "2.0.0"`; `tutor_pipeline` ids and hashes equal the package's; `two_pass_tutor == "shadow"`; `ledger == {"chain": "tutor-responses", "status": "ok"}`, with no sequence number; both SLI blocks present; `_build_fields()` makes no DB call.
32. `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` (SQLite and PostgreSQL via `fresh_database_url`): `create_all` on every table except the three Phase 3 tables, `tutor_turns.ledger_record_expected` dropped (a Phase 2 database), `alembic stamp 20261119_phase2_corpus_spans`, `alembic upgrade head`, `run_schema_upgrades`: `compare_metadata == []`; append one row; `alembic downgrade -1` (one step from this Phase 3 stamp) fails with "export first"; with `-x allow_ledger_drop=true` it succeeds, the three tables and the column are gone; `SCHEMA_REVISION` equals the single head. The runbook's absolute-target rollback over every stamp state is `test_e10_*`.
33. `test_plan_g_legacy_turns_read_as_no_verdict`: a turn an image that keeps no ledger created (`ledger_record_expected` null), with no record, gives `recorded == False`, `legacy_turn == True`, `unrecorded_reason == "earlier_image"`, `verdict == "no-verdict"`; row counts unchanged.
34. `test_plan_h_private_plane_spans_never_reach_the_bundle_the_envelope_or_the_alias_route`: a temporary manifest moves one document item to the private plane (as AC-2-7 does); for queries that retrieved it before, no bundle or envelope span names it, the shadow record has none of its span ids, and `/evidence/spans/{id}` is 404; every envelope span is quotable; `governed_empty` abstains with `no_quotable_evidence` or a retrieval reason on all 298 fixture items.
35. `test_task_3_8_the_evidence_panel_labels_the_contained_answer_and_never_says_grounded`: answer → `labels == ["lexically_screened"]`, abstention → `[]`; `"extractive_only"` always in `degraded`; spans equal the citations; `resolvable` follows `SPAN_RESOLVER_ROUTE_ENABLED`; "grounded" nowhere in `evidence`; with `EVIDENCE_PANEL_ENABLED=False` the response has no `evidence` key.
36. `test_evidence_spans_alias_matches_the_resolver_route_and_is_off_when_the_flag_is_off`: body equals `/spans/{id}`'s plus `license_class`; governed D-31 document spans give 404; flag off → 404 and `no-store`.
37. `test_the_ledger_is_outside_erasure_and_guarded_at_start_up`, modelled on the security-log test.
38. `test_freeze_production_chat_responses_keep_todays_keys_and_bytes`: with production-like settings monkeypatched into the orchestrator and route (evidence panel off, shadow off), `/assistant/chat` returns exactly the pre-Phase-3 key set (`answer, citations, retrieval_mode, provider, model, grounded, thread_id, turn_id, decision, decision_reason, claims`), no `evidence` key, and a body equal (minus ids) to an orchestrator built without the Phase 3 follow-ups.
39. `test_plan_l_a_held_ledger_lock_never_delays_the_learner_beyond_the_append_budget`: on PostgreSQL (branch), another connection holds `SELECT ... FOR UPDATE` on the head; a chat returns within the append budget in force (`ledger.ledger_budget_ms`: the package's 1500 ms, `TUTOR_LEDGER_APPEND_BUDGET_MS` unset) + 500 ms + 1500 ms for the chat itself, with the normal body, and `failed.legacy` increments; on both dialects an `IntegrityError`-raising stub is retried at most 3 times and an `OperationalError` with no SQLSTATE is not retried. A deadlock (40P01) or a serialization failure (40001) is retried like an `IntegrityError`.

### 13.2 NEW unit test files

| File | Tests |
|---|---|
| `test_tutor_pipeline_contracts.py` | Committed schema files structurally equal `SCHEMA_MODELS` and their sha256 equal the pins (`check_tutor_pipeline_package(..., structural=True) == []`). Models are frozen. `LockedClaimSet` refuses a wrong `claim_set_hash` or `span_ids`; `verify_locked` catches a `model_copy` tamper. `LedgerEntry` validator rules, both directions. `ledger_canonical` refuses NaN. |
| `test_tutor_resolver.py` | `resolve_turns` rule table; the text template; prompt-hash pin; `resolve_thread` ordering with microsecond timestamps and SQLite whole-second legacy rows (and `id != cur.id`); wrong-thread refusal. |
| `test_tutor_retrieve_bind_lock.py` | Request allowlist; `corpus_version_mismatch`; sufficiency (abstain; near_miss exactly when the top result's `near_floor`; answer); every bind drop reason; claim text kept verbatim (an NFKC-changing character survives); content-addressed `claim_id`; lock hash independent of plan; `span_is_quotable` equals the `contain_answer` decision over all dev and governed spans; `RetrievalEngine.evidence` results equal the lexical `search` results, never call the semantic backend even with `SEMANTIC_RETRIEVAL_ENABLED` and a mocked aligned backend, and record no Phase 2 SLI. |
| `test_tutor_render_subset.py` | Each plan's layout and exact template strings; stepwise reorders by `source_order`; citations numbered by first appearance; `layout_text`; every `check_subset` problem code; the pedagogical hash pin covers all plans. |
| `test_response_ledger.py` | Canonical bytes and `record_hash_for` vectors; genesis; `chain_head`; an `IntegrityError` at commit retried onto the head within the budget (a session whose first commit raises; the head is read under `FOR UPDATE`, so a stale head is not faked), attempts capped at `ledger_append_attempts`, and an `OperationalError` raised at once, never retried; the Core statement order (the `SET LOCAL`s before the first read on PostgreSQL, insert record before head update) on both dialects; `LedgerConflict`; `record_legacy_delivery` fail-open; the PostgreSQL `lock_timeout` statement issued (dialect branch); worker JSON line; `tutor.ledger.appended` carries `record_hash`; `verify_ledger.py` report, coverage, export refusal inside the repo; `entry_schema` dispatch. |
| `test_config_package.py` (additions) | `test_package_v2_keeps_every_phase_2_value_of_v1` (every v1 block equal except the lineage field; `owner_decisions` keeps the four v1 entries equal; `retrieval_sha256` equal). `test_v1_stays_readable_for_one_release`. `test_v2_structural_errors_always_stop_the_load`, parametrised: `max_regenerations=3`, a `default_plan` not in the plans, a non-wired generator, an absolute or `..` schema path, a missing schema name, `phase4_exit_passed=true` without evidence, D-12 open with a second generator, `retrieval.mode != "lexical"`, a stop ratio of 0. `test_on_is_refused_unless_phase4_exit_passed`. `test_a_start_up_pipeline_problem_is_fatal_only_when_the_pipeline_is_requested` (subprocess, governed: a schema file removed → starts with `off`, fails with `shadow`). |
| `test_authorization.py` | Additions in 13.3. |

### 13.3 Existing tests expected to change (intent kept; the commit message gives the reason)

1. **`test_config_package.py::test_the_shipped_package_validates_and_matches_its_hash`** asserts `package_version == "2.0.0"` for `DEFAULT_PACKAGE_PATH`; the v1 assertions move to `test_v1_stays_readable_for_one_release` (loads `V1_PACKAGE_PATH`, 1.0.0, hash verified). Reason: plan P "schemas in configuration package v2". `RAW` now reads v2; the parametrised structural edits still apply.
2. **`test_phase2_acceptance.py::test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis`**: `"1.0.0"` becomes `package.package_version` (intent: "reports the package in force"); `set(slis) == {4 keys}` becomes `set(slis) == {4 keys} | {"tutor_ledger", "two_pass_shadow"}` (still exact).
3. **`test_authorization.py`**: `OWNERSHIP_TESTED` adds `("POST", "/tutor/turns")` and `("GET", "/ledger/responses/{response_id}")`; `_concrete` adds `"response_id": "turn-00000000-0000-0000-0000-000000000000"`; two new ownership tests: `test_another_learners_thread_cannot_be_continued_through_tutor_turns` (404, no message written) and `test_another_learners_ledger_record_reads_as_missing` (owner 200; intruder response equals the missing-id response; shadow id 404 for the owner). Strengthens the matrix rule.
4. **`apps/frontend/tests/answer-wording.integration.test.ts`:** `ANSWER_SURFACES` adds `components/evidence-panel.tsx` and `lib/evidence-panel.ts`. Stricter.
Later changes to existing tests are listed, with their reasons, in the commit message of the round that made them (18.4).
5. **`docs/security/authorization-matrix.md`:** regenerated (`test_the_committed_matrix_is_current`).
6. **Expected unchanged; verify:** `test_cs595_increment.py::test_persistent_tutor_stores_resolved_follow_up_and_claim_provenance` (legacy `_resolve_query` kept; direct `orchestrator.chat` calls schedule nothing); `test_api.py` stub tutors (no `_followups`); AC-2-9 tests (the shadow changes no response; `RetrievalEngine.search` call counts unchanged because the shadow calls `evidence`); `test_the_shipped_gate_outside_development_is_p1_floor_and_bm25_is_an_override` and `test_security_log.py::test_configuration_overrides_are_recorded_outside_development` (exact override details unchanged under production defaults); `test_structured_logging.py::test_startup_logs_what_the_instance_started_with` (one `qcai.api` record); `test_ac_2_8_the_ci_gate_exits_1_...` and `test_d9_an_invalid_or_tampered_configuration_package_...` (they copy the default package, now v2, without `schemas/`; parsing does not need the files); `calibrate_abstention.py --check` (lineage field); `privacy-inventory.integration.test.ts` (the new row is not a retention-constant row).

### 13.4 Frontend tests (NEW `apps/frontend/tests/evidence-panel.integration.test.ts`)
- `evidencePanelView`: maps each code to its fixed text; an answer gets the lexically-screened label, an abstention none; `resolvable: false` gives `href === null`, `true` gives `/api/backend/evidence/spans/<encoded>`; no output matches `/grounded/i`.
- Source regexes: `teaching-assistant-chat.tsx` matches `/message\.evidence \? <EvidencePanel/` and `/evidence: response\.evidence \?\? null/`; `evidence-panel.tsx` is a `role="group"` labelled "Evidence for this answer", with distinct "Passage {n}" link text and no "grounded"; `privacy-disclosures.ts` has the "Tutor response ledger" row with its current wording.
- A span link never mints a guest session, and only a well-formed span id is public (the proxy patterns); the Q&A panel renders only when the API sent `evidence`; the panel's links, labels and focus ring, and the compose field, keep their contrast in both themes (WCAG ratios computed from `globals.css`).

---

## 14. CI changes (`.github/workflows/ci.yml`)

`api-and-evaluation`, after the existing `config_package.py --check` step:

```yaml
      # Phase 3: configuration package v1 stays readable for one release (DI-42).
      - run: python scripts/config_package.py --check --path apps/api/app/config_package/v1.json
      - run: python scripts/authorization_matrix.py --check
      # Plan Phase 3 F: three-plan replay over public-corpus fixtures (not E3 or LQ-1 evidence); exit 3 is the plan L
      # bound-claim-ratio stop.
      - run: python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
```

- `api-postgres-driver` runs the API suite on PostgreSQL 16 as a matrix over both drivers, psycopg and pg8000 (production's driver), with `TEST_DATABASE_URL=postgresql+${{ matrix.driver }}://...` (DI-46). The pg8000 leg's URL goes through pg8000's legacy `pg8000.connect`, not the `pg8000.dbapi.connect` that production's Cloud SQL connector calls, and the two raise different classes (7.19); `test_m1_*` builds production's engine with a `pg8000.dbapi.connect` creator and runs on both legs. Its checks are named "api-postgres (psycopg)" and "api-postgres (pg8000)". The job named `api-postgres`, the required status check on `main`, needs both legs and passes only when both succeeded.
- The frontend job is unchanged (the new test matches `tests/**/*.test.ts`). `release-artifacts` and `api-image-boundary-scan` are unchanged.

---

## 15. Docs and evidence

1. **`docs/adr/ADR-001-grounding-separation.md`:** `## Revision 2026-11-19 (Phase 3: provenance-first two-channel tutor)`, appended after the original decision, states the Phase 3 design as it is: status (accepted for Phase 3 engineering; D-19 extractive provisional, PD-08; D-12 open, PD-09); the evidential channel (resolve, retrieve, envelope, generator, bind, lock) and the pedagogical channel (render, subset check); learner state is an input to neither; `PresentationPlan` from request hints; `build_pedagogical_context` still reaches no prompt; lock before render and the plan-independent `claim_set_hash` (conflict 1); verbatim claim text and sentence-aligned binding (conflict 32); the ledger as the record replacing mutable `TutorTurn` provenance; `two_pass_tutor` shadow-only until the Phase 4 exit with three locks (conflict 2, R-a); residuals: "misleading wording within locked claims" (plan M; sentence splits at abbreviations) and renderer wording (R-41); the RQ2 replay (AC-3-2) and the invariant 1 test.
2. **`docs/adr/ADR-005-abstention-gate.md`:** `## Revision 2026-11-19 (Phase 3)`: the overlap `ClaimGate` is removed (plan 3.4); `claim_gate.py` is the segment subset checker; abstention reasons come from the pipeline vocabulary; the full rewrite is Phase 4 (plan Phase 4 F).
3. **`docs/architecture/phase3-implementation-spec.md`:** this document; section 18 holds the implementation record and the review history.
4. **`docs/evaluation/phase3/README.md`** plus the generated `three_plan_replay_v1.json`: reproduction, configurations, metrics, "not E3 or LQ-1 evidence", the bound-claim stop, limitations (deterministic renderer; no entailment checker; lexical only).
5. **`infra/cloudrun/deployment.md`**, section `## Phase 3: two-channel tutor, response ledger and shadow (runbook)`; the Phase 2 step "must report `config_package_version` 1.0.0" says "(2.0.0 from the Phase 3 release; see the Phase 3 section)".
   - **Approval.** Every step is a cloud write needing Platform Owner approval under D-05; none was run in Phase 3.
   - **Defaults that ship:** `TWO_PASS_TUTOR` off, `LEDGER_ROUTE_ENABLED` false, `EVIDENCE_PANEL_ENABLED` false, `TUTOR_LEDGER_ENABLED` true; `TUTOR_LEDGER_APPEND_BUDGET_MS` and `TWO_PASS_SHADOW_BUDGET_MS` unset, so the package's 1500 ms append and 2000 ms shadow budgets hold (`tutor_pipeline.budgets`, PD-11); `POST /tutor/turns` 404.
   - **Before the release:** `config_package.py --check` (v2 and v1); `replay_tutor_plans.py --check`; a backup; reading the CPU allocation (DI-48) and the request timeout; optionally the Alembic pre-deploy job from a workstation with the migration scripts, which checks the stamp first with `alembic current` and runs `alembic upgrade 20261119_phase3_response_ledger` (an absolute target) only on a `20261119_phase2_corpus_spans` stamp, skipping otherwise (`alembic upgrade head` on a database built by `create_all` replays revisions against tables that already exist and fails).
   - **Deploy.** `create_all` adds the three tables and the schema upgrades add the triggers and `tutor_turns.ledger_record_expected`; start-up writes nothing to the ledger. `/ready` must show `config_package_version` 2.0.0, `two_pass_tutor` off, `tutor_pipeline.available` true and `ledger.status` ok. A pipeline-package problem does not stop the start-up while `TWO_PASS_TUTOR` is off; `available` false then needs a fix before any shadow enablement.
   - **Verify** with `python -m app.workers.response_ledger` (`--expect-head`, `--coverage-since`, `--coverage-horizon-s`, and `--check-provenance`, the provenance audit that stands in for F-2's logged-prompt check, DI-49); its daily schedule is DI-33. Every `tutor.ledger.appended` log line carries `seq` and `record_hash` (the off-DB copy).
   - **Enabling shadow in production** is a separate D-05 decision (DI-32); expect a `config.override` (`two_pass_tutor_shadow`); check Cloud Run CPU allocation for background tasks first.
   - **Stop conditions** (plan L): any `tutor.ledger.append_failed` or `tutor.ledger.conflict`; ledger coverage below 100%, read by CPU allocation against the 360 s horizon (4.12); the log-based shadow bound-claim ratio below 1.0; `response_ledger` job problems (`broken` or `provenance_mismatch`). On a stop, set `TWO_PASS_TUTOR=off` (shadow) or investigate the database, with `TUTOR_LEDGER_ENABLED=false` as the kill switch for request-path ledger writes; legacy deliveries continue. An attempt still without a terminal line after the 840 s dead-peer horizon is held by a server that never replies: replace the instance (a new revision of the same digest).
   - **Roll back** by digest; a digest rollback needs no downgrade, and turns the earlier image serves read `earlier_image`. The optional Alembic downgrade needs its own owner decision, the worker's `--export`, an `alembic current` check, the absolute target `20261119_phase2_corpus_spans` and, after the re-apply, the worker's `--restore`.
6. **`infra/cloudrun/observability.md`:** `## Phase 3 SLIs: ledger and shadow (plan Phase 3 I)`, covering 11.3-11.4, the `/ready` blocks and the log-based SLIs and alerts, marked "Not set up yet" (DI-50).
7. **`docs/testing/test-strategy.md`:** `## Phase 3 acceptance map (plan Phase 3 K)`, mapping AC-3-1..AC-3-6 and plan G/H/I/L onto the tests, and every `apps/api/tests/test_phase3_*.py` file onto what it proves.
8. **`docs/security/authorization-matrix.md`:** regenerated.
9. **`infra/cloudrun/api-production.env.example.yaml`:** the new settings (section 6).
10. **BEP-2-12** (outside the repository; never edit other phases' rows):
    - `phase03/PHASE_RECORD.md`: a current-state section first (what was built per task 3.1-3.8; preconditions as taken: Phase 2 exit not passed, AC-2-7 partial, DI-25/DI-26; task 1.11 "lexically screened" label present only as an API string, rendered in development by the panel, production via DI-34; D-12 open; D-19 provisional; AC status with test names; open items with their DI rows; the latest suite totals and CI run), then a compact history table, one row per review round.
    - `phase03/CLOSURE_EVIDENCE_NOTES.md`: R-22 (the ledger, tests 11-18, off-DB record hashes; residual DBA alteration until DI-33); R-41 (AC-3-1 tests; residual renderer wording); R-11 (typed envelope, `extra="forbid"`); R-13 (resolver binding, no rebinding, sentence-aligned verbatim; closure in Phase 4); R-16 (containment unchanged; no delivered path; truncation refused at bind); R-46 (package v2 pins, stop baseline in the package); R-10 (lexical-only shadow, no provider egress).
    - Register rows (section 16).

---

## 16. Provisional defaults and deferred items

The registers in `BEP-2-12/00_meta` (`PROVISIONAL_DEFAULTS_REGISTER.md`, `DEFERRED_ITEMS_REGISTER.md`, the `## Phase 3` heading) hold the authoritative rows; this section summarises their current values.

### 16.1 Provisional defaults (PD-08 to PD-12)

| # | Decision (owner) | Plan text | Provisional default applied | Where the value lives |
|---|---|---|---|---|
| PD-08 | D-19, extractive mode (PO) | 18.4: "D-19 RECOMMENDATION: no-provider extractive mode quoting spans only from manifest-approved public-plane assets, never the private licensed evaluation corpus or ULQS; no approved span, abstain [Risk R-26]." | The two-pass evidential generator is `extractive-d19-v1`: verbatim whole sentences of quotable spans only, bound by `resolver-bundle-sentence-v2` (a claim equals a `sentences-v2` sentence of the document's section text lying wholly inside every span it cites; a span-edge fragment is refused as `partial_sentence`). No approved span means abstain. The legacy containment is unchanged. | Package v2 `owner_decisions.D-19`, `tutor_pipeline.evidential`; ADR-001 revision 2026-11-19 |
| PD-09 | D-12, provider and terms (PO, counsel); hold H6 | 14.3: "D-12 \|OPEN \|PO \|Generation provider terms \|single pinned (interim)"; 9.4: "H6 \| Provider [Decision D-12] \| P3 interim path; P5 exit \| Payload register"; "OPEN decisions ... MUST NOT be closed by engineering alone." | Unresolved path: hold H6 blocks the provider interim path and stays held; no provider generator is wired (`WIRED_GENERATORS` holds only the extractive id). Phase 3 runs D-19 extractive mode instead, which sends no provider payload; shadow retrieval is lexical only. | Package v2 `owner_decisions.D-12`; `WIRED_GENERATORS` |
| PD-10 | The Phase 3 switches outside development (freeze, D-05) | Phase 3 G: "two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners"; 5.3 release rule | `TWO_PASS_TUTOR` off (shadow in development; `on` refused until `phase4_exit_passed`); `EVIDENCE_PANEL_ENABLED` and `LEDGER_ROUTE_ENABLED` false; `POST /tutor/turns` 404; `TUTOR_LEDGER_ENABLED` true (not learner-visible). Each relaxation logs `config.override`. The package's `flag_policy` is marked `provisional: true`, and the loader refuses defaults that differ from the code's (`TWO_PASS_DEFAULT_DEVELOPMENT`, `TWO_PASS_DEFAULT_ELSEWHERE`). | `app/core/config.py`; package v2 `flag_policy`; env example |
| PD-11 | Two-pass engineering parameters with no plan value | 3.1-3.7 and 7.3 name the mechanisms but give no values (the regeneration limit "at most two" is plan text) | Resolver: at least 2 content terms, the cue list, lookback 4. Retrieval: `top_k` 4, lexical; near-miss is the gate's `near_floor` on the top result. Claims: at most 3, 2 per span, `sentences-v2` sentences of 4+ words and at most 1000 characters, sharing at least 1 content term with the question (`min_question_overlap_terms`). Plans concise, stepwise, socratic; default concise. Budgets: shadow 2000 ms, ledger append 1500 ms, 3 attempts, 250 ms wait grace, 4 append workers, 16 in flight. The attempt horizon (`ledger.attempt_horizon_s`, 360 s) derives from those values, the pool's 30 s checkout timeout, the 30 s connect bound (`app.core.db.CONNECT_TIMEOUT_S`) and `HORIZON_MARGIN_S` 60 s. Idempotency-Key: `^[A-Za-z0-9._:-]{8,128}$`, kept 24 hours, in-progress lease 600 s. `LEDGER_RATE_LIMIT` 30/minute; `POST /tutor/turns` shares `ASSISTANT_CHAT_RATE_LIMIT`. Stop baseline 1.0 (measured). | Package v2 `tutor_pipeline` (`budgets`, `idempotency` marked `provisional: true`); `app/core/config.py`; `app/core/db.py`, `app/services/ledger.py` |
| PD-12 | Ledger reader roles (SL) | 7.3: "GET /ledger/responses/{response_id} (owner or reviewer)"; 7.6: "reviewer access is logged" | The plan text: only role `reviewer` reads any record, shadow included; each read is a security event; owners read their own non-shadow records without chain fields. Outside development the route answers 404 to everyone. No reviewer role is provisioned (DI-38). | `app/core/authorization.py` `LEDGER_READER_ROLES`; the authorization matrix |

### 16.2 Deferred items (DI-31 to DI-51)

| # | Item | Who | State |
|---|---|---|---|
| DI-31 | A cited green CI run for AC-3-1..AC-3-6 (plan Phase 3 P), on `main`. The branch was pushed; run 44676365093 at `94aa3e6` passed every job. Each later commit needs its own run, and the exit needs a cited green run on `main` after the merge. | Eng | Open |
| DI-32 | Production shadow enablement (`TWO_PASS_TUTOR=shadow` outside development): D-05, CPU for background tasks, keep-alive and thread-pool effects (section 9); plan H applies to real learner questions. | PfO / PO | Not started |
| DI-33 | The daily off-DB ledger digest (7.5): schedule `python -m app.workers.response_ledger` and keep the logged head (a cloud write). | PfO, then Eng | Worker built; not scheduled |
| DI-34 | The evidence-panel production rollout (`EVIDENCE_PANEL_ENABLED` outside development; D-05), which completes the task 1.11 label precondition in production; the panel for reloaded threads; the trust indicator. | PO | Deferred |
| DI-35 | D-12 and hold H6, the provider decision; wiring a provider generator is Phase 5, through the gateway. | PO, counsel | Open (PD-09) |
| DI-36 | F-1 cannot be measured before a two-pass response is delivered (Phase 4 exit). | MLE | Not measurable in Phase 3 |
| DI-37 | Ratify PD-08..PD-12. | PO / PI / SL | Open |
| DI-38 | Provision reviewers (no `reviewer` role in account provisioning; Phase 6, H4, D-18). | PO | Open |
| DI-39 | `/qa/ask` deliveries are ledgered (`test_c8_*`); the cited run is DI-31. | MLE | Closed in code |
| DI-40 | Idempotency-Key on `POST /tutor/turns` (`test_c9_*`, `test_e7_*`, `test_f13_*`); the privacy disclosure of the retry record and client keys come with the Phase 4 enablement. | Eng | Closed in code |
| DI-41 | The contract step after the dual-write release: retire `_resolve_query` and the `TutorTurn` provenance columns once two-pass delivers. | Eng (Phase 4+) | Deferred |
| DI-42 | Remove configuration package v1 after one release, with its CI check. | Eng | Deferred |
| DI-43 | LQ-1 and E3 learner-state invariance with the real learner model (Phases 8 and 10). | MLE / PI | Out of Phase 3 scope |
| DI-44 | Span routes in the frontend proxy's public patterns. | Eng | Closed |
| DI-45 | Ledger retention period (plan 12.8: "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted); proposed default release life plus 24 months."). The ledger is retained, machine-readable in the package (`owner_decisions.PLAN-12.8`); the proposed default is recorded but not applied, as it is not a default form engineering may apply. | PO / PI | Open (owner decision) |
| DI-46 | pg8000, the production driver, in CI: the `api-postgres-driver` matrix, whose pg8000 leg uses pg8000's legacy `pg8000.connect`; production's `pg8000.dbapi.connect` interface runs in `test_m1_*` on both legs (7.19); the cited run is DI-31. | Eng | CI leg added |
| DI-47 | Task 3.3 "atomic claims" under D-19 (conflict 34), recorded as `owner_decisions.PLAN-3.3`, unratified. | PI / Research Lead | Open |
| DI-48 | Read and record the Cloud Run CPU allocation before the Phase 3 release; it decides how the coverage stops are read (always-on rules until recorded). | PfO | Open (a cloud read) |
| DI-49 | F-2 (plan 15.1, "Zero learner-state fields in evidential-pass prompts") is taken by its 15.2 mechanism, the CI contract test (AC-3-1, `test_ac_3_1_*`). Its 15.2 method, "F-2 A (static check of logged prompts)", has no input: no evidential prompt is logged or ledgered (R-e), and the D-19 generator sends none, until a provider prompt exists (D-12). Until then the provenance audit stands in: `python -m app.workers.response_ledger --check-provenance` (`ledger.ledger_provenance`, 4.12) checks that every record stamped with the package in force names that package's pinned evidential input (a shadow record its evidential prompt hash, a legacy record the containment rule hash in `tutor_pipeline.legacy`); built and tested (`test_l7_*`); its production run is a cloud job under D-05 (deployment.md, Phase 3). | MLE / SL | Met by AC-3-1; audit built, not yet run in production; logged-prompt method open until D-12 |
| DI-50 | The Phase 3 log-based metrics and alerts (observability.md), a cloud write. | PfO, then Eng | Defined; not created |
| DI-51 | The floating chat's contrast in the opt-in light theme (pre-existing production styling; ships with a D-05 release). | PO (D-05), then Eng | Open |

---

## 17. Verification and exit

**Verification** (all must pass; `<py>` is the scratch venv's python):

```
<py> -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests -p no:cacheprovider
<py> scripts/validate_corpus.py --check-public-assets --check-recall-stop
<py> scripts/validate_lqs.py --allow-draft
<py> scripts/config_package.py --check
<py> scripts/config_package.py --check --path apps/api/app/config_package/v1.json
<py> scripts/generate_manifest.py --check
<py> scripts/validate_corpus.py --check-hashes --check-near-duplicates
<py> scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
<py> scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report <scratchpad>/boundary.json
<py> scripts/authorization_matrix.py --check
<py> scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
cd apps/frontend && npm run lint && npm run typecheck && npm run test:integration
git status --short   (no stray files; nothing in the repository root)
```

**Scratch PostgreSQL** (`C:\Program Files\PostgreSQL\17\bin`; data directory in the scratchpad; never the installed server's data directory; never pipe `pg_ctl` output):
- `initdb -D <scratchpad>\pg17 -U postgres -A trust`;
- `pg_ctl -D <scratchpad>\pg17 -o "-p <port>" -l <scratchpad>\pg17.log start`;
- `createdb -h 127.0.0.1 -p <port> -U postgres qcai_test`;
- run the API suite with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:<port>/qcai_test`, and again with `postgresql+pg8000://...` on a fresh database;
- stop it at the end with `pg_ctl -D <scratchpad>\pg17 stop`.

The latest results are in 18.3. Against the Phase 2 baseline (576 passed, 2 skipped, 3 xfailed (strict) on SQLite; 574 passed, 3 xfailed on PostgreSQL), Phase 3 adds tests and no skip or xfail.

**Exit (plan Phase 3 P)**
- "AC-3-1 to AC-3-6 green in a cited CI run; schemas in configuration package v2; ADR-001 revised".
- Schemas in package v2 and the ADR-001 revision are done. The cited CI run is DI-31: the exit is not passed until a cited run is green on `main`.

---

## 18. Implementation record (2026-11-19)

18.1 and 18.2 record the departures and refinements the code forced when this spec was first implemented; sections 0-17 have since been corrected in place, so they state the current code. 18.3 is the latest verification and 18.4 the review history. Local machine paths are written `<scratchpad>`, `<py>` and `<port>`.

### 18.1 Departures known at spec time, confirmed

- **Production stored-data change:** tutor message and turn `created_at` are set in Python (7.11), needed for a deterministic per-thread order on SQLite (M5). The user message gets `now`, the assistant reply `now + 1 µs`, the turn and `thread.updated_at` `now`.
- **`"evidence"` is omitted from serialisation when None** (conflict 28), so production response bodies keep today's keys. Test 38 pins the key set and the bytes (ids aside).
- **No delivered two-pass path in Phase 3** (R-a, conflict 31). `ledger_write_failed` is not in the abstention vocabulary.
- **The legacy append is bounded** by the package's `ledger_append_ms` (1500 ms; `TUTOR_LEDGER_APPEND_BUDGET_MS` overrides it), which also sets each PostgreSQL attempt's lock, statement and idle-in-transaction timeouts; the learner waits at most the budget plus the 250 ms grace, the wait for a connection included (conflict 29).
- **Start-up pipeline-package problems are fatal only when the pipeline is requested** (conflict 30): a governed build with `TWO_PASS_TUTOR` not off.
- **Production-image changes outside the tutor** (7.19-7.21; none is learner-visible): on the pg8000 driver, server errors take psycopg's PEP 249 classes by SQLSTATE class on every engine (`classify_pg8000_errors`); a new Cloud SQL connection is bounded at 30 s, with at most 30 connects pending (`cloud_sql_creator`, `bounded_connect`); each Cloud SQL connection's socket has TCP keepalive, which ends a read whose peer is gone within 60 s (`enable_tcp_keepalive`); and `app.schemas` refuses to import, so the API does not start, on a pydantic that keeps a None `exclude_if` field, below the `pydantic>=2.12.4,<3` floor in `requirements.txt`.
- **Cuts:** no `GatewayGenerator` class (the `ClaimGenerator` Protocol is the interface); no `own_hashes_verified`; no shadow latency percentiles (latency is in each `tutor.two_pass.shadow` line); no per-combination orchestrator runs in test 27 (one per effective mode).

### 18.2 Refinements forced by the code

1. **Module placement, to avoid import cycles.** `ledger.py` imports the contracts, and the lock hash needs canonical JSON, so these live in `tutor_pipeline/contracts.py`:
   - `ledger_canonical`, `sha256_hex`, `lock_hash`, `verify_locked` and `LockedClaimSetTampered`. `app.services.ledger` imports `ledger_canonical`, and `tutor_pipeline/lock.py` re-exports `verify_locked`.
   - `TWO_PASS_DELIVERY_IMPLEMENTED`, the single flag that the `LedgerEntry` validator, the pipeline and the shadow runner read at call time. `shadow.py` exposes `delivery_implemented()`.

   `tutor_pipeline/__init__.py` re-exports lazily (module `__getattr__`), so importing a submodule never imports the pipeline.
2. **`render_checked()`** is a module-level function in `pipeline.py`: the plan 3.7 loop of render, subset check and at most `max_regenerations` re-renders. `TwoPassPipeline.run` uses it, and the AC-3-3 property test drives it directly with random locked sets.
3. **The claim plan must name the configured generator** (`plan.generator == generator.ref`); otherwise the plan is invalid (`claim_plan_invalid`). The lock is stamped with the configured generator's ref, never a ref the plan claims.
4. **Order of the checks in `run`.** A sufficiency abstention is decided before the budget check. The budget is checked after retrieval, generation and binding, and between render attempts. A passing render ends the loop, so a passing answer never depends on timing.
5. **Abstentions and the entry.**
   - `presentation` is None when no render attempt ran (its `attempts` must be 1-3).
   - The two-pass entry's provenance always carries the configured generator's model id and prompt hash, and the package's pedagogical prompt hash. `counts.proposed_claims == 0` shows the generator was not called.
   - The lock still runs on every path, so every two-pass record has a `claim_set_hash`.
6. **The legacy entry.**
   - Field values: `generator_id` is `contained-answers-v1`; `evidential_prompt_hash` is `LEGACY_CONTAINMENT_RULE_HASH`; `pedagogical_prompt_hash` is null; `counts.render_attempts` is 0; `proposed_claims` is the claims plus `dropped_unresolved`, with `dropped = {"unresolved_citation": n}` when n > 0.
   - `LegacyDelivery` gains `manifest_sha256`, taken from the orchestrator's registry, because the recorder has no registry of its own.
   - The orchestrator now builds one `CorpusRegistry` per chat (it built two). The values are unchanged.
7. **Follow-ups are prepared separately**, so a failure in one never loses the other:
   - legacy (`_legacy_followup`): counts `attempted.legacy`; on a failure, `failed.legacy` and `tutor.ledger.append_failed` with stage `prepare`;
   - shadow (`_shadow_followup`): on a failure, `failed.pipeline` and `tutor.two_pass.shadow_failed` with step `prepare`.

   `TurnFollowups` lives in `tutor_followups.py`. `run_turn_followups` counts `scheduled` and passes the orchestrator's settings to `record_legacy_delivery`.
8. **Metrics details.**
   - The pipeline counts `attempted.shadow` just before its own append, and wraps any append failure as `LedgerWriteFailed`. The runner counts that as `failed.ledger`, and also as `failed.shadow` through `record_ledger_failure`.
   - A `LedgerConflict` counts both `conflicts` and `failed`.
   - `render_regenerations` sums `attempts - 1` over completed runs.
9. **Loader checks beyond 5.2:**
   - `ledger.genesis` must be 64 zeros, and `ledger.deliveries` must be exactly the three deliveries.
   - `flag_policy.two_pass_tutor` must have `values` `[off, shadow, on]`, `default_elsewhere` `off` and `on_requires` `phase4_exit_passed`.
   - `owner_decisions.D-19` must be an object, and `D-12` is required.
   - The resolver parameters have bounds (`min_content_terms` and `max_lookback` 1-20), and the continuation cues must be lowercase.
   - A schema path with a drive letter or a colon is refused.

   `TutorPipelineParams.schemas_sha256` (one digest of the sorted pins) feeds `/ready`. `tutor_pipeline` carries an informational `authority` string, and `owner_decisions.D-19` quotes the plan's text.
10. **Schemas.**
    - The committed JSON schemas include the models' docstrings as `description`, so a docstring edit changes a pinned schema; `--check` and the start-up check catch it.
    - The structural check needs `additionalProperties: false` on every record, meaning every object with properties. A map such as `PipelineCounts.dropped` (`dict[str, int]`) must type its values instead.
11. **Routes.**
    - `/spans/{id}` and `/evidence/spans/{id}` share `_resolve_span`; both return `license_class` (the same body).
    - The ledger route logs `ledger.reviewer_read` for a reviewer's miss too, with delivery `none`.
    - A guest is an ordinary principal: an owner reads their own record, and anyone else gets the missing-id 404.
12. **The verifier** caps reported problems at 50. A first row other than seq 1 is reported as `seq 1 to {n-1} missing`. `LedgerCheck.head_row` is the head table's row.
13. **The replay.**
    - `fixture.sha256` is the fixture's canonical-JSON sha256, so CRLF and LF checkouts agree.
    - Each configuration also reports `threshold_version`; the `tutor_pipeline` block adds `subset_check`, `binding_rule` and the stop baseline.
    - `items_digest` is the canonical sha256 of the sorted rows.
    - `compute(subset=n)` takes an evenly spaced, deterministic sample, and `generator_factory` lets the stop test inject a generator.
14. **The evidence panel** always lists `citations_provisional` while citations stay provisional (AC-1-13), alongside `extractive_only`. Frontend span links carry `rel="nofollow"`.
15. **Settings.** The refusal of `on` raises inside the model validator, so `Settings(...)` raises a pydantic `ValidationError` (a `ValueError`).
16. **Tests.**
    - Test 16 runs the two-thread barrier and then the 4 × 10 writers in the same fresh database, so it expects `(42, 1, 42)` rather than `(40, 1, 40)`.
    - `make_entry` (a valid ledger entry builder) lives in `tutor_fakes.py`.
    - Test 13 runs the worker by subprocess only for the forged-head case, where the logged head is needed; `verify_ledger.py` runs in-process for every case.
    - The retry test in `test_response_ledger.py` makes the first commit raise `IntegrityError`, rather than faking a stale head: the head is read under `FOR UPDATE`, so it cannot go stale.
    - `test_a_start_up_pipeline_problem_is_fatal_only_when_the_pipeline_is_requested` lives in `test_phase3_acceptance.py`.
    - `_concrete()` in `test_authorization.py` also gains a `span_id` value (unused by refused routes; harmless).
    - The AC-3-1 signature allowlist names each parameter the evidential functions take.
    - Test 34 adds a control: the alias route serves the span (200) while the item is public and approved, before showing 404 once the item is private.
17. **The CSS and the privacy row** follow 12 exactly. The evidence-panel test also checks the privacy row's wording.
18. **Line endings.** New files are LF. Edited files keep their working-tree line endings; git stores LF. `.gitattributes` pins this spec to LF, as it does the Phase 2 spec.

### 18.3 Verification results (latest local run)

Local runs on 2026-11-20, twelfth review round (the commit after `4283194`, run on its working tree before the commit).

**Suites**
- **Full suite, SQLite** (`pytest -m "not release_artifacts" apps/api/tests evaluation/tests`): 1020 passed, 2 skipped, 3 xfailed (strict), 1 deselected (`release_artifacts`). Against the eleventh round's 1002 passed, the 18 new tests in `test_phase3_review12.py` add no skip or xfail.
- **API suite, PostgreSQL 17** (a private scratch cluster; CI runs 16), each on a fresh database, on the same code: 1018 passed, 3 xfailed, 1 deselected with psycopg, and the same with pg8000 (production's driver, through the legacy interface its URL selects; `test_m1_*` ran production's `pg8000.dbapi.connect` interface in both runs). Rerun because the PostgreSQL tests and the `app.core.db` text changed. The first pg8000 run ended at 49% with a native access violation inside lxml while `test_phase2_acceptance.py` parsed a DOCX source (no Phase 3 code on the stack); the rerun on a fresh database passed.
- **Mutation checks** (local; each change undone afterwards): with `classify_pg8000_errors` removed from every engine, `test_m1_production_s_pg8000_interface_raises_plain_database_errors_and_the_engine_gives_psycopg_s_classes` and `test_m1_the_ledger_retries_a_real_duplicate_key_on_production_s_pg8000_interface` fail on PostgreSQL with both drivers (the duplicate key reaches the ledger as a `DatabaseError` and is not retried); a listener that reclassifies only `ProgrammingError` and `InternalError` wrappers passes every `test_c7_*` and fails all 12 cases of `test_m1_a_raw_pg8000_database_error_takes_the_class_psycopg_gives_its_sqlstate`; M24's earlier consequence text, or M24 with one of the four owner decisions dropped, fails both `test_m2_*` tests.

**Validators:** every CI step exits 0: `validate_corpus.py --check-public-assets --check-recall-stop`; `validate_lqs.py --allow-draft`; `config_package.py --check` (v2 2.0.0, sha256 `f35a4edf…`, unchanged, 8 schema pins; v1 1.0.0 `060c59f2…`); `authorization_matrix.py --check`; `replay_tutor_plans.py --check` (the record rewritten because the `app/core/db.py` text changed, which changes only its `inputs` hash: 0, 148 and 130 of 299 answered, 0 mismatches, two-pass ratio 1.0); `generate_manifest.py --check`; `validate_corpus.py --check-hashes --check-near-duplicates`; `calibrate_abstention.py --check`; `scan_boundary.py --repo` with both Docker contexts (path scan pass; its report written outside the repository).

**Frontend:** unchanged in this round, so not rerun. **Not run here:** `pip-audit` and `npm audit` (network; no dependency changed), the Docker image build and its scan, PostgreSQL 16 itself, and the provenance audit against production (a cloud job under D-05, DI-49).

**CI:** branch run 44676365093 (push) at `94aa3e6` passed every job. The commits from the tenth round on need their own run, and the exit needs a cited green run on `main` (DI-31).

### 18.4 Review history

The rows below record what each review round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative. Each finding is one line with the tests that fail if its defect comes back. The first round's findings are numbered; later rounds use letters (C for the second round to M for the twelfth; the twelfth round's M1 and M2 are findings, not the measured facts of 0.2). Each round's commit message lists its findings and every existing test it changed, with the reason. Earlier copies of this spec cite a round by its former section number (18.4 to 18.12), given in the first column.

| Round (former section) | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| 1, review fixes (18.4) | `dade4d3` (replay record `15b4793`) | 1. A budget overrun after generation read as a bound-claim stop; the claims count as `budget_exceeded`, in neither ratio term, and counts reconcile: `test_plan_l_a_budget_overrun_after_generation_is_a_latency_event_not_a_bound_claim_stop`<br>2. Bind locks the span's own sentence and the subset check compares whitespace forms, never NFKC: `test_tutor_retrieve_bind_lock.py`, `test_tutor_render_subset.py`<br>3. `admin` withdrawn from the ledger readers (PD-12): `test_ac_3_6_the_ledger_readers_are_the_plans_reviewer_role_only`<br>4. A sentence two overlapping spans hold is locked once, citing both; the subset check looks claims up by id: `test_ac_3_3_a_sentence_in_two_overlapping_spans_is_one_claim_and_the_honest_rendering_passes`<br>5. A field-level `exclude_if` keeps both chat response schemas in OpenAPI: `test_the_chat_response_schemas_keep_every_field_in_openapi`<br>6. Public `/ready` shows no head sequence number: `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`<br>7. The legacy append's wait is bounded as a whole (worker pool, statement timeout): `test_response_ledger.py`<br>8. The privacy row says what the ledger keeps: `apps/frontend/tests/evidence-panel.integration.test.ts`<br>9. `/evidence/spans` shares `/spans`' rate-limit window: `test_the_span_route_and_its_alias_share_one_rate_limit_window`<br>10. The replay record's `commit` is HEAD only on a clean tree, and `--write` refuses a dirty one: `test_ac_3_2_the_replay_record_names_its_commit_and_refuses_to_write_from_a_dirty_tree` |
| 2, C1-C12 (18.5) | `f974355` (replay record `b341e49`, verification `028cd40`) | C1 `license_class` is derived and a non-public span is never emitted: `test_c1_*`<br>C2 every `config.override` key is tested, with an AST scan for uncovered keys: `test_c2_*`<br>C3 the PD-11 values and budgets are package values, not code constants: `test_c3_*`<br>C4 ledger retention is an open decision, the package says retain, and no job deletes a row: `test_c4_*`<br>C5 the database rate-limit test waits for its instances robustly: `test_rate_limit.py`<br>C6 the demo-seed test is isolated: `test_demo_seed.py`<br>C7 pg8000 in CI, and pg8000 errors take psycopg's PEP 249 classes: `test_c7_*`<br>C8 `/qa/ask` is ledgered with its bytes unchanged: `test_c8_*`<br>C9 `Idempotency-Key` on `POST /tutor/turns`: `test_c9_*`<br>C10 sentence rule `sentences-v2`: `test_c10_*`<br>C11 a span link never mints a guest session in the proxy: `apps/frontend/tests/evidence-panel.integration.test.ts`<br>C12 a thread's message times are strictly ordered: `test_c12_*` |
| 3, D1-D15 (18.6) | `e0f230c` | D1 the shadow log line carries the plan L ratio terms: `test_d1_*`<br>D2 the task 3.3 reading is a recorded, unratified deviation: `test_d2_*`<br>D3 plan 12.8 quoted in full: `test_d3_*`<br>D4 a rendering with no claim, or an uncited claim, never answers, and the ledger records what was shown: `test_d4_*`, `test_tutor_render_subset.py`<br>D5 budget overrides are logged, stamped and on `/ready`: `test_d5_*`<br>D6 `flag_policy` and the route limits are marked provisional: `test_d6_*`<br>D7 ADR-005 and the spec say what the code does: `test_d7_*`<br>D8 a ledger check that overlaps appends reads the head first: `test_d8_*`<br>D9 public `/ready` holds no per-run shadow output: `test_d9_*`<br>D10 no unlinkability claim for Q&A records: `test_d10_*`<br>D11 the pydantic floor `exclude_if` needs: `test_d11_*`<br>D12 the required check `api-postgres` keeps its name over the driver matrix: `test_d12_*`<br>D13 the production ledger steps run through the worker, and a stalled append's lock is ended by the server: `test_d13_*`<br>D14 the evidence panel is a group with distinct passage links: `apps/frontend/tests/evidence-panel.integration.test.ts`<br>D15 the in-flight test no longer depends on a wall clock: `test_response_ledger.py` |
| 4, E1-E17 (18.7) | `65f56d1` (replay record `928abd4`) | E1 the record names the displayed spans, and a stale citation list never answers (rule v3): `test_e1_*`, `test_tutor_render_subset.py`<br>E2 the schema guard compares leaf constraints: `test_e2_*`<br>E3 the replay README and conflict 11 say what the record is: `test_e3_*`<br>E4 F-2 recorded: `test_e4_*`<br>E5 a rolled-back request is no ledger attempt: `test_e5_*`<br>E6 a lost record never reads as a legacy turn: `test_e6_*`<br>E7 an abandoned Idempotency-Key claim is released after its lease: `test_e7_*`<br>E8 the text-helper and subset-check docstrings: `test_e8_*`<br>E9 the migration names the worker: `test_e9_*`<br>E10 the absolute downgrade target in every stamp state, and Alembic through the Cloud SQL connector: `test_e10_*`<br>E11 the kill switch on the tutor surface: `test_e11_*`<br>E12 export, restore and tamper refusal: `test_e12_*`<br>E13 attempted lines, the surface field and the observability tables: `test_e13_*`<br>E14 conflict 29 and the privacy row: `test_e14_*`<br>E15 public `/ready` carries no shadow outcome: `test_e15_*`<br>E16 the abstention copy claims no coverage fact: `apps/frontend/tests/evidence-panel.integration.test.ts`<br>E17 the panel's contrast in both themes: `apps/frontend/tests/evidence-panel.integration.test.ts` |
| 5, F1-F16 (18.8) | `feb025f` | F1 delivered abstention by reason in the record, the attempted line and `/ready`: `test_f1_*`<br>F2 the replay record names its code by content and survives a squash merge: `test_ac_3_2_the_replay_inputs_check_needs_no_history_and_refuses_a_changed_or_missing_file`<br>F3 the Q&A evidence panel, development only: `test_f3_*`<br>F4 the package's rule ids and `flag_policy` defaults are compared with the code: `test_f4_*`<br>F5 the question-overlap threshold is a package value: `test_f5_*`<br>F6 PD-09 and `owner_decisions.D-12` say hold H6 blocks the provider interim path: `test_f6_*`<br>F7 the reader-role comment, the test strategy and the phase record: `test_f7_*`<br>F8 start-up's trigger guard never deadlocks a live append, and a deadlock is retried: `test_f8_*`<br>F9 the compose field stays readable in the light theme: `apps/frontend/tests/evidence-panel.integration.test.ts`<br>F10 start-up writes no ledger marker: `test_f10_*`<br>F11 every legacy attempt ends in one terminal line with its `attempt` id: `test_f11_*`<br>F12 each turn says whether it expects a record, so rollback-window turns are no lost records: `test_f12_*`<br>F13 a request past its Idempotency-Key lease cannot make a second turn: `test_f13_*`<br>F14 the forward Alembic step checks the stamp: `test_f14_*`<br>F15 the evidence-package records: `test_f15_*`<br>F16 the 11.4 event set equals the events the code logs: `test_f16_*` |
| 6, G1-G2 (18.9) | `6822206` | G1 no file that runs or checks the replay record asks git about history: `test_g1_*`, `test_ac_3_2_the_committed_record_check_passes_on_a_squash_merged_main_that_keeps_the_branch_objects`<br>G2 no record calls the D-19 generator the interim path hold H6 blocks: `test_g2_*` |
| 7, H1-H9 (18.10) | `e7909f0` | H1 binding rule `resolver-bundle-sentence-v2` refuses a span-edge fragment as `partial_sentence`: `test_h1_*`<br>H2 stepwise keeps two sentences of one span in source order: `test_h2_*`<br>H3 the package's pipeline version, component ids, header and plans are compared with the code: `test_h3_*`<br>H4 the record check runs no process: `test_h4_*`, `test_ac_3_2_the_record_check_and_a_replay_with_its_own_commit_run_no_process`<br>H5 one rate-limit window for a tutor turn: `test_h5_*`<br>H6, H7 the ledger records describe the current append, guard and coverage rules: `test_h6_*`, `test_h7_*`<br>H8 spec 7.17 names the replayed code by `inputs`: `test_h8_*`<br>H9 the status file counts the phase record's review rounds: `test_h9_*` |
| 8, I1-I8 (18.11) | `94d82fc` | I1 quotable spans with no whole sentence abstain as `no_whole_sentence`: `test_i1_*`<br>I2 every fault mode is placed as itself on a several-claim answer: `test_i2_*`<br>I3 spec section 3 and the 4.5 hash listing match the code: `test_i3_*`<br>I4 spec 3.4 and 7.13 give the ledger route's current rule: `test_i4_*`<br>I5 the registers and spec sections 6 and 16: `test_i5_*`<br>I6 spec 12 lists every production frontend change: `test_i6_*`<br>I7 the phase record and closure notes point at the latest run and pin: `test_i7_*`<br>I8 the test strategy names only tests that exist: `test_i8_*` |
| 9, J1-J8 (18.12) | `94aa3e6` | J1 a duplicate claim counts as bound in the plan L ratio, as a merged one does: `test_j1_*`<br>J2 the invariant 1 fixture compares the ClaimPlans and the whole shadow record: `test_j2_*`<br>J3 a renderer exception logs `tutor.two_pass.render_failed`, and a run whose every attempt raised abstains with `render_failed`: `test_j3_*`<br>J4 every exact fault test asserts what it placed: `test_j4_*`<br>J5 a turn whose append may still be running is `pending`, not `unrecorded`: `test_j5_*`<br>J6 the attempt horizon is derived from the code's own terms, the append queue included, and read by CPU allocation: `test_j6_*`<br>J7 the shadow budget source, the connection note and tests 28 and 39: `test_j7_*`<br>J8 the CI job, budget setting and Alembic step in sections 14 and 15: `test_j8_*` |
| 10, K1-K3 | `23cc281` (K1, K2); `79d8516` (K3) | K1 the invariant 1 fixture tells learners apart by the abstention reason, counts, floor, margin, sufficiency and `top_k`, and compares every field of the shadow record but its ids, `contains_learner_state` included: `test_k1_*`<br>K2 a new Cloud SQL connection is bounded by `app.core.db.CONNECT_TIMEOUT_S`, which the attempt horizon counts; the connector bounds none of it: `test_k2_*`<br>K3 the Phase 3 records state current behaviour: sections 0-17, the ADR revisions, the runbooks and the evidence package corrected in place, this table in place of per-round sections, the test strategy mapping every `test_phase3_*.py` file, and section 3 listed from the code: `test_k3_*` |
| 11, L1-L8 | `4283194` | L1 spec 4.12 lists the append's statements in the code's order, the `SET LOCAL`s before the `response_id` read: `test_l1_*`<br>L2 spec section 7 names every production file the phase changes and states `app/core/db.py`, the `_ExcludeIfProbe` refusal and the pydantic floor; 18.1 lists them: `test_l2_*`<br>L3 each Cloud SQL connection's socket gets TCP keepalive (a dead peer ends a read within 60 s; the 840 s dead-peer horizon); a server that never replies is stated as unbounded, and the runbook replaces the instance: `test_l3_*`<br>L4 spec 13.2 describes the retry test the file holds: `test_l4_*`<br>L5 the ADR-005 revision withdraws the overlap gate and keeps fail-closed abstention: `test_l5_*`<br>L6 spec 5.1 names the four owner decisions v2 adds: `test_l6_*`<br>L7 F-2's stand-in audit: package v2 pins the legacy path (`tutor_pipeline.legacy`), `ledger_provenance` and `--check-provenance` compare every record with the pins, and the records say what exists: `test_l7_*`<br>L8 spec 4.3, 4.5, 4.10 and 13.1 item 3 state the license-gate abstention, `top`, the budget checks and the mutation tests: `test_l8_*` |
| 12, M1-M2 | the commit after `4283194` (its message lists M1-M2) | M1 spec 7.19, 14 and 16, the `app/core/db.py` comment, the CI comment, the test strategy and DI-46 state production's pg8000 interface (the Cloud SQL connector's `pg8000.dbapi.connect`, which raises every server error as a plain `DatabaseError`, 23505 included) and CI's (the legacy `pg8000.connect`); a raw `DatabaseError` takes psycopg's class, and the ledger retries a real duplicate key on production's interface: `test_m1_*`<br>M2 spec 0.2 M24 names the four owner decisions v2 adds, as 5.1 does, and every line that says what v2 adds to `owner_decisions` names all four: `test_m2_*` |
