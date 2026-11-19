# QC+AI Studio — Phase 3 Implementation Spec (reviewed)
## Provenance-first two-channel tutor (plan L1225-1284)

Repository: `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`. Branch: `phase3/two-channel-tutor`, cut from `origin/main` `72f1b5e` (Phase 2 merged, PR #34).

Plan: `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`.
- Phase 3 block: L1225-1284.
- Architecture contracts: Section 7 (L811-983).
- What consumes Phase 3: Phase 4 (L1286-1355).

The implementer commits this spec as `docs/architecture/phase3-implementation-spec.md`. At the end it appends a section 18, "Implementation record", listing every refinement or departure, as Phase 2 did.

How to use this spec:
- Section 0 holds the binding rules, the measured facts, the readings of the ACs, and the adversarial-review corrections (0.4).
- Section 1 lists every conflict between the plan and the fixed decisions, with its resolution.
- Sections 2-5 cover the architecture, contracts, algorithms and configuration package v2.
- Sections 6-12 cover settings, file-by-file changes, the database, routes, start-up and `/ready`, and the frontend.
- Sections 13-17 cover tests, CI, docs and evidence, registers, and the order of work.

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (restated)

**Repository and git**
- Stay on the branch: no branch switch, no `git stash`, no push, no git-config change, no history rewrite.
- Every commit message ends with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only in the scratchpad, never in the repository root. Ledger exports (`verify_ledger.py --export`) are written outside the repository.
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
| M2 | **Extractive prototype**, for each eligible document span: whitespace-normalised sentences split on `(?<=[.!?])\s+`, at least 4 words, sharing at least 1 package-tokenizer content term with the question; at most 2 per span and 3 in all; no fallback sentence.<br>• Answers 166/174 (`bm25f-v1`) and 146/174 (`p1-floor`), equal to the legacy rate.<br>• 2.89 and 2.77 claims per answer.<br>• Claim length p50 221 / 281 chars, max 699; 0 of 2299 dev document sentences exceed 1000 chars.<br>• The off-topic and stopword fixture (124): 0 results in every configuration.<br>• Retrieval plus selection: p50 0.97 ms / p95 1.3 ms (`bm25f-v1`); 6.1 / 11.0 ms (`p1-floor`). | The D-19 generator never lowers the answer rate against the legacy path. A shadow run costs milliseconds. |
| M3 | Top score within the margin (`near_miss`): 1 of 174 in-domain queries (`bm25f-v1`, dev). Under `p1-floor` the margin is 0, so there is never a near_miss. | `near_miss` is rare. It is recorded; it never abstains (section 4.3). |
| M4 | **Index sizes.** Dev: 1071 spans (1030 document, 41 authored), 331 index entries, `corpus-c658893abb6440dd`. Governed empty: 41 spans and 41 entries, all authored. All-approved: the same corpus_version as dev. The API image holds no DOCX (deployment runbook), so in production only authored spans exist. | Positive-path tests run on dev or all-approved. Governed empty and the production image abstain everywhere. |
| M5 | `TutorMessage.created_at` uses `server_default=func.now()`. SQLite stores whole seconds; a Python-set value keeps microseconds. PostgreSQL `now()` is the transaction start time. | Order within a thread is ambiguous within one second on SQLite, and within one transaction on PostgreSQL. Section 7.11 sets message timestamps in Python under a thread lock, never earlier than the thread's latest message (`next_message_time`, 18.5 C12): a production change to stored data that ships only with a D-05 release. |
| M6 | `app/services/claim_gate.py` (the overlap `ClaimGate`, `evidence_digest`) is imported by no runtime module and no test. Only ADR-005 and the CS595 blueprint name it. | Safe to repurpose as the subset checker (plan E). |
| M7 | Roles in code are `learner`, `instructor` and `admin` (`require_role`, STAFF). There is no `reviewer` role. Auth0 roles come from the token claim; demo roles come from `x-demo-role` in development. | Ledger readers are `("reviewer",)`, the plan text (section 9; PD-12, revised in 18.4). |
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
| M24 | Package v1 top-level keys: `package, package_version, schema_version, phase, status, created, span_identity, corpus_version, gates, retrieval, semantic, abstention, near_duplicate, legacy_citations, owner_decisions, boundary`; `owner_decisions` holds `D-17, D-30, Q-10, PLAN-11.3`. | v2 copies every block; `owner_decisions` keeps those four unchanged and adds D-19 and D-12 (5.1). |
| M25 | Route handlers call `get_settings()` directly (`spans.py`); `app.dependency_overrides[get_settings]` reaches only `Depends(get_settings)` (for example `get_current_user`). | Route-flag tests monkeypatch the route module's `get_settings` (Phase 2 precedent), never `dependency_overrides` (test 26). |

### 0.3 Readings

**R-a. "Delivery" in Phase 3.**
- Every learner delivery is the legacy contained answer. The ledger records it with `delivery = "legacy"` and `response_id = TutorTurn.id`.
- Every shadow run is recorded with `delivery = "shadow"` and `response_id = "shadow-<uuid4>"`, linked by `shadowed_response_id = TutorTurn.id`.
- `delivery = "delivered"` (two-pass output delivered to a learner) is reserved for Phase 4: it exists in the schema, the DB check constraint and the package, but `TwoPassPipeline.run` **refuses** it while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (`DeliveryNotImplemented`). No Phase 3 code path returns two-pass text to any caller (13.6, invariant 6).

**R-b. AC-3-4** ("Given any delivered test response, then its ledger record exists and the chain verifies") is tested on:
1. every `/assistant/chat` and `/tutor/turns` response in the test (legacy records);
2. their shadow records.
After both, `verify_response_ledger` reports `ok`. Coverage of real deliveries is measured by `verify_ledger.py --coverage-since` and the `legacy_coverage_rate` SLI.

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

### 0.4 Review corrections applied (cross-reference for the implementer)

The draft was revised for: production response bytes (conflict 28); no unverified delivery path (R-a, conflict 31); bounded legacy append (conflict 29); start-up fatality only when the pipeline is requested (conflict 30, 5.4); StaticPool-safe concurrency tests (M17); explicit insert-then-update order (4.12); verbatim (non-NFKC) claim text and sentence-aligned binding (conflict 32); lexical-only shadow retrieval (conflict 33); a faithful legacy retrieval record (M20); `owner_decisions` extension (5.1); work order for prompt hashes (17); non-vacuous license tests (test 34); header-subset equality (test 23); route-flag tests by monkeypatch (test 26); a `qcai.tutor` logger (M23); off-DB record hashes in logs (11.4); privacy disclosure and retention (15, 16); `entry_schema` dispatch in verify (4.12); trigger `TG_OP` checks (8.2); Alembic CLI syntax (8.3); a local pg8000 run (17); and several cuts (section 18 seed).

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
- **Resolution:** `LEDGER_READER_ROLES = ("reviewer",)` in `app/core/authorization.py`: the plan's own reader, nothing wider. The draft's `admin` widened the plan text and was withdrawn on review (18.4, PD-12 revised): any other role, admin included, reads only its own turns. Each reviewer read records `ledger.reviewer_read` per 7.6 (L937): "reviewer access is logged". Provisioning reviewers is Phase 6 (DI-38).

**6. "daily digest exported off-DB" (7.5, L915).**
- A scheduled export is a cloud write and is deferred (DI-33).
- **Resolution:** every append logs its `seq` and `record_hash` (no learner data) to the platform log, as the security log mirrors `seq` and `hash`: the platform log is a continuous off-DB copy of the chain. The in-image worker `python -m app.workers.response_ledger` verifies the chain and logs the head. `verify_ledger.py --expect-head SEQ:HASH` checks the chain against any logged head.

**7. ClaimLedgerEntry `text` (7.4) vs "no learner text" (E3).** Resolved as R-e.

**8. Plan 3.1 / 7.4 "replaces the heuristic resolver [E-44]" vs E2 "the legacy path keeps working".**
- `thread-resolver-v1` replaces the word-count heuristic on the two-pass path. `TutorOrchestrator._resolve_query` stays on the legacy path (changing it would change what learners receive). The heuristic is removed when the two-pass path delivers (Phase 4, DI-41).

**9. Plan 13.5 (L2360): "every ledger row stamps code SHA, alembic revision, corpus manifest hash, prompt hashes for both L5 passes (F-1), pinned model ids (generator, V1.3 checker, V2 verifiers), MCP contract version and config hash".**
- **Resolution:** `LedgerEntry.versions` holds `code_sha` (`GIT_SHA`), `schema_revision_expected` (the code constant `ledger.SCHEMA_REVISION`, tested against the Alembic head; it names the revision the code expects, not a value read from `alembic_version`, which a `create_all` database may lack, M13), `manifest_sha256`, `config_package_version`, `config_package_sha256` and `span_scheme`. `provenance` holds both prompt hashes and `generator_model_id`. `v1_3_checker_model_id`, `panel_weights_version`, `routing_table_version` and `tool_contract_version` are explicit nulls. V2 verifier ids are Phase 5 additive fields (plan Phase 4 G: "Additive ledger fields").

**10. Plan 3.6 "sole learner-tool user [E-76]".**
- No learner tools exist before Phase 8. **Resolution:** the renderer is the only component whose signature accepts a `PresentationPlan`; in Phase 3 it comes from request hints only (`/tutor/turns presentation_plan`, otherwise the package default). AC-3-1 scans that no `tutor_pipeline` module imports a learner module.

**11. Plan L (L1274) "Stop if bound-claim ratio falls below Phase 2".**
- Phase 2 defined no such SLI. **Resolution:** the baseline is measured at 1.0 (M1) and pinned in the package (`tutor_pipeline.stop.phase2_bound_claim_ratio`). The replay report and `/ready` report the two-pass ratio beside the baseline. A null ratio (no claims proposed) is never a stop. `scripts/replay_tutor_plans.py` exits 3 when a non-null two-pass ratio is below the baseline.

**12. Plan H "Public-corpus spans only".**
- Production shadow would process real learner questions. **Resolution:** shadow is off outside development; production enablement is deferred (DI-32). The replay and every test use public fixtures and public-plane spans only.

**13. "/evidence/spans/{span_id} (public license_class only)" with no `license_class` in the code.**
- **Resolution:** `license_class` is derived, never labelled (revised in 18.5 C1): `CorpusRegistry.license_class` gives `"public"` only when the span record's own plane is public and the manifest does not put its item or file on another plane; a span whose class is not public is never emitted (left out of the bundle and the legacy record, counted; the span routes answer 404). The field is on `SpanResolution` and `EvidenceSpan`. The license gate is tested with a private-plane fixture (test 34) and with forced non-public records (18.5 C1), not by the type.

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

**22. Plan G "Reversible migration" vs append-only evidence (R-22).** **Resolution:** the Alembic downgrade refuses while `response_ledger` holds rows, unless run as `alembic -x allow_ledger_drop=true downgrade -1` after `scripts/verify_ledger.py --export`.

**23. 3.2 "Retrieval request = resolved text, lesson scope, corpus_version".** The client's `top_k` is a request field. **Resolution:** `RetrievalRequest` has exactly those three fields; depth is `tutor_pipeline.retrieval.top_k` (4) from the package.

**24. E5 "evidence panel" vs E9 "evidence-panel production rollout deferred".** **Resolution:** the API adds `evidence` only when `EVIDENCE_PANEL_ENABLED` (`None` = on in development, off elsewhere); the frontend renders the panel only when `evidence` is present.

**25. Task 1.11 (L1095): "a "lexically screened" label MAY accompany only that contained output".** **Resolution:** the panel's `lexically_screened` label appears only when `decision == "answer"` on the legacy contained answer; never on two-pass output.

**26. AC-3-5 "references only thread-A turns".** `TutorTurn` rows do not link to their message. **Resolution:** `source_turn_ids` are the user `TutorMessage` ids (R-d). No column is added to `tutor_turns`.

**27. E4 "guests get 403/404 consistently with the authorization matrix".** `GET /ledger/responses` is `PRINCIPAL` + `OWNER`; anonymous callers get 401 (matrix rule); a guest who is not the owner gets the same 404 as a missing id; a guest owner reads their own non-shadow record when the route is enabled; shadow ids are 404 for every non-reviewer. `scripts/authorization_matrix.py` needs no code change; the doc is regenerated.

**28. "Byte-identical" production responses vs a new response field.**
- Adding `evidence: EvidencePanel | None = None` to `AssistantChatResponse` would put `"evidence": null` into every production response.
- **Resolution:** `AssistantChatResponse.evidence` is `Field(default=None, exclude_if=lambda value: value is None)`, which omits the key when it is None; every other key serialises as today. Test 38 pins the production key set and body. The draft's wrap `model_serializer` erased both chat response schemas in `/openapi.json` (a free-form object); a field-level `exclude_if` keeps them (18.4).

**29. E1 "never ... delays the learner's legacy response beyond a bounded budget" vs a synchronous legacy append.**
- **Resolution:** the legacy append runs synchronously after the turn commits (so the record exists before the answer leaves) but under a total deadline `TUTOR_LEDGER_APPEND_BUDGET_MS` (default 1500): at most 3 attempts; each PostgreSQL attempt first sets `lock_timeout` and `statement_timeout` to the remaining budget; only `IntegrityError` is retried; any other error (lock or statement timeout, busy, trigger refusal) fails open at once. Neither timeout bounds the checkout of a pooled connection or a new Cloud SQL connection, so the append runs on a small worker pool (4 threads, at most 16 appends in flight; past that an append is refused at once and counted) and the request waits for it at most the budget plus 250 ms (`LEGACY_WAIT_GRACE_MS`). An append still running then finishes in the background and is counted when it ends (`tutor.ledger.append_deferred`). That is the worst-case added latency on every dialect (18.4). SQLite (development and tests) keeps the driver's busy timeout.

**30. Start-up checks for a feature that is off.**
- **Resolution:** at start-up `check_tutor_pipeline_package(package, structural=False)` verifies schema file hashes and prompt hashes (deterministic from code and package). A governed build stops on a problem only when `TWO_PASS_TUTOR != "off"`; otherwise it logs `tutor.two_pass.unavailable`, reports `tutor_pipeline.available: false` in `/ready`, and keeps `effective_mode` off. The pydantic structural comparison (`structural=True`) runs in tests and `config_package.py --check` (CI) only, because the image's pydantic version is not pinned (M21).

**31. Plan 7.2 "[L7 ledger append] --> DELIVER" vs invariant 6 and 13.6.**
- **Resolution:** Phase 3 has no delivered two-pass path (R-a). The ledger-before-delivery order is Phase 4's, behind V1. The pipeline's refusal of `delivered` is tested (test 12).

**32. D-19 "verbatim" vs comparison normalisation; and the binding rule.**
- **Resolution:** claim text stored, locked, ledgered and rendered is the whitespace-normalised verbatim sentence of the span (`whitespace()`), never the generator's text: bind locks the span's own sentence that the normalised claim matched, and the subset check requires the rendered text to equal the locked text, whitespace runs aside. NFKC (`normalise()`) is used only to find the matching sentence (M22; 18.4). The Phase 3 binding rule `resolver-bundle-sentence-v1` requires the normalised claim to equal a whole `sentences-v1` sentence of every cited span, so no generator can bind a truncated sentence that drops a qualification or negation (R-16 class). Plan M's residual "misleading wording within locked claims" for sentence splits at abbreviations is closed by `sentences-v2` (18.5 C10): 1 of 2177 dev sentences still ends at an initial (a bibliography line), against 49 of 2199 under `sentences-v1`.

**33. Provider egress from the shadow (D-12, D-23, R-10).**
- `RetrievalEngine._search` could call the OpenAI embeddings backend if semantic retrieval were ever aligned in the API process; the shadow would send the resolved text (possibly two learner turns) to a provider.
- **Resolution:** `RetrievalEngine.evidence()` is lexical only (`store.evaluate`), whatever `SEMANTIC_RETRIEVAL_ENABLED` says; `retrieval_mode` is always `"lexical"` in Phase 3 bundles.

---

## 2. Architecture

```
POST /assistant/chat | POST /tutor/turns (dev)
   └─ TutorOrchestrator.chat  (legacy, unchanged containment, D-19)
        ├─ TeachingAssistantService.chat → contain_answer → learner response  ── delivered (legacy)
        │     (response._retrieval = RetrievalResponse, never serialised)
        └─ response._followups = TurnFollowups(legacy=LegacyDelivery?, shadow=ShadowJob?)
   route: db.commit()
        ├─ record_legacy_delivery(legacy)   sync, own session, ≤ TUTOR_LEDGER_APPEND_BUDGET_MS, fail-open → response_ledger
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

All new contracts live in `apps/api/app/services/tutor_pipeline/contracts.py`. Each subclasses:

```python
class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

Collections are tuples. The regexes are:
```python
SPAN_ID = r"^span-[0-9a-f]{64}$"
HEX64 = r"^[0-9a-f]{64}$"
CLAIM_ID = r"^claim-[0-9a-f]{32}$"
RESPONSE_ID = r"^(turn|shadow)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
```

### 3.1 Evidential channel

```python
class ResolverRef(Contract):
    model_id: str                      # "thread-resolver-v1"
    prompt_hash: str = Field(pattern=HEX64)

class ResolvedQuestion(Contract):      # plan 7.4
    text: str = Field(min_length=1, max_length=4001)
    resolver: ResolverRef
    source_turn_ids: tuple[str, ...] = Field(min_length=1, max_length=2)
    contains_learner_state: Literal[False] = False

class RetrievalRequest(Contract):      # plan 3.2: exactly these three fields
    text: str = Field(min_length=1, max_length=4001)
    lesson_slug: str | None = Field(default=None, max_length=255)
    corpus_version: str = Field(min_length=1, max_length=64)

class EvidenceSpan(Contract):          # plan 7.4 spans[]
    span_id: str = Field(pattern=SPAN_ID)
    item_id: str
    item_version: str
    kind: Literal["document", "authored"]
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    content_hash: str = Field(pattern=HEX64)
    score: float | None                # None only on legacy records without a retrieval side channel
    near_floor: bool
    license_class: Literal["public"]
    quotable: bool                     # D-19: public-plane, bound, indexable document (section 4.4)

class Sufficiency(Contract):
    score: float | None                # top score; None when no result
    gate: Literal["p1-floor", "bm25f-v1"]
    threshold_version: str
    floor: float
    margin: float
    decision: Literal["answer", "abstain", "near_miss"]
    reason: str                        # "evidence" | the gate's abstention reason | "corpus_version_mismatch"

class EvidenceBundle(Contract):
    bundle_schema: Literal["evidence-bundle-v1"] = "evidence-bundle-v1"
    corpus_version: str
    index_version: str
    retrieval_mode: Literal["lexical"] # Phase 3: lexical only (conflict 33)
    spans: tuple[EvidenceSpan, ...] = Field(max_length=12)
    sufficiency: Sufficiency
    conflicts: tuple[str, ...] = ()    # validator: must be empty in Phase 3 (V1.7 is Phase 4)

class EnvelopeSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    text: str = Field(min_length=1)    # the span's own text from the span registry

class EvidentialInstructions(Contract):
    rule_id: str                       # generator id
    prompt_hash: str = Field(pattern=HEX64)
    max_claims: int = Field(ge=1, le=10)
    max_claims_per_span: int = Field(ge=1, le=10)
    min_sentence_words: int = Field(ge=1, le=50)

class EvidentialEnvelope(Contract):    # the "evidential prompt" (F-2)
    envelope_schema: Literal["evidential-envelope-v1"] = "evidential-envelope-v1"
    question: str = Field(min_length=1, max_length=4001)   # == RetrievalRequest.text
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
    span_ids: tuple[str, ...] = Field(default=(), max_length=8)  # empty → dropped "unbound"

class ClaimPlan(Contract):
    plan_schema: Literal["claim-plan-v1"] = "claim-plan-v1"
    generator: GeneratorRef
    claims: tuple[ProposedClaim, ...] = Field(max_length=20)

class LockedClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    text: str                          # verbatim, whitespace-normalised (section 4.1); never NFKC-folded
    span_ids: tuple[str, ...] = Field(min_length=1)        # sorted, unique
    source_order: tuple[str, int]      # (item_id, char_start) of the first span id in sorted order

class ConfigStamp(Contract):
    version: str
    sha256: str = Field(pattern=HEX64)

class LockedClaimSet(Contract):
    lock_schema: Literal["locked-claim-set-v1"] = "locked-claim-set-v1"
    claims: tuple[LockedClaim, ...]    # may be empty (abstention before or at binding)
    span_ids: tuple[str, ...]          # sorted union of the claims' span_ids
    corpus_version: str
    index_version: str
    generator: GeneratorRef | None     # None when abstaining before generation
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str       # the renderer registry hash (conflict 1)
    resolver: ResolverRef
    config_package: ConfigStamp
    claim_set_hash: str = Field(pattern=HEX64)
    # model_validator: span_ids == sorted(union); claim ids unique; claim_set_hash == lock_hash(self)
```

`lock_hash(s) = sha256(ledger_canonical(s.model_dump(mode="json", exclude={"claim_set_hash"})))`. A copy made with `model_copy(update=...)` skips validation, so the renderer, the subset check and the ledger call `verify_locked(locked)`, which recomputes the hash and raises `LockedClaimSetTampered` on a mismatch. The lock holds no learner, request or commit value.

### 3.2 Pedagogical channel

```python
class PresentationPlan(Contract):
    plan_id: Literal["concise", "stepwise", "socratic"]
    source: Literal["request", "default"]

class Segment(Contract):
    kind: Literal["connective", "question", "claim", "citation"]
    line: int = Field(ge=0)
    text: str                          # no "\n"
    template_id: str | None = None     # connective/question/citation
    params: tuple[int, ...] = ()       # integer template parameters only
    claim_id: str | None = None        # claim
    span_id: str | None = None         # citation

class RenderedResponse(Contract):
    renderer_id: str                   # "template-renderer-v1"
    plan_id: str
    attempt: int = Field(ge=1, le=3)
    segments: tuple[Segment, ...]      # ordered by (line, position); lines contiguous from 0
    citations: tuple[str, ...]         # unique span ids by first appearance
    text: str
```

### 3.3 Ledger entry (`ledger-entry-v1`)

```python
class Provenance(Contract):            # plan 7.4 provenance
    generator_model_id: str            # the configured generator's model id (legacy: EXTRACTIVE_MODE);
                                       # counts.proposed_claims == 0 shows it was not called
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str | None
    v1_3_checker_model_id: None = None
    corpus_version: str
    threshold_set_version: str
    panel_weights_version: None = None
    routing_table_version: None = None
    tool_contract_version: None = None

class ClaimLedgerEntry(Contract):      # plan 7.4
    claim_id: str = Field(pattern=CLAIM_ID)
    response_id: str = Field(pattern=RESPONSE_ID)
    text: str
    span_ids: tuple[str, ...] = Field(min_length=1)
    entailment_score: None = None
    locked: Literal[True] = True
    provenance: Provenance

class ResolvedQuestionRef(Contract):   # no text (R-e)
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
    evidence_scope: Literal["retrieved", "delivered_citations"]  # legacy without the side channel: delivered only
    sufficiency: Sufficiency | None    # None on legacy records
    evidence: tuple[EvidenceSpan, ...]

class PresentationRecord(Contract):
    plan_id: str
    source: str
    renderer_id: str
    attempts: int = Field(ge=1, le=3)
    subset_check: Literal["passed", "failed"]

class VersionStamps(Contract):
    pipeline_version: str              # "two-pass-v1" | "legacy-contained-v1"
    code_sha: str
    schema_revision_expected: str      # ledger.SCHEMA_REVISION (conflict 9)
    config_package_version: str
    config_package_sha256: str
    manifest_sha256: str | None
    span_scheme: str
    policy_version: str                # settings.grounding_policy_version
    resolver_id: str | None
    generator_id: str | None
    renderer_id: str | None

class PipelineCounts(Contract):
    proposed_claims: int
    bound_claims: int
    dropped: dict[str, int]            # unbound|outside_bundle|unresolvable|not_quotable|not_verbatim|duplicate (binding failures);
                                       # merged|budget_exceeded (not failures); unresolved_citation (legacy). Reconciles (18.4):
                                       # proposed_claims == bound_claims + sum(dropped), bound_claims == len(claims)
    render_attempts: int

class LedgerEntry(Contract):
    entry_schema: Literal["ledger-entry-v1"] = "ledger-entry-v1"
    response_id: str = Field(pattern=RESPONSE_ID)
    delivery: Literal["shadow", "delivered", "legacy"]
    shadowed_response_id: str | None
    pipeline: Literal["two-pass-v1", "legacy-contained-v1"]
    decision: Literal["answer", "abstain"]
    abstention_reason: str | None
    resolved_question: ResolvedQuestionRef | None   # None on legacy records
    retrieval: RetrievalRecord
    claim_set_hash: str | None         # None on legacy records
    claims: tuple[ClaimLedgerEntry, ...]
    span_ids: tuple[str, ...]
    presentation: PresentationRecord | None
    rendered_text_sha256: str | None
    provenance: Provenance
    versions: VersionStamps
    verification: None = None          # no V1/V2/V3 verdict before Phase 4: read as "no-verdict"
    counts: PipelineCounts
```

`LedgerEntry` model validator:
- `delivery == "shadow"` iff `response_id` starts with `shadow-` and `shadowed_response_id` matches `^turn-`;
- `legacy` and `delivered` require a `turn-` id and `shadowed_response_id is None`;
- `delivered` is refused while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (no Phase 3 code builds one);
- `decision == "abstain"` iff `abstention_reason` is set;
- `decision == "answer"` requires claims and `rendered_text_sha256`;
- `span_ids == sorted(union(claim.span_ids))`;
- every `claim.response_id == response_id` and `claim.provenance == provenance`;
- `abstention_reason ∈ ABSTENTION_REASONS ∪ {"no_approved_span"}` (the legacy reason).

```python
ABSTENTION_REASONS = ("no_query_terms", "no_match", "insufficient_coverage", "below_floor", "corpus_version_mismatch",
                      "no_quotable_evidence", "claim_plan_invalid", "no_claims", "no_bound_claims",
                      "subset_check_failed", "budget_exceeded")
LEARNER_STATE_FIELDS = ("mastery", "mastery_band", "band", "preference", "preferences", "user_id", "learner_id",
                        "guest_id", "account_id", "email", "history", "page_path", "pedagogical_context",
                        "learner_state", "profile", "quiz_attempts", "notes", "cursor", "target_role", "focus_area",
                        "self_ratings", "preferred_pace", "presentation", "presentation_plan", "plan_id", "thread_id")
SCHEMA_MODELS = {"ResolvedQuestion": ResolvedQuestion, "RetrievalRequest": RetrievalRequest,
                 "EvidenceBundle": EvidenceBundle, "EvidentialEnvelope": EvidentialEnvelope, "ClaimPlan": ClaimPlan,
                 "LockedClaimSet": LockedClaimSet, "PresentationPlan": PresentationPlan, "LedgerEntry": LedgerEntry}
ENTRY_SCHEMAS = {"ledger-entry-v1": LedgerEntry}   # verify dispatches on entry_schema; Phase 4 adds v2
```

(`ledger_write_failed` is not an abstention reason in Phase 3: there is no delivered two-pass path; a failed shadow append is a counted failure, a failed legacy append a counted coverage gap.)

### 3.4 API additions (`app/schemas.py`)

```python
class EvidenceSpanLink(BaseModel):
    span_id: str
    label: str                       # f"{source_title} — {section_title}"
    resolvable: bool                 # settings.span_resolver_route_enabled

class EvidencePanel(BaseModel):      # task 3.8, labels only
    panel_schema: Literal["evidence-panel-v1"] = "evidence-panel-v1"
    decision: Literal["answer", "abstain"]
    labels: list[Literal["lexically_screened"]] = Field(default_factory=list)
    degraded: list[Literal["extractive_only", "retrieval_fallback", "citations_provisional"]] = Field(default_factory=list)
    spans: list[EvidenceSpanLink] = Field(default_factory=list)
    verdict: Literal["no-verdict"] = "no-verdict"
```

`AssistantChatResponse` gains:
- `evidence: EvidencePanel | None = None`, omitted from serialisation when None by a wrap `model_serializer` returning `dict[str, Any]` (conflict 28);
- `_followups: Any = PrivateAttr(default=None)` and `_retrieval: Any = PrivateAttr(default=None)`: never serialised. Typed `Any` to avoid an import cycle.

```python
class TutorTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")           # AC-3-1 at the API boundary
    message: str = Field(min_length=1, max_length=2000)  # validator as AssistantChatRequest.validate_message
    thread_id: str | None = Field(default=None, min_length=8, max_length=64)
    lesson_slug: str | None = Field(default=None, max_length=255)
    presentation_plan: Literal["concise", "stepwise", "socratic"] | None = None

class TutorTurnResponse(AssistantChatResponse):
    delivery: Literal["legacy"] = "legacy"              # Phase 4 adds "delivered"

class LedgerClaimRead(BaseModel): claim_id: str; text: str; span_ids: list[str]
class LedgerRecordRead(BaseModel):
    response_id: str; delivery: str; decision: str; abstention_reason: str | None; created_at: datetime
    claim_set_hash: str | None; span_ids: list[str]; claims: list[LedgerClaimRead]; retrieval: dict
    presentation: dict | None; provenance: dict; versions: dict; resolved_question: dict | None
    # reviewers only (None for owners, so a learner never learns global chain position or traffic volume):
    seq: int | None = None; prev_hash: str | None = None; record_hash: str | None = None
    entry_sha256: str | None = None; shadowed_response_id: str | None = None
class LedgerResponseRead(BaseModel):
    response_id: str
    verdict: Literal["no-verdict"] = "no-verdict"       # plan G: legacy turns marked no-verdict
    recorded: bool
    legacy_turn: bool                                   # a pre-ledger turn, reported at read time
    record: LedgerRecordRead | None = None
```

`SpanResolution` gains `license_class: Literal["public"] = "public"` (additive; the route is off outside development).

---

## 4. Algorithms

### 4.1 Text helpers (`tutor_pipeline/text.py`)

```python
def normalise(text: str) -> str:            # comparisons only (bind, subset check)
    return " ".join(unicodedata.normalize("NFKC", text).split())
def whitespace(text: str) -> str:           # the verbatim surface that is stored, locked and rendered
    return " ".join(text.split())
SENTENCE_RULE = "sentences-v2"                # 18.5 C10; it replaced sentences-v1, which split after every ". "
def split_sentences(text: str) -> list[str]:  # boundaries after . ! ?, never after an abbreviation, an initial or
    ...                                       # before a lowercase word (text.py docstring)
def sentences(text: str, *, min_words: int, max_chars: int) -> list[str]:   # both from the package
    return [s for s in split_sentences(text) if len(s.split()) >= min_words and len(s) <= max_chars]
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
- `spans` are built from `response.results`, joined with `store.span_registry.get(span_id)` for kind and offsets; `quotable = span_is_quotable(record, registry)`.
- `floor, margin, threshold_version = store.index.thresholds`.
- **Sufficiency**
  - No results: `abstain`, reason `response.reason`.
  - Otherwise `top` = the top-ranked result (lexical results are score-descending). Decision `near_miss` when `top.near_floor` (the gate's own flag; never re-derived from rounded scores), else `answer`. `score = top.score`. Reason `"evidence"`.
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
EXTRACTIVE_RULE = ("D-19 extractive mode: each claim is one verbatim sentence (sentences-v1) of an approved, "
                   "public-plane document span in the envelope that shares at least one content term with the "
                   "question; at most {max_claims_per_span} per span and {max_claims} in all, in evidence order.")
def evidential_prompt_hash(params) -> str:
    return canonical_sha256({"id": "extractive-d19-v1", "rule": EXTRACTIVE_RULE, "sentence_rule": "sentences-v1",
        "max_claims": params.max_claims, "max_claims_per_span": params.max_claims_per_span,
        "min_sentence_words": params.min_sentence_words, "max_sentence_chars": params.max_sentence_chars})
```

No provider class exists in Phase 3 (D-12 open, hold H6): the Protocol is the interface, and `get_generator` refuses any id outside `WIRED_GENERATORS`.

**`build_envelope`**
- `evidence` holds the bundle spans with `quotable` true, in bundle order, each with the span registry's text.
- If none are quotable, return `None`; the pipeline abstains with `no_quotable_evidence`. Non-quotable span text never reaches a generator (D-19, D-31).

**`ExtractiveD19Generator.propose`**
- `q = content_terms(envelope.question)`.
- For each envelope span, in order: candidates are the `sentences_v1(span.text)` whose `content_terms ∩ q` is non-empty; take the first `max_claims_per_span`; stop at `max_claims`.
- Each claim is `ProposedClaim(text=whitespace(sentence), span_ids=(span.span_id,))`.

**Wrapping.** A generator exception, or a `ValidationError` when the result is coerced with `ClaimPlan.model_validate(...)`, abstains with `claim_plan_invalid`. Zero claims abstain with `no_claims`.

### 4.6 Bind (`tutor_pipeline/bind.py`; binding rule `resolver-bundle-sentence-v1`)

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
| `normalise(text)` is not equal to `normalise(s)` for some `s in sentences_v1(span.text)` of **every** cited span (no entailment checker exists before Phase 4) | `not_verbatim` |
| the cited spans hold the matching sentence in different characters | `not_verbatim` |
| the same sentence was already bound on every span it cites | `duplicate` |
| the same sentence was already bound on other spans | `merged` (not a failure: its spans join that claim's, 18.4) |

A claim is never re-bound to a span it did not cite. Phase 1's overlap rebinding is gone (plan 3.4, R-13). The draft keeps the span's own sentence (`whitespace()` form) as the claim text, never the generator's text (conflict 32). One sentence can sit in two adjacent spans (the splitter overlaps chunks by 120 characters), and the extractive generator then proposes it once per span: the merge locks it once, citing both spans, each of which holds it verbatim.

`claim_id = "claim-" + sha256(ledger_canonical({"text": normalise(text), "span_ids": sorted(span_ids)}))[:32]`: content-addressed, identical across plans and responses.

### 4.7 Lock (`tutor_pipeline/lock.py`)

```python
def lock(drafts, *, bundle, generator: GeneratorRef | None, evidential_prompt_hash: str | None,
         pedagogical_prompt_hash: str, resolver: ResolverRef, package: ConfigPackage) -> LockedClaimSet
def verify_locked(locked: LockedClaimSet) -> None
```

`source_order = (item_id, char_start)` of the first span id in sorted order.

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

### 4.9 Subset check (`app/services/claim_gate.py`, repurposed; rule `segment-exact-normalised-v1`)

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
| `unmapped_factual_sentence` | a claim segment whose `claim_id` names no locked claim, or whose `whitespace(text)` differs from that claim's text (never NFKC-folded: a rendering that turns `x²` into `x2` changes what a learner reads). Claims are looked up by id, so two claims with one sentence both map (18.4). |
| `unmapped_factual_sentence` | a connective or question segment with an unknown `template_id`, a wrong kind, or `text != template.format(*params)`. Untyped text in a non-factual slot is treated as factual. |
| `duplicate_claim` | a locked claim is rendered twice |
| `citation_outside_locked_set` | a citation `span_id` not in `locked.span_ids`, or `set(rendered.citations) - set(locked.span_ids)` is non-empty |
| `citation_not_on_claim` | a citation on a line with no mapped claim, or a span not in that claim's span_ids |
| `citation_marker_mismatch` | marker text other than `"[{index+1}]"` |

- `passed = not problems`. `missing_claims` is reported, not failed (plan 3.7 requires a subset only).
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

**`run`, step by step.** `item.delivery != "shadow"` raises `DeliveryNotImplemented` while `TWO_PASS_DELIVERY_IMPLEMENTED` is False (R-a). A budget check (`elapsed > budget_ms` abstains with `budget_exceeded`) runs after each of steps 2, 4, 5 and each render attempt.
1. `request = build_request(item.resolved, lesson_slug=..., corpus_version=store.corpus_version)`.
2. `bundle = retrieve(...)`. If the sufficiency decision is `abstain`, abstain with its reason.
3. `envelope = build_envelope(...)`. None abstains with `no_quotable_evidence`.
4. `plan = generator.propose(envelope)`, guarded; on error abstain with `claim_plan_invalid`; zero claims abstain with `no_claims`.
5. `result = bind(...)`. No bound claims abstain with `no_bound_claims`.
6. `locked = lock(...)`. Always runs, so `claim_set_hash` exists for every two-pass response.
7. **Render loop.** For `attempt` in `1..1+max_regenerations`, render and check the subset; stop on the first pass. If none passes, abstain with `subset_check_failed` (`rendered=None`; the locked claims are kept in the entry, withheld).
8. `entry = build_two_pass_entry(...)`, `rendered_text_sha256 = sha256(text if answer else ABSTENTION)`.
9. If `record`, `appended = append_ledger_entry(entry, ...)`; exceptions propagate to the runner, which counts them.

### 4.11 Shadow runner (`tutor_pipeline/shadow.py`)

```python
TWO_PASS_DELIVERY_IMPLEMENTED = False            # Phase 4 sets True with its V1 module (conflict 2)
PIPELINE_UNAVAILABLE_REASON: str | None = None   # set (or cleared) by each start-up check (11.1)
@dataclass(frozen=True)
class ShadowJob:
    shadow_response_id: str; shadowed_response_id: str; thread_id: str; user_message_id: str
    lesson_slug: str | None; presentation: PresentationPlan
def effective_mode(settings: Settings, package: ConfigPackage) -> Literal["off", "shadow"]
def run_shadow(job: ShadowJob, *, pipeline_factory: Callable[[], TwoPassPipeline], settings: Settings,
               session_factory=SessionLocal) -> None   # never raises
```

**`effective_mode` returns `"off"`** when any of: `package.tutor_pipeline is None`; `PIPELINE_UNAVAILABLE_REASON` is set; `not settings.tutor_ledger_enabled`; `settings.two_pass_tutor == "off"`. **`"on"`** returns `"shadow"` while `not TWO_PASS_DELIVERY_IMPLEMENTED`, and logs `tutor.two_pass.on_downgraded` once per process.

**`run_shadow`** (everything inside one `try`, pipeline construction included):
1. `pipeline = pipeline_factory()` (failure → `failed["pipeline"]`).
2. Open a session; `resolved = resolve_thread(db, job.thread_id, job.user_message_id, package=...)`; close it (failure → `failed["resolve"]`).
3. `pipeline.run(PipelineInput(resolved, ..., delivery="shadow", ...), budget_ms=settings.two_pass_shadow_budget_ms)` (a ledger exception → `failed["ledger"]`, anything else → `failed["pipeline"]`).
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
def append_ledger_entry(entry: LedgerEntry, *, session_factory=SessionLocal, now=None, budget_ms: int) -> AppendedRecord
def chain_head(db) -> tuple[int, str] | None
@dataclass(frozen=True) class LedgerCheck: count; first_seq; last_seq; head_hash; head_row: tuple[int, str] | None; problems: tuple[str, ...]; ok (property)
def verify_response_ledger(db, *, expected_head: tuple[int, str] | None = None) -> LedgerCheck
@dataclass(frozen=True) class LegacyDelivery: ...   # section 7.12
LEGACY_CONTAINMENT_RULE_HASH = canonical_sha256({"id": "contained-answers-v1", "mode": EXTRACTIVE_MODE,
    "max_quoted_spans": MAX_QUOTED_SPANS, "quotation_lead": QUOTATION_LEAD, "abstention": ABSTENTION})
def build_legacy_entry(delivery: LegacyDelivery, *, settings, package, manifest_sha256) -> LedgerEntry
def record_legacy_delivery(delivery: LegacyDelivery, *, settings=None, session_factory=SessionLocal) -> AppendedRecord | None   # fail-open
```

**Append** (at most 3 attempts within `budget_ms`; `created_at` fixed before the first attempt; small jitter between attempts as in the security log). Each attempt is one session and uses Core statements in this exact order:
1. If a row with `response_id` exists: an equal `entry_sha256` returns `duplicate=True`; a different one raises `LedgerConflict`.
2. On PostgreSQL: `SET LOCAL lock_timeout = '<remaining>ms'` (an int; no `%`; no bind parameter).
3. `insert(ResponseLedgerHead).values(chain=CHAIN, seq=0, record_hash=GENESIS_HASH, updated_at=now).on_conflict_do_nothing(index_elements=["chain"])` (dialect insert).
4. `head = SELECT seq, record_hash ... WHERE chain=CHAIN FOR UPDATE` (`with_for_update()`; a no-op on SQLite).
5. `seq = head.seq + 1`, `prev = head.record_hash`; `INSERT` the record (`entry = entry_bytes(entry).decode()`, `entry_sha256`, `record_hash`).
6. `UPDATE response_ledger_head SET seq, record_hash, updated_at WHERE chain=CHAIN`; commit.
7. An `IntegrityError` rolls back and retries if budget remains (a duplicate `response_id` is re-read as in step 1). Any other `DBAPIError` (lock timeout, SQLite busy, trigger refusal) rolls back and raises at once.

On success it logs `tutor.ledger.appended` with `delivery`, `seq`, `record_hash`, `duplicate` (the off-DB copy, conflict 6).

**`record_legacy_delivery`** builds the entry and appends it with `budget_ms=settings.tutor_ledger_append_budget_ms`. Every exception logs `tutor.ledger.append_failed` (ERROR; `{"delivery": "legacy", "error": class}`), increments `failed["legacy"]`, and returns None. The learner response is never changed.

**`verify_response_ledger`** streams rows by `seq` ascending (`yield_per(500)`). No retention applies, so the first row must be seq 1. Each row's entry is validated with `ENTRY_SCHEMAS[row.entry_schema]` (an unknown schema is a problem). Problem messages:

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
| `"the chain no longer reaches the logged head seq {s}"` | `expected_head` is not in the chain with an equal hash |

### 4.13 Evidence panel (`app/services/evidence_panel.py`)

```python
def build_evidence_panel(*, decision: str, citations: list[Citation], retrieval_mode: str, settings: Settings) -> EvidencePanel
```

- `labels = ["lexically_screened"] if decision == "answer" else []`.
- `degraded = ["extractive_only"]` (D-19: generation is off), plus `"retrieval_fallback"` when `retrieval_mode.startswith("lexical-fallback")`, plus `"citations_provisional"` when any citation is provisional.
- `spans = [EvidenceSpanLink(span_id=c.span_id, label=f"{c.source_title} — {c.section_title}", resolvable=settings.span_resolver_route_enabled)]` for the delivered citations.
- The panel never reads shadow output.

---

## 5. Configuration package v2 (`apps/api/app/config_package/v2.json`)

### 5.1 File
- v2 is a copy of v1 with: `package_version: "2.0.0"`, `schema_version: 2`, `phase: "3"`, `created: "2026-11-19"`, and the additions below.
- Blocks copied unchanged: `span_identity`, `corpus_version`, `gates`, `retrieval`, `semantic`, `near_duplicate`, `legacy_citations`, `boundary`. `abstention` gains only `calibrated_with_package_version`. `owner_decisions` keeps `D-17`, `D-30`, `Q-10` and `PLAN-11.3` unchanged and adds `D-19` and `D-12`.
- `retrieval_sha256` is unchanged, so `index_version` and `corpus_version` are unchanged.
- Sidecar: `v2.json.sha256`. `v1.json` and its sidecar stay readable for one release (DI-42).

```json
"supersedes": {"package_version": "1.0.0", "sha256": "060c59f2ac94dcd20b16f9e7bd3e21128b952b067135ac29a91821b02bc04403",
               "readable_until": "the release after the Phase 3 merge"},
"abstention": { "...v1 fields...": "...", "calibrated_with_package_version": "1.0.0" },
"tutor_pipeline": {
  "version": "two-pass-v1", "status": "provisional", "phase": "3",
  "schemas": {
    "ResolvedQuestion":   {"version": "resolved-question-v1",   "path": "schemas/resolved-question.v1.schema.json",   "sha256": "<canonical sha>"},
    "RetrievalRequest":   {"version": "retrieval-request-v1",   "path": "schemas/retrieval-request.v1.schema.json",   "sha256": "…"},
    "EvidenceBundle":     {"version": "evidence-bundle-v1",     "path": "schemas/evidence-bundle.v1.schema.json",     "sha256": "…"},
    "EvidentialEnvelope": {"version": "evidential-envelope-v1", "path": "schemas/evidential-envelope.v1.schema.json", "sha256": "…"},
    "ClaimPlan":          {"version": "claim-plan-v1",          "path": "schemas/claim-plan.v1.schema.json",          "sha256": "…"},
    "LockedClaimSet":     {"version": "locked-claim-set-v1",    "path": "schemas/locked-claim-set.v1.schema.json",    "sha256": "…"},
    "PresentationPlan":   {"version": "presentation-plan-v1",   "path": "schemas/presentation-plan.v1.schema.json",   "sha256": "…"},
    "LedgerEntry":        {"version": "ledger-entry-v1",        "path": "schemas/ledger-entry.v1.schema.json",        "sha256": "…"}
  },
  "resolver": {"id": "thread-resolver-v1", "prompt_hash": "<resolver_prompt_hash>", "min_content_terms": 2,
               "continuation_cues": ["and ", "also ", "but ", "so ", "then ", "what about ", "how about "], "max_lookback": 4,
               "inputs": "the learner's own user messages of the same thread (plan 3.1)"},
  "retrieval": {"request_fields": ["text", "lesson_slug", "corpus_version"], "top_k": 4, "mode": "lexical",
                "near_miss_rule": "gate-near-floor-flag-of-top-result-v1"},
  "evidential": {"generator_default": "extractive-d19-v1", "generators_allowed": ["extractive-d19-v1"],
                 "prompt_hash": "<evidential_prompt_hash>", "max_claims": 3, "max_claims_per_span": 2,
                 "min_sentence_words": 4, "max_sentence_chars": 1000, "sentence_rule": "sentences-v1",
                 "binding_rule": "resolver-bundle-sentence-v1"},
  "pedagogical": {"renderer": "template-renderer-v1", "prompt_hash": "<pedagogical_prompt_hash>",
                  "presentation_plans": ["concise", "stepwise", "socratic"], "default_plan": "concise",
                  "max_regenerations": 2, "max_regenerations_authority": "plan 3.7: at most two",
                  "subset_check": "segment-exact-normalised-v1"},
  "ledger": {"chain": "tutor-responses", "entry_schema": "ledger-entry-v1",
             "record_hash_rule": "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1",
             "genesis": "0000000000000000000000000000000000000000000000000000000000000000",
             "deliveries": ["legacy", "shadow", "delivered"]},
  "stop": {"phase2_bound_claim_ratio": 1.0, "authority": "plan Phase 3 L; measured, spec M1"},
  "unused_provenance_fields": ["v1_3_checker_model_id", "panel_weights_version", "routing_table_version", "tool_contract_version"]
},
"flag_policy": {
  "two_pass_tutor": {"values": ["off", "shadow", "on"], "default_development": "shadow", "default_elsewhere": "off",
                     "on_requires": "phase4_exit_passed", "authority": "plan Phase 3 G; AC-3-6; 13.6"},
  "phase4_exit_passed": false, "phase4_exit_evidence": null
},
"owner_decisions": { "D-17": "...unchanged", "D-30": "...unchanged", "Q-10": "...unchanged", "PLAN-11.3": "...unchanged",
  "D-19": {"option": "RECOMMENDATION (no-provider extractive mode)", "status": "provisional", "authority": "P1-D-18",
           "ratified": false, "applied_to": ["legacy contained answers (task 1.11)", "two-pass evidential generator extractive-d19-v1"],
           "record": "PD-08"},
  "D-12": {"state": "open", "path": "no provider generator is wired; hold H6 (P3 interim path) stays unresolved; the D-19 extractive generator is the interim path",
           "ratified": false, "record": "PD-09"}
}
```

### 5.2 Loader (`app/core/config_package.py`)

**Constants:** `DEFAULT_PACKAGE_PATH` becomes `.../v2.json`; add `V1_PACKAGE_PATH`; `WIRED_GENERATORS = frozenset({"extractive-d19-v1"})` ("D-12 open: no provider generator is wired (hold H6)"); `TUTOR_SCHEMA_NAMES` (the 8 names in 5.1).

**Parsing.** `parse_config_package` accepts `schema_version` 1 or 2. For 1: `tutor_pipeline=None`, `flag_policy=FlagPolicy(False, None)`. For 2, any failure raises `ConfigPackageError`, governed or not:
- `supersedes` is an object with `package_version` and a 64-hex `sha256`;
- every v1 block, by the existing v1 rules;
- `tutor_pipeline` (next table);
- `flag_policy`: `phase4_exit_passed` is a bool; when true, `phase4_exit_evidence` is a non-empty string;
- `owner_decisions.D-12.state == "open"` implies `generators_allowed == ["extractive-d19-v1"]`.

| `tutor_pipeline` check | Rule |
|---|---|
| schema names | exactly `TUTOR_SCHEMA_NAMES` |
| schema `path` | relative, under `schemas/`, no `..`, resolves inside the package directory (existence is checked in 5.4, not here) |
| hashes | each `sha256` and each prompt hash is 64-hex |
| `max_regenerations` | an int in 0..2 |
| plans | `presentation_plans` ⊇ {concise, stepwise, socratic} and `default_plan` is in them |
| generators | `generators_allowed` ⊆ `WIRED_GENERATORS` and `generator_default` is in it |
| claim limits | `1 ≤ max_claims ≤ 10`, `1 ≤ max_claims_per_span ≤ max_claims` |
| sentence limits | `min_sentence_words ≥ 1`, `max_sentence_chars ≥ 50` |
| retrieval | `1 ≤ top_k ≤ 12`; `request_fields == ["text", "lesson_slug", "corpus_version"]`; `mode == "lexical"` |
| stop | `0 < phase2_bound_claim_ratio ≤ 1` |
| `unused_provenance_fields` | equals the four names |

**New dataclasses:** `TutorPipelineParams` (every value above, plus `schemas: Mapping[str, SchemaPin(version, path, sha256)]`), `FlagPolicy(phase4_exit_passed: bool, phase4_exit_evidence: str | None)`. **`ConfigPackage`** gains `schema_version`, `tutor_pipeline`, `flag_policy`, `supersedes`. `AbstentionParams` gains `calibrated_with_package_version: str | None`.

### 5.3 Calibration lineage (`scripts/calibrate_abstention.py`)
- Line 373 becomes `"config_package_version": package.abstention.calibrated_with_package_version or package.package_version`. Nothing else changes; `--check` passes on v2 with the committed record unchanged.

### 5.4 Pipeline/package consistency check (`tutor_pipeline/package_check.py`)

```python
def check_tutor_pipeline_package(package: ConfigPackage, *, structural: bool) -> list[str]
```

Always: a schema file missing, or its canonical sha256 differing from its pin; `resolver_prompt_hash(...)`, `evidential_prompt_hash(...)` or `pedagogical_prompt_hash()` differing from the pinned values; the `GENERATORS` keys differing from `WIRED_GENERATORS`.

With `structural=True` (tests and `config_package.py --check` only, M21): a committed schema whose structure (property names, required set, `additionalProperties: false` at every object, recursively through `$defs`) differs from `SCHEMA_MODELS[name].model_json_schema(mode="validation")`.

**Start-up policy** (11.1, conflict 30): `structural=False`. A problem stops a governed build only when `TWO_PASS_TUTOR != "off"`; otherwise (and always in development) it sets `PIPELINE_UNAVAILABLE_REASON`, logs `tutor.two_pass.unavailable`, and `effective_mode` is off. The unit test requires zero problems with `structural=True`.

### 5.5 Scripts (`scripts/config_package.py`)
- **`--check [--path P]`:** the existing checks, plus, for schema 2, `check_tutor_pipeline_package(..., structural=True)`. Prints the version, sha and two-pass ids.
- **`--rehash [--path P]`:** the stopword hash and, for schema 2, the schema pins from the files and the three prompt hashes from the code; then rewrites the sidecar.
- **`--write-schemas`:** writes `SCHEMA_MODELS[name].model_json_schema(mode="validation")` to the eight files as `json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"` (LF). Then `--rehash`.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `TWO_PASS_TUTOR` | `Literal["off","shadow","on"] \| None = None`; `None` → `"shadow"` in development, `"off"` elsewhere | Plan G (L1255): "two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners". `on` is refused (below). `shadow` outside development records a `config.override` (`two_pass_tutor_shadow`). |
| `TWO_PASS_SHADOW_BUDGET_MS` | `int \| None = Field(None, ge=100, le=30000)`; None = the package's `tutor_pipeline.budgets.shadow_ms` (2000; 18.5 C3) | E1 "bounded budget". The shadow runs after the response body is sent; the budget bounds how long it holds a worker thread and the connection's next request (19). |
| `TUTOR_LEDGER_ENABLED` | `bool = True` | Not learner-visible. Kill switch for the new request-path write, like `SPAN_REGISTRY_WRITE_THROUGH`. Disabling it outside development is a `config.override` (`tutor_ledger_disabled`): it relaxes the audit control (R-22). |
| `TUTOR_LEDGER_APPEND_BUDGET_MS` | `int \| None = Field(None, ge=100, le=5000)`; None = the package's `tutor_pipeline.budgets.ledger_append_ms` (1500; 18.5 C3) | Bounds the synchronous legacy append (conflict 29); also the PostgreSQL `lock_timeout` of each attempt. |
| `LEDGER_ROUTE_ENABLED` | `bool \| None = None`: development true, elsewhere false | A new route under the freeze (conflict 4). Enabling it outside development is a `config.override` (`ledger_route_enabled`). |
| `EVIDENCE_PANEL_ENABLED` | `bool \| None = None`: development true, elsewhere false | E5 and E9 (conflict 24). Enabling it outside development is a `config.override` (`evidence_panel_enabled`). |
| `TUTOR_TURNS_RATE_LIMIT` | `"8/minute"` | Like `ASSISTANT_CHAT_RATE_LIMIT`. |
| `LEDGER_RATE_LIMIT` | `"30/minute"` | Like `SPANS_RATE_LIMIT`. |

Derived property `tutor_turns_route_enabled = environment == "development" or two_pass_tutor == "on"`.

**Validator additions** (in `validate_allowed_origins`, after `enforce_corpus_governance` is resolved):

```python
if self.two_pass_tutor is None:
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
- `infra/cloudrun/api-production.env.example.yaml` gains the eight settings with their non-development defaults (`TWO_PASS_TUTOR: "off"`, `TUTOR_LEDGER_ENABLED: "true"`, `LEDGER_ROUTE_ENABLED: "false"`, `EVIDENCE_PANEL_ENABLED: "false"`, the budgets and limits), each with its rationale. `test_api_cloud_run_example_disables_demo_auth_and_documents_secret_injection` must keep passing.

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
  1. `now = datetime.now(timezone.utc)`; the user message gets `created_at=now`, the assistant message `now + timedelta(microseconds=1)`, the turn `now`. Ids kept in locals (`user_message_id`, `turn_id`). (A production stored-data change: Python time replaces database time for these three rows; recorded in 18.)
  2. `evidence = build_evidence_panel(...) if self.settings.evidence_panel_enabled else None`, set on the response.
  3. `response._followups = self._followups(...)`, wrapped: any exception logs `tutor.ledger.append_failed` (ERROR, `{"delivery": "legacy", "stage": "prepare", "error": class}`), increments `failed["legacy"]` (a lost record is a plan L stop signal), and leaves `None`. It returns `TurnFollowups(legacy, shadow)`:
     - `legacy = LegacyDelivery(...)` if `settings.tutor_ledger_enabled`, else None;
     - `shadow = ShadowJob(shadow_response_id=f"shadow-{uuid4()}", shadowed_response_id=turn_id, thread_id=thread.id, user_message_id=..., lesson_slug=payload.lesson_slug, presentation=PresentationPlan(plan_id=presentation_plan or package default, source="request" if presentation_plan else "default"))` if `effective_mode(...) == "shadow"`, else None.
- `run_shadow(self, job)` calls `tutor_pipeline.run_shadow(job, pipeline_factory=self._pipeline, settings=self.settings)`; it never raises.
- `_pipeline()` returns `self.assistant.pipeline` when the assistant is a `TeachingAssistantService`, else `TwoPassPipeline(get_retrieval_engine(), self.settings)` (lazy import of `app.services.store` to avoid the cycle).

### 7.12 `LegacyDelivery` (in `ledger.py`) and the follow-ups
- `LegacyDelivery` holds: `response_id` (turn id), `decision`, `reason`, `claims: tuple[(text, span_ids)]`, `quoted: tuple[EvidenceSpan]` (delivered citations, `score=None`), `retrieved: tuple[EvidenceSpan] | None` (from `candidate._retrieval` when present, with scores and `near_floor`; None otherwise, giving `evidence_scope="delivered_citations"`), `answer_sha256`, `retrieval_mode`, `provider`, `model`, `corpus_version`, `index_version`, `gate`, `threshold_version`, `floor`, `margin` (from the orchestrator's store), `policy_version` and `dropped_unresolved`.
- **NEW `app/services/tutor_followups.py`:**
  ```python
  def run_turn_followups(response, orchestrator, background_tasks) -> None:
      followups = getattr(response, "_followups", None)
      if followups is None: return
      if followups.legacy is not None: record_legacy_delivery(followups.legacy)      # never raises
      if followups.shadow is not None and hasattr(orchestrator, "run_shadow"):
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
@limiter.limit(lambda: get_settings().tutor_turns_rate_limit)
def create_tutor_turn(request: Request, response: Response, payload: TutorTurnRequest, background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    if not get_settings().tutor_turns_route_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not Found"}, headers={"Cache-Control": "no-store"})
    clean = sanitize_user_text(payload.message)   # 422 if empty, as /assistant/chat
    chat = AssistantChatRequest(message=clean, thread_id=payload.thread_id, lesson_slug=payload.lesson_slug)
    delivered = deliver_tutor_turn(request, response, chat, background_tasks, db, user, presentation_plan=payload.presentation_plan)
    return TutorTurnResponse(**delivered.model_dump(), delivery="legacy")
```

**NEW `app/api/routes/ledger.py`** (`APIRouter(prefix="/ledger", tags=["ledger"])`). `GET /responses/{response_id}`, rate-limited, `Depends(get_current_user)`; `get_settings()` called directly (monkeypatchable, M25):
1. If not `ledger_route_enabled`, or the id does not match `RESPONSE_ID`: 404 `{"detail": "Response not found."}`, `Cache-Control: no-store`.
2. **Reviewer** (`user.role in LEDGER_READER_ROLES`): read the row by `response_id`; if missing and the id is a `turn-` id with an existing turn, return the legacy no-verdict result; `record_security_event("ledger.reviewer_read", "success", connection=request, actor_role=user.role, subject=user.user_id, details={"route": route_template(request), "delivery": row.delivery if row else "none"})`; return the record with the chain fields and `shadowed_response_id`.
3. **Everyone else:** a `shadow-` id is 404 whether or not it exists (AC-3-6); `turn = db.get(TutorTurn, response_id)`; missing or `turn.user_id != user.user_id` is 404; if the row exists, `LedgerResponseRead(recorded=True, legacy_turn=False, record=...)` with the chain fields and `shadowed_response_id` None; otherwise `LedgerResponseRead(recorded=False, legacy_turn=True, record=None)` (plan G "legacy turns marked no-verdict"; no write).
4. Every response carries `Cache-Control: no-store`.

**MOD `app/api/routes/spans.py`**
- Move the handler body into `_resolve_span(span_id, request, response, db)`, still calling this module's `get_settings` and `get_span_resolver` (Phase 2 monkeypatches keep working).
- Add `evidence_router = APIRouter(prefix="/evidence", tags=["evidence"])` with `GET /spans/{span_id}`, the same decorator stack and the same call. Both handlers use `limiter.shared_limit(..., scope="span-resolver")`, so the two paths share one `SPANS_RATE_LIMIT` window per client (18.4).
- Return `license_class="public"`.

**MOD `app/main.py`**
- Import `ledger` and `tutor`. `ROUTERS` becomes: …, `qa.router`, `spans.router`, `spans.evidence_router`, `assistant.router`, `tutor.router`, `ledger.router`, …
- Plus section 11.

### 7.14 MOD `app/core/authorization.py`
- Add `LEDGER_READER_ROLES = ("reviewer",)` (the draft's `admin` was withdrawn, 18.4) and three policies:

```python
("GET", "/evidence/spans/{span_id}"): _p(PUBLIC, NONE, "Alias of /spans/{span_id} (plan 7.3): the same SPAN_RESOLVER_ROUTE_ENABLED flag, rate limit and D-31 rules; public license_class only."),
("POST", "/tutor/turns"): _p(PRINCIPAL, OWNER, "Two-pass tutor endpoint (plan 7.3). 404 outside development unless TWO_PASS_TUTOR is on, which settings refuse before the Phase 4 exit; returns the legacy contained answer and runs the two-pass pipeline in shadow. A thread_id in the body must be the caller's thread. Rate-limited."),
("GET", "/ledger/responses/{response_id}"): _p(PRINCIPAL, OWNER, "404 unless LEDGER_ROUTE_ENABLED. The turn's owner reads its legacy record (a pre-ledger turn reads as no-verdict); the reviewer role reads any record, shadow records included, and each such read is a security event. Any other role, admin included, reads only its own turns. A learner never sees a shadow record (AC-3-6)."),
```

- Regenerate `docs/security/authorization-matrix.md` with `python scripts/authorization_matrix.py`.

### 7.15 NEW `app/workers/response_ledger.py`
- Modelled on `workers/security_log.py`: verify, then log one JSON line `{"job": "response_ledger", "status", "records", "first_seq", "last_seq", "head_hash", "head_row", "problems", "duration_ms"}`. Exit 1 if the chain is broken or the job fails. `python -m app.workers.response_ledger [--expect-head SEQ:HASH]`.

### 7.16 NEW `scripts/verify_ledger.py`

```
python scripts/verify_ledger.py [--database-url URL] [--report PATH] [--expect-head SEQ:HASH]
                                [--coverage-since ISO8601] [--export PATH.jsonl]
```

- Read-only; builds its own engine. The URL comes from `--database-url`, else `DATABASE_URL`; never printed.
- The report holds counts, head and problems, plus an optional `coverage` block `{"turns_since": n, "unrecorded": m}`: tutor turns created since the time with no record whose `response_id` equals the turn id. Coverage is report-only.
- `--export` writes one JSON object per row (all columns) to a path outside the repository (refuses a path inside it); it is the step before a downgrade (conflict 22).
- Exit codes: 0 ok, 1 broken, 2 usage or connection error.

### 7.17 NEW `scripts/replay_tutor_plans.py` (the three-plan replay, plan F)

```
python scripts/replay_tutor_plans.py --write docs/evaluation/phase3/three_plan_replay_v1.json
python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
```

- **Fixture.** `apps/api/tests/data/score_floor_queries.json`: in_domain 174, off_topic 100, stopword_only 24 (298 public items), plus the regression items of `apps/api/tests/data/phase3_replay_regressions.json` (1, replayed in full even with a subset; 18.4). It refuses any path under `lqs/` (like `calibrate_abstention._refuse_lqs`).
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
 "result": "pass"}
```

- `result`: `"pass"`, `"mismatch"` (any `claim_set_hash` or span set differing across plans) or `"stop"` (a non-null two-pass ratio below `tutor_pipeline.stop.phase2_bound_claim_ratio`; null never stops).
- **Exit codes:** `--write` 0 on pass, 1 on mismatch, 3 on stop, 4 when the working tree differs from HEAD (refused unless `--allow-dirty`); `--check` 1 if the record differs from a fresh run (ignoring `created_at` and `commit`), else as `--write`.
- **`commit`** is HEAD when `git status --porcelain` is empty, else HEAD + `-dirty`, so a committed record names the commit that holds the code it replayed (18.4). The report also has `answered_by_stratum` and `two_pass.merged_claims`; the `two_pass` counts are `bound_claim_ratio_terms`.
- **Expected:** governed_empty abstains on every item; all-approved `bm25f-v1` about 166 answered; all-approved `p1-floor` about 146; 0 off-topic answered; 0 mismatches; ratio 1.0 (M1, M2). The committed report is authoritative. Any package change (sha) needs a re-`--write`.

### 7.18 MOD `apps/api/app/services/store.py`
- No change. The pipeline hangs off `TeachingAssistantService`, so `rebuild_course_store()` clears it.

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
```

The entry is TEXT holding the exact canonical bytes (no JSON round-trip differences between SQLite, psycopg and pg8000). No column name matches the erasure identity pattern `(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$`.

### 8.2 Triggers (`schema_upgrades.run_schema_upgrades`)

Created when the tables exist, re-created on every start. No `%` in any statement (psycopg, pg8000).

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
- `response_ledger_head_forward_only()`: first `IF TG_OP <> 'UPDATE' THEN RAISE ...` (DELETE and statement-level TRUNCATE, where NEW/OLD are NULL); an UPDATE is allowed only if `NEW.chain = OLD.chain AND NEW.seq = OLD.seq + 1 AND EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash)`; otherwise it raises `'response_ledger_head moves forward only: ' || TG_OP || ' refused'`. Triggers `response_ledger_head_forward_only` (BEFORE UPDATE OR DELETE FOR EACH ROW) and `response_ledger_head_no_truncate` (BEFORE TRUNCATE FOR EACH STATEMENT).

**SQLite** (each `DROP TRIGGER IF EXISTS` first)
- `response_ledger_no_update`, `response_ledger_no_delete`: `RAISE(ABORT, ...)`.
- `response_ledger_links_to_chain`: BEFORE INSERT `WHEN NEW.seq != (SELECT COALESCE(MAX(seq), 0) + 1 FROM response_ledger) OR NEW.prev_hash != COALESCE((SELECT record_hash FROM response_ledger ORDER BY seq DESC LIMIT 1), '<64 zeros>')`.
- `response_ledger_head_forward_only`: BEFORE UPDATE `WHEN NEW.seq != OLD.seq + 1 OR NEW.chain != OLD.chain OR NOT EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash)`.
- `response_ledger_head_no_delete`.

### 8.3 Alembic (`apps/api/alembic/versions/20261119_phase3_response_ledger.py`)

```python
revision = "20261119_phase3_response_ledger"; down_revision = "20261119_phase2_corpus_spans"
def upgrade():  create both tables exactly as 8.1 (same constraint and index names; seq autoincrement=False)
def downgrade():
    allow = context.get_x_argument(as_dictionary=True).get("allow_ledger_drop") == "true"
    rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM response_ledger")).scalar() or 0
    if rows and not allow:
        raise RuntimeError(f"response_ledger holds {rows} rows (append-only evidence, R-22); run scripts/verify_ledger.py "
                           "--export first, then: alembic -x allow_ledger_drop=true downgrade -1")
    if op.get_bind().dialect.name == "postgresql":  drop the 5 triggers and 3 functions (IF EXISTS)
    drop the indexes, then response_ledger_head, then response_ledger
```

- Docstring: additive and reversible (expand step, plan 13.3); triggers come from `schema_upgrades`; the chain still cannot build an empty database (the strict xfail stays).
- `ledger.SCHEMA_REVISION` must equal this revision; a test parses `apps/api/alembic/versions/*.py` and asserts it is the single head.

### 8.4 Erasure and retention
- **No code change.** Not user-keyed and no foreign keys, so `user_keyed_tables()` and `_covered_tables()` exclude the tables and erasure never touches them.
- **Retention.** No rule in Phase 3: plan 12.8 leaves the retention period an OPEN owner decision (DI-45). The ledger holds no learner identifier; after erasure of `tutor_turns`/`tutor_messages` its turn and message ids are dangling. Residual: platform access logs of `GET /ledger/responses/{turn id}` and record timestamps could support re-linking outside the database; no application log carries a turn, thread or message id (0.1).
- **Tests** (13.1): `test_ac_3_4_erasure_leaves_ledger_rows_unlinkable` and `test_the_ledger_is_outside_erasure_and_guarded_at_start_up`.
- **Machine-readable retention state (18.5 C4).** Package v2 `owner_decisions.PLAN-12.8` = `{state: open, behaviour: retain}` and `tutor_pipeline.ledger.retention` = `retain`; the loader refuses anything else while no retention job exists. `test_c4_no_retention_or_erasure_job_deletes_a_ledger_row` runs `run_retention_cleanup` with a cutoff in 2100 over old ledger rows.
- **Q&A records (18.5 C8)** carry a `qa-` id stored nowhere else: unlinkable from the start.
- **`tutor_turn_idempotency` (18.5 C9)** is user-keyed: erasure deletes it and guest retention covers it like every user-keyed table.

---

## 9. Routes and request-path behaviour

| Path | Outside development (defaults) | Development |
|---|---|---|
| `POST /assistant/chat` | Body and keys identical to today (no `evidence` key; conflict 28), plus a legacy ledger record per turn (`TUTOR_LEDGER_ENABLED`, ≤ append budget). No shadow. | Legacy answer, `evidence` panel, legacy record, and the shadow pipeline as a background task (a shadow record). |
| `POST /tutor/turns` | 404 `{"detail": "Not Found"}` after authentication (anonymous 401; an invalid body 422), whatever `Idempotency-Key` holds | Like `/assistant/chat`, plus `delivery: "legacy"`. Honours `presentation_plan`. `extra="forbid"`. An optional `Idempotency-Key` (18.5 C9): a retry returns the first turn (`Idempotent-Replayed: true`); another body with the key 422; a retry while the first runs 409. |
| `GET /ledger/responses/{id}` | 404 | Owner: own legacy record (no chain fields), or `legacy_turn` no-verdict. Reviewer: any record with chain fields, logged. Shadow ids: 404 to everyone else, admin included. |
| `GET /evidence/spans/{id}` | 404 (`SPAN_RESOLVER_ROUTE_ENABLED` false) | Identical to `/spans/{id}`, plus `license_class` |
| `GET /assistant/threads/{id}` | Unchanged | Unchanged (shadow writes no message) |
| `POST /qa/ask`, `GET /qa/history` | Response bytes unchanged. Each `/qa/ask` delivery is ledgered like a tutor turn (18.5 C8; `TUTOR_LEDGER_ENABLED`, bounded, fail-open) under a `qa-` id with no learner link; the plan I SLI is reported per surface (`legacy_by_surface`). | The same |

**Rate limits.** Learner-facing tests use a fresh `demo()` principal and a distinct `x-forwarded-for` per call (8/minute limits).

**Connection note.** uvicorn processes one request at a time per HTTP/1.1 connection and the ASGI cycle ends after background tasks, so a keep-alive connection's next request can wait for the shadow (bounded by `TWO_PASS_SHADOW_BUDGET_MS`); shadow tasks also share the AnyIO thread pool with sync routes. Both matter for DI-32.

---

## 10. (reserved; numbering kept aligned with the order of work)

---

## 11. Start-up, `/ready`, logs and SLIs

### 11.1 Start-up order (`main.py`)
1. `require_guest_token_secret`.
2. `_check_corpus_before_any_table()`, as in Phase 2, plus, after `get_config_package(settings)`: if `package.tutor_pipeline`, `problems = check_tutor_pipeline_package(package, structural=False)`; on problems a governed build with `TWO_PASS_TUTOR != "off"` raises `ConfigPackageError("tutor pipeline: ...")`; otherwise set `tutor_pipeline.shadow.PIPELINE_UNAVAILABLE_REASON` and log `tutor.two_pass.unavailable` (WARNING, logger `qcai.tutor`). With no problems the reason is cleared. `TWO_PASS_TUTOR=on` has already failed in `Settings`.
3. `create_all` (the new tables) and `run_schema_upgrades` (the new triggers). No ledger row is written at start-up.
4. `_record_configuration_overrides()` adds `("two_pass_tutor_shadow", settings.two_pass_tutor == "shadow")`, `("tutor_ledger_disabled", not settings.tutor_ledger_enabled)`, `("ledger_route_enabled", settings.ledger_route_enabled)`, `("evidence_panel_enabled", settings.evidence_panel_enabled)`. Keys appear only when active, so the existing exact-details tests are unchanged.
5. The single `qcai.api` start-up line stays the only `qcai.api` structured record (M23).

### 11.2 `/ready`
- **`_build_fields()` additions** (deterministic per process, no DB read):

```json
"two_pass_tutor": "off|shadow", "two_pass_tutor_setting": "off|shadow|on", "phase4_exit_passed": false,
"tutor_pipeline": {"version": "two-pass-v1", "resolver": "thread-resolver-v1", "generator": "extractive-d19-v1",
                   "renderer": "template-renderer-v1", "presentation_plans": ["concise","stepwise","socratic"],
                   "max_regenerations": 2, "schemas_sha256": "<sha256 of the sorted schema pins>",
                   "prompt_hashes": {"resolver": "…", "evidential": "…", "pedagogical": "…"}, "available": true},
"tutor_ledger_enabled": true, "ledger_route_enabled": true, "evidence_panel_enabled": true, "tutor_turns_route_enabled": true
```

  `tutor_pipeline` is `null` with a v1 package.
- **`readiness_check` (200 path) adds** `"ledger": {"chain": "tutor-responses", "status": "ok"}` when the head is readable, wrapped in try/except (`"status": "unavailable"`); never changes readiness (the ledger fails open). `/ready` is public, so it never reports the head's sequence number, which is the all-time count of tutor responses (18.4); the head is in the verification job's log line and in every `tutor.ledger.appended` line.
- **`slis` adds two blocks:**

```json
"tutor_ledger": {"attempted": {"legacy": 0, "shadow": 0}, "appended": {"legacy": 0, "shadow": 0}, "duplicates": 0,
                 "failed": {"legacy": 0, "shadow": 0}, "conflicts": 0, "legacy_coverage_rate": null,
                 "write_stop": false},
"two_pass_shadow": {"scheduled": 0, "completed": 0, "failed": {"resolve": 0, "pipeline": 0, "ledger": 0},
                    "decisions": {"answer": 0, "abstain": 0}, "abstention_by_reason": {}, "proposed_claims": 0,
                    "bound_claims": 0, "bound_claim_ratio": null, "phase2_bound_claim_ratio_baseline": 1.0,
                    "bound_claim_ratio_stop": false, "render_regenerations": 0, "budget_exceeded": 0}
```

### 11.3 Metrics (`tutor_pipeline/metrics.py`)
- `TwoPassMetrics` and `LedgerMetrics` are locked counter classes, like `RetrievalMetrics`, with the `snapshot()` shapes above.
- `legacy_coverage_rate = appended.legacy / attempted.legacy` (null when attempted is 0; `attempted` counts every legacy delivery, including those whose preparation failed).
- `write_stop = failed.legacy + failed.shadow + conflicts > 0` (plan L "a ledger write fails").
- `bound_claim_ratio = bound / proposed`, null when proposed is 0; `bound_claim_ratio_stop = ratio is not None and ratio < baseline` (baseline from the package). Each run adds `contracts.bound_claim_ratio_terms(counts)`: claims dropped as `budget_exceeded` (bind never ran) are in neither term, and `merged` claims are in both, so a latency event never trips the binding stop (18.4).

### 11.4 Structured log events (logger `qcai.tutor`; counts, hashes and enumerations only; no question, claim or rendered text; no response, turn, thread or message id)

| Event | Fields | Severity |
|---|---|---|
| `tutor.ledger.appended` | `delivery`, `seq`, `record_hash`, `duplicate` | INFO (the off-DB chain copy) |
| `tutor.ledger.append_failed` | `delivery`, `stage`, `error` (class) | ERROR, a stop condition (plan L) |
| `tutor.ledger.conflict` | `delivery` | ERROR |
| `tutor.two_pass.shadow` | `decision`, `reason`, `proposed`, `bound`, `dropped`, `attempts`, `plan_id`, `gate`, `latency_ms`, `seq` | INFO |
| `tutor.two_pass.shadow_failed` | `step`, `error` | ERROR |
| `tutor.two_pass.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms` | WARNING |
| `tutor.two_pass.on_downgraded` | — | WARNING (once per process) |
| `tutor.two_pass.unavailable` | `reason` | WARNING |
| Security event `ledger.reviewer_read` | `route`, `delivery` (actor role; subject digest) | success |
| Job `response_ledger` | see 7.15 | INFO, or ERROR when broken |

---

## 12. Frontend (`apps/frontend`, E5)

| File | Change |
|---|---|
| `src/lib/types.ts` | `export type EvidencePanelPayload = { panel_schema: "evidence-panel-v1"; decision: "answer" \| "abstain"; labels: Array<"lexically_screened">; degraded: Array<"extractive_only" \| "retrieval_fallback" \| "citations_provisional">; spans: Array<{ span_id: string; label: string; resolvable: boolean }>; verdict: "no-verdict" };` and `AssistantChatResponse.evidence?: EvidencePanelPayload \| null`. |
| NEW `src/lib/evidence-panel.ts` | Pure module, `import type` only. Exports `DECISION_TEXT`, `LABEL_TEXT`, `DEGRADED_TEXT`, `VERDICT_TEXT`, `spanHref(spanId) = \`/api/backend/evidence/spans/${encodeURIComponent(spanId)}\`` and `evidencePanelView(payload) → { decision: string; labels: string[]; degraded: string[]; verdict: string; spans: Array<{ key: string; label: string; href: string \| null }> }`. No "grounded"; no `qcai_`/`qcai-` literal; no storage. |
| NEW `src/components/evidence-panel.tsx` | `export function EvidencePanel({ evidence }: { evidence: EvidencePanelPayload })`: `<section aria-label="Evidence for this answer" className="assistant-evidence-panel">` with the decision line, label badges, degraded notes, the verdict line, and a span list (an `<a>` when `href`, else text). |
| MOD `src/components/teaching-assistant-chat.tsx` | `ChatBubble.evidence?: AssistantChatResponse["evidence"]`; the assistant bubble gets `evidence: response.evidence ?? null`; render `{message.evidence ? <EvidencePanel evidence={message.evidence} /> : null}` after the citation list. Stored history bubbles have none. |
| MOD `src/app/globals.css` | Minimal `.assistant-evidence-panel` styles. |
| MOD `src/lib/privacy-disclosures.ts` | A `RETENTION_SCHEDULE` row (accurate disclosure: the ledger runs in production): data class "Tutor response ledger"; stored: "For each tutor answer: which approved course passages were quoted, the quotations, the decision and version stamps, linked to your tutor turn by a random id. No name, email, account id or question text."; retention: "Kept as an audit record; the retention period is an open owner decision."; trigger: "Deleting your account or tutor history removes the link, so the record can no longer be tied to you; records cannot be edited or deleted." |

**Copy (fixed, conservative):** decision `answer`: "Quoted word for word from approved course sources"; `abstain`: "No answer: the approved course sources do not cover this"; `lexically_screened`: "Lexically screened: matched on words, not checked for meaning"; `extractive_only`: "Explanations are switched off; only quotations are shown"; `retrieval_fallback`: "Search ran in a reduced mode"; `citations_provisional`: "Citations are provisional"; `no-verdict`: "Not yet verified".

**Production.** The API sends no `evidence` key outside development, so no panel renders; the privacy row is the only production frontend change.

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
3. `test_ac_3_1_what_the_evidential_pass_receives_holds_zero_learner_state_under_three_learner_contexts`: three demo learners seeded with mastery 0.1/0.5/0.9, a note, a quiz attempt, Q&A history and a profile `focus_area` holding a unique `MARKER-<uuid>`; requests to `/assistant/chat` carry `page_path` and `history` markers; the orchestrator is monkeypatched to a `TeachingAssistantService` subclass whose `pipeline` uses `SpyGenerator(ExtractiveD19Generator)`; `retrieve` (called through its module attribute) and `RetrievalEngine.search` (the legacy path) are wrapped to capture inputs; four questions, one off-topic. The captured JSON at any depth has no `LEARNER_STATE_FIELDS` key and no marker; envelopes, requests, bundle span ids and scores, `claim_set_hash` values and decisions are identical across the learners (invariant 1).
4. `test_ac_3_1_post_tutor_turns_refuses_learner_state_fields`: `page_path`, `history`, `mastery`, `user_id` in the body each give 422.

**AC-3-2**
5. `test_ac_3_2_three_presentation_plans_give_the_same_claim_set_hash_and_span_set`: over `dev`, `governed_empty`, `all_public_approved` and both gates; 40 in-domain and 10 off-topic queries, one run per plan (`record=False`); equal `claim_set_hash` and `span_ids`; `plan_id` differs; for answers the three rendered texts are pairwise distinct; governed_empty abstains everywhere with equal hashes.
6. `test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1`: `replay_tutor_plans.compute(subset=60)`; `result == "pass"`, `mismatches == []`, `evidence_class` contains "NOT E3 or LQ-1", `public_corpus_only` true; an `lqs/` path is refused; the report contains no fixture query text.

**AC-3-3**
7. `test_ac_3_3_every_factual_sentence_of_a_rendered_response_maps_to_a_locked_claim`: the real renderer, 3 plans, locked sets from 50 dev queries; `check_subset` passes on the first attempt; `missing_claims == 0`; every claim segment maps and every citation lies in the locked span ids; rendered claim text equals the locked (verbatim) text.
8. `test_ac_3_3_property_an_unmapped_sentence_regenerates_at_most_twice_then_abstains`: `rng = random.Random(20261119)`, 300 trials, random locked sets from dev spans; `FaultyRenderer` injects per scheduled attempt one of: an invented sentence; a claim with a digit changed; a sentence from a span outside the set; a fact in a connective; an extra citation; a citation on the wrong claim; a duplicate claim; text not matching the segments; a non-contiguous line order. Schedule: a random boolean list of length 3. **Property:** decision `answer` iff some attempt ≤ 3 is clean; `render_attempts` equals the first clean attempt (or 3); an answer's rendered response passes `check_subset`; an abstention has reason `subset_check_failed` and `rendered is None`.
9. `test_ac_3_3_a_renderer_that_adds_a_claim_a_citation_or_a_fact_in_a_connective_is_caught`: each plan J failure mode, deterministic.
10. `test_ac_3_3_the_overlap_gate_is_gone_and_claims_are_never_rebound`: `claim_gate` has no `ClaimGate` or `evidence_digest`; a claim verbatim from span A citing span B is dropped `not_verbatim`, not rebound; a truncated sentence of a cited span (a qualifying clause removed) is dropped `not_verbatim`; a cited span outside the bundle is `outside_bundle`; an unbound claim is `unbound`; a forged content hash is `unresolvable`.

**AC-3-4**
11. `test_ac_3_4_every_delivered_tutor_response_has_a_ledger_record_and_the_chain_verifies`: 6 `/assistant/chat` and 3 `/tutor/turns` calls (answers and abstentions); each turn has a record with `response_id == turn_id`, delivery `legacy`, decision equal to the response's, `span_ids` equal to the sorted citation span ids, `rendered_text_sha256 == sha256(answer)`, claim texts equal to the response claims, and `retrieval.evidence_scope == "retrieved"` with scores; each turn has exactly one shadow record (`shadowed_response_id == turn_id`); `verify_response_ledger(session db).ok`.
12. `test_ac_3_4_the_pipeline_refuses_delivered_mode_before_the_phase_4_exit`: `PipelineInput(delivery="delivered")` (constructed bypassing the Literal via `model_construct`-style dataclass replace) makes `run` raise `DeliveryNotImplemented` before any retrieval or append; no `delivered` row exists after the whole module; a `LedgerEntry(delivery="delivered")` is refused by its validator; with `FailingLedger` a shadow run propagates to `run_shadow`, which counts `failed["ledger"]`.
13. `test_ac_3_4_ledger_tamper_is_detected` (isolated DB), parametrised: an edited entry; an edited `record_hash` column; an edited `decision` column; a middle row deleted; the tail truncated; the head forged with the tail truncated and `expected_head` taken from the worker log line; two rows' seq swapped; an unknown `entry_schema`. Each yields its problem message; `scripts/verify_ledger.py` exits 1 on each; a clean chain exits 0 and the worker exits 0.
14. `test_ac_3_4_update_delete_and_truncate_are_refused_and_the_head_moves_forward_only` (isolated DB): raw UPDATE and DELETE raise `DBAPIError` with "append-only"; on PostgreSQL TRUNCATE of either table raises; a raw INSERT with the wrong `prev_hash` or seq raises; a head rewind, a head delete, or a head pointing at a non-existent record raises.
15. `test_ac_3_4_appends_are_idempotent_on_response_id_and_a_changed_entry_is_refused`.
16. `test_ac_3_4_two_concurrent_appends_never_fork_the_chain` (isolated DB, both dialects): `threading.Barrier(2)` gives seq {1, 2} and verify ok; then 4 threads × 10 give `(40, 1, 40)` and ok (generous budget for the test).
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
28. `test_plan_l_a_shadow_or_ledger_failure_never_changes_the_learner_response_and_is_counted`: parametrised: the pipeline raises; the shadow append raises; the budget is exceeded (a slow fake generator, `TWO_PASS_SHADOW_BUDGET_MS=100`); the legacy append raises; follow-up preparation raises. The response equals that of `off`; each case increments its counter in `/ready` `slis` and emits its event; `write_stop` is true for the ledger cases.
29. `test_plan_l_flag_off_restores_the_labelled_legacy_path`: with `off`, no shadow record; legacy records still exist; the panel labels are present.
30. `test_plan_l_the_bound_claim_ratio_is_reported_and_a_drop_below_phase_2_is_a_stop`: the extractive generator gives 1.0 and no stop; a `ScriptedGenerator` with 1 unbound claim in 4 gives 0.75, `bound_claim_ratio_stop` true, and replay `compute(...)` gives `result == "stop"` and exit 3; a null ratio is not a stop.
31. `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode`: `config_package_version == "2.0.0"`; `tutor_pipeline` ids and hashes equal the package's; `two_pass_tutor == "shadow"`; `ledger == {"chain": "tutor-responses", "status": "ok"}`, with no sequence number (18.4); both SLI blocks present; `_build_fields()` makes no DB call.
32. `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` (SQLite and PostgreSQL via `fresh_database_url`): `create_all` on every table except the ledger tables, `alembic stamp 20261119_phase2_corpus_spans`, `alembic upgrade head`, `run_schema_upgrades`: `compare_metadata == []`; append one row; `alembic downgrade -1` fails with "export first"; `alembic -x allow_ledger_drop=true downgrade -1` succeeds and the tables are gone; `SCHEMA_REVISION` equals the single head.
33. `test_plan_g_legacy_turns_read_as_no_verdict`: a turn inserted directly with no record gives `recorded == False`, `legacy_turn == True`, `verdict == "no-verdict"`; row counts unchanged.
34. `test_plan_h_private_plane_spans_never_reach_the_bundle_the_envelope_or_the_alias_route`: a temporary manifest moves one document item to the private plane (as AC-2-7 does); for queries that retrieved it before, no bundle or envelope span names it, the shadow record has none of its span ids, and `/evidence/spans/{id}` is 404; every envelope span is quotable; `governed_empty` abstains with `no_quotable_evidence` or a retrieval reason on all 298 fixture items.
35. `test_task_3_8_the_evidence_panel_labels_the_contained_answer_and_never_says_grounded`: answer → `labels == ["lexically_screened"]`, abstention → `[]`; `"extractive_only"` always in `degraded`; spans equal the citations; `resolvable` follows `SPAN_RESOLVER_ROUTE_ENABLED`; "grounded" nowhere in `evidence`; with `EVIDENCE_PANEL_ENABLED=False` the response has no `evidence` key.
36. `test_evidence_spans_alias_matches_the_resolver_route_and_is_off_when_the_flag_is_off`: body equals `/spans/{id}`'s plus `license_class`; governed D-31 document spans give 404; flag off → 404 and `no-store`.
37. `test_the_ledger_is_outside_erasure_and_guarded_at_start_up`, modelled on the security-log test.
38. `test_freeze_production_chat_responses_keep_todays_keys_and_bytes`: with production-like settings monkeypatched into the orchestrator and route (evidence panel off, shadow off), `/assistant/chat` returns exactly the pre-Phase-3 key set (`answer, citations, retrieval_mode, provider, model, grounded, thread_id, turn_id, decision, decision_reason, claims`), no `evidence` key, and a body equal (minus ids) to an orchestrator built without the Phase 3 follow-ups.
39. `test_plan_l_a_held_ledger_lock_never_delays_the_learner_beyond_the_append_budget`: on PostgreSQL (branch), another connection holds `SELECT ... FOR UPDATE` on the head; a chat returns within `TUTOR_LEDGER_APPEND_BUDGET_MS` + 500 ms with the normal body, and `failed.legacy` increments; on both dialects an `IntegrityError`-raising stub is retried at most 3 times and a non-integrity `DBAPIError` is not retried.

### 13.2 NEW unit test files

| File | Tests |
|---|---|
| `test_tutor_pipeline_contracts.py` | Committed schema files structurally equal `SCHEMA_MODELS` and their sha256 equal the pins (`check_tutor_pipeline_package(..., structural=True) == []`). Models are frozen. `LockedClaimSet` refuses a wrong `claim_set_hash` or `span_ids`; `verify_locked` catches a `model_copy` tamper. `LedgerEntry` validator rules, both directions. `ledger_canonical` refuses NaN. |
| `test_tutor_resolver.py` | `resolve_turns` rule table; the text template; prompt-hash pin; `resolve_thread` ordering with microsecond timestamps and SQLite whole-second legacy rows (and `id != cur.id`); wrong-thread refusal. |
| `test_tutor_retrieve_bind_lock.py` | Request allowlist; `corpus_version_mismatch`; sufficiency (abstain; near_miss exactly when the top result's `near_floor`; answer); every bind drop reason; claim text kept verbatim (an NFKC-changing character survives); content-addressed `claim_id`; lock hash independent of plan; `span_is_quotable` equals the `contain_answer` decision over all dev and governed spans; `RetrievalEngine.evidence` results equal the lexical `search` results, never call the semantic backend even with `SEMANTIC_RETRIEVAL_ENABLED` and a mocked aligned backend, and record no Phase 2 SLI. |
| `test_tutor_render_subset.py` | Each plan's layout and exact template strings; stepwise reorders by `source_order`; citations numbered by first appearance; `layout_text`; every `check_subset` problem code; the pedagogical hash pin covers all plans. |
| `test_response_ledger.py` | Canonical bytes and `record_hash_for` vectors; genesis; `chain_head`; the retry onto a new head (monkeypatched stale head, as in `test_security_log`); the Core statement order (insert record before head update) on both dialects; `LedgerConflict`; `record_legacy_delivery` fail-open; the PostgreSQL `lock_timeout` statement issued (dialect branch); worker JSON line; `tutor.ledger.appended` carries `record_hash`; `verify_ledger.py` report, coverage, export refusal inside the repo; `entry_schema` dispatch. |
| `test_config_package.py` (additions) | `test_package_v2_keeps_every_phase_2_value_of_v1` (every v1 block equal except the lineage field; `owner_decisions` keeps the four v1 entries equal; `retrieval_sha256` equal). `test_v1_stays_readable_for_one_release`. `test_v2_structural_errors_always_stop_the_load`, parametrised: `max_regenerations=3`, a `default_plan` not in the plans, a non-wired generator, an absolute or `..` schema path, a missing schema name, `phase4_exit_passed=true` without evidence, D-12 open with a second generator, `retrieval.mode != "lexical"`, a stop ratio of 0. `test_on_is_refused_unless_phase4_exit_passed`. `test_a_start_up_pipeline_problem_is_fatal_only_when_the_pipeline_is_requested` (subprocess, governed: a schema file removed → starts with `off`, fails with `shadow`). |
| `test_authorization.py` | Additions in 13.3. |

### 13.3 Existing tests expected to change (intent kept; the commit message gives the reason)

1. **`test_config_package.py::test_the_shipped_package_validates_and_matches_its_hash`** asserts `package_version == "2.0.0"` for `DEFAULT_PACKAGE_PATH`; the v1 assertions move to `test_v1_stays_readable_for_one_release` (loads `V1_PACKAGE_PATH`, 1.0.0, hash verified). Reason: plan P "schemas in configuration package v2". `RAW` now reads v2; the parametrised structural edits still apply.
2. **`test_phase2_acceptance.py::test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis`**: `"1.0.0"` becomes `package.package_version` (intent: "reports the package in force"); `set(slis) == {4 keys}` becomes `set(slis) == {4 keys} | {"tutor_ledger", "two_pass_shadow"}` (still exact).
3. **`test_authorization.py`**: `OWNERSHIP_TESTED` adds `("POST", "/tutor/turns")` and `("GET", "/ledger/responses/{response_id}")`; `_concrete` adds `"response_id": "turn-00000000-0000-0000-0000-000000000000"`; two new ownership tests: `test_another_learners_thread_cannot_be_continued_through_tutor_turns` (404, no message written) and `test_another_learners_ledger_record_reads_as_missing` (owner 200; intruder response equals the missing-id response; shadow id 404 for the owner). Strengthens the matrix rule.
4. **`apps/frontend/tests/answer-wording.integration.test.ts`:** `ANSWER_SURFACES` adds `components/evidence-panel.tsx` and `lib/evidence-panel.ts`. Stricter.
5. **`docs/security/authorization-matrix.md`:** regenerated (`test_the_committed_matrix_is_current`).
6. **Expected unchanged; verify:** `test_cs595_increment.py::test_persistent_tutor_stores_resolved_follow_up_and_claim_provenance` (legacy `_resolve_query` kept; direct `orchestrator.chat` calls schedule nothing); `test_api.py` stub tutors (no `_followups`); AC-2-9 tests (the shadow changes no response; `RetrievalEngine.search` call counts unchanged because the shadow calls `evidence`); `test_the_shipped_gate_outside_development_is_p1_floor_and_bm25_is_an_override` and `test_security_log.py::test_configuration_overrides_are_recorded_outside_development` (exact override details unchanged under production defaults); `test_structured_logging.py::test_startup_logs_what_the_instance_started_with` (one `qcai.api` record); `test_ac_2_8_the_ci_gate_exits_1_...` and `test_d9_an_invalid_or_tampered_configuration_package_...` (they copy the default package, now v2, without `schemas/`; parsing does not need the files); `calibrate_abstention.py --check` (lineage field); `privacy-inventory.integration.test.ts` (the new row is not a retention-constant row).

### 13.4 Frontend tests (NEW `apps/frontend/tests/evidence-panel.integration.test.ts`)
- `evidencePanelView`: maps each code to its fixed text; an answer gets the lexically-screened label, an abstention none; `resolvable: false` gives `href === null`, `true` gives `/api/backend/evidence/spans/<encoded>`; no output matches `/grounded/i`.
- Source regexes: `teaching-assistant-chat.tsx` matches `/message\.evidence \? <EvidencePanel/` and `/evidence: response\.evidence \?\? null/`; `evidence-panel.tsx` contains `aria-label="Evidence for this answer"` and no "grounded"; `privacy-disclosures.ts` has a "Tutor response ledger" row.

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

- `api-postgres` runs the API suite on PostgreSQL 16 as a matrix over both drivers, psycopg and pg8000 (production's driver), with `TEST_DATABASE_URL=postgresql+${{ matrix.driver }}://...` (18.5 C7; DI-46).
- The frontend job is unchanged (the new test matches `tests/**/*.test.ts`). `release-artifacts` and `api-image-boundary-scan` are unchanged.

---

## 15. Docs and evidence

1. **`docs/adr/ADR-001-grounding-separation.md`:** append `## Revision 2026-11-19 (Phase 3: provenance-first two-channel tutor)`, keeping the existing text as history: status (accepted for Phase 3 engineering; D-19 extractive provisional, PD-08; D-12 open, PD-09); the evidential channel (resolve, retrieve, envelope, generator, bind, lock) and the pedagogical channel (render, subset check); learner state is an input to neither; `PresentationPlan` from request hints; `build_pedagogical_context` still reaches no prompt; lock before render and the plan-independent `claim_set_hash` (conflict 1); verbatim claim text and sentence-aligned binding (conflict 32); the ledger as the record replacing mutable `TutorTurn` provenance; `two_pass_tutor` shadow-only until the Phase 4 exit with three locks (conflict 2, R-a); residuals: "misleading wording within locked claims" (plan M; sentence splits at abbreviations) and renderer wording (R-41); the RQ2 replay (AC-3-2) and the invariant 1 test.
2. **`docs/adr/ADR-005-abstention-gate.md`:** append `## Revision 2026-11-19 (Phase 3)`: the overlap `ClaimGate` is removed (plan 3.4); `claim_gate.py` is the segment subset checker; abstention reasons come from the pipeline vocabulary; the full rewrite is Phase 4 (plan Phase 4 F).
3. **`docs/architecture/phase3-implementation-spec.md`:** this document, plus the implementation record (section 18).
4. **`docs/evaluation/phase3/README.md`** plus the generated `three_plan_replay_v1.json`: reproduction, configurations, metrics, "not E3 or LQ-1 evidence", the bound-claim stop, limitations (deterministic renderer; no entailment checker; lexical only).
5. **`infra/cloudrun/deployment.md`:** new section `## Phase 3: two-channel tutor, response ledger and shadow (runbook)`; the Phase 2 step "must report `config_package_version` 1.0.0" gains "(2.0.0 from the Phase 3 release; see the Phase 3 section)".
   - **Approval.** Every step below is a cloud write needing Platform Owner approval under D-05; none is run in Phase 3.
   - **Defaults that ship:** `TWO_PASS_TUTOR` off, `LEDGER_ROUTE_ENABLED` false, `EVIDENCE_PANEL_ENABLED` false, `TUTOR_LEDGER_ENABLED` true, `TUTOR_LEDGER_APPEND_BUDGET_MS` 1500; `POST /tutor/turns` 404.
   - **Before the release:** `config_package.py --check` (v2 and v1); `replay_tutor_plans.py --check`; a backup; optionally the Alembic pre-deploy job (`alembic upgrade head`) from a workstation with the migration scripts.
   - **Deploy.** `create_all` adds `response_ledger` and `response_ledger_head`; the upgrades add the triggers. `/ready` must show `config_package_version` 2.0.0, `two_pass_tutor` off, `tutor_pipeline.available` true and `ledger.status` ok. A pipeline-package problem does not stop the start-up while `TWO_PASS_TUTOR` is off; `available` false then needs a fix before any shadow enablement.
   - **Verify** with `python -m app.workers.response_ledger`; its daily schedule is DI-33. Every `tutor.ledger.appended` log line carries `seq` and `record_hash` (the off-DB copy).
   - **Enabling shadow in production** is a separate D-05 decision (DI-32); expect a `config.override` (`two_pass_tutor_shadow`); check Cloud Run CPU allocation for background tasks first.
   - **Stop conditions** (plan L): any `tutor.ledger.append_failed` or `tutor.ledger.conflict` (`slis.tutor_ledger.write_stop`); `bound_claim_ratio_stop` true; `verify_response_ledger` problems. On a stop, set `TWO_PASS_TUTOR=off` (shadow) or investigate the database (legacy appends); legacy deliveries continue.
   - **Roll back** by digest. The ledger stays. The Alembic downgrade refuses while rows exist; export with `scripts/verify_ledger.py --export` to a path outside the repository first.
6. **`infra/cloudrun/observability.md`:** `## Phase 3 SLIs: ledger and shadow (plan Phase 3 I)`, covering 11.3-11.4 and the `/ready` blocks, marked "Not set up yet".
7. **`docs/testing/test-strategy.md`:** `## Phase 3 acceptance map (plan Phase 3 K)`, mapping AC-3-1..AC-3-6 and plan G/H/I/L onto 13.1.
8. **`docs/security/authorization-matrix.md`:** regenerated.
9. **`infra/cloudrun/api-production.env.example.yaml`:** the new settings (section 6).
10. **BEP-2-12** (outside the repository; never edit other phases' rows):
    - `phase03/PHASE_RECORD.md`: what was built per task 3.1-3.8; preconditions as taken (Phase 2 exit not passed: AC-2-7 partial, DI-25/DI-26; task 1.11 "lexically screened" label present only as an API string, rendered in development by the panel, production via DI-34; D-12 open; D-19 provisional); local suite numbers (SQLite, PostgreSQL psycopg, the local pg8000 run); CI pending (DI-31).
    - `phase03/CLOSURE_EVIDENCE_NOTES.md`: R-22 (the ledger, tests 11-18, off-DB record hashes; residual DBA alteration until DI-33); R-41 (AC-3-1 tests; residual renderer wording); R-11 (typed envelope, `extra="forbid"`); R-13 (resolver binding, no rebinding, sentence-aligned verbatim; closure in Phase 4); R-16 (containment unchanged; no delivered path; truncation refused at bind); R-46 (package v2 pins, stop baseline in the package); R-10 (lexical-only shadow, no provider egress).
    - Register rows (section 16).

---

## 16. Provisional defaults and deferred items (append; keep the numbering)

### 16.1 `PROVISIONAL_DEFAULTS_REGISTER.md`

| # | Decision (owner) | Plan text | Provisional default applied | Where the value lives | Phase |
|---|---|---|---|---|---|
| PD-08 | D-19, extractive mode (PO) | 18.4: "D-19 RECOMMENDATION: no-provider extractive mode quoting spans only from manifest-approved public-plane assets, never the private licensed evaluation corpus or ULQS; no approved span, abstain [Risk R-26]." | The two-pass evidential generator is `extractive-d19-v1`: verbatim whole sentences of quotable spans only, bound by `resolver-bundle-sentence-v1`. No approved span means abstain. The legacy containment is unchanged. | Package v2 `owner_decisions.D-19`, `tutor_pipeline.evidential`; ADR-001 revision 2026-11-19 | 3 |
| PD-09 | D-12, provider and terms (PO, counsel); hold H6 | 14.3: "D-12 \|OPEN \|PO \|Generation provider terms \|single pinned (interim)"; 9.4: "H6 \| Provider [Decision D-12] \| P3 interim path; P5 exit \| Payload register"; "OPEN decisions ... MUST NOT be closed by engineering alone." | Unresolved path. No provider generator is wired (the `ClaimGenerator` Protocol is the interface; `WIRED_GENERATORS` holds only the extractive id). H6 stays open. The D-19 extractive generator is the Phase 3 interim path, with no provider payloads; shadow retrieval is lexical only. | Package v2 `owner_decisions.D-12`, `WIRED_GENERATORS` | 3 |
| PD-10 | The Phase 3 switches outside development (freeze, D-05) | Phase 3 G: "two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners"; 5.3 release rule | `TWO_PASS_TUTOR` off (shadow in development; `on` refused until `phase4_exit_passed`). `EVIDENCE_PANEL_ENABLED` false. `LEDGER_ROUTE_ENABLED` false. `/tutor/turns` 404. `TUTOR_LEDGER_ENABLED` true (not learner-visible; append budget 1500 ms). Each relaxation logs `config.override`. | `app/core/config.py`; package v2 `flag_policy`; env example | 3 |
| PD-11 | Two-pass parameters with no plan value | 3.1-3.7 give no values (the regeneration limit "at most two" is plan text, not provisional) | Resolver: at least 2 content terms, the cue list, lookback 4. Retrieval top_k 4, lexical. Near-miss: the gate's `near_floor` on the top result. At most 3 claims, 2 per span, sentences of 4+ words and ≤1000 chars (`sentences-v1`). Plans concise, stepwise, socratic; default concise. Shadow budget 2000 ms; ledger append budget 1500 ms. Stop baseline 1.0 (measured). | Package v2 `tutor_pipeline`; settings | 3 |
| PD-12 | Ledger reader roles (SL) | 7.3: "GET /ledger/responses/{response_id} (owner or reviewer)"; 7.6: "reviewer access is logged" | The plan text: only role `reviewer` reads any record, shadow included; each read is a security event; owners see no chain position fields. No reviewer role is provisioned (DI-38). (Revised in 18.4: the draft's `admin` widened the plan text and was withdrawn.) | `app/core/authorization.py` `LEDGER_READER_ROLES`; the authorization matrix | 3 |

### 16.2 `DEFERRED_ITEMS_REGISTER.md`: a `## Phase 3` heading

| # | Item | Who | State |
|---|---|---|---|
| DI-31 | A cited green CI run for AC-3-1..AC-3-6 (plan Phase 3 P). Needs a push and a PR. | Eng | Pending |
| DI-32 | Production shadow enablement (`TWO_PASS_TUTOR=shadow` outside development). Needs D-05, a check that Cloud Run gives CPU to background tasks, and a look at keep-alive and thread-pool effects (section 9). Shadow processes real learner questions, so plan H applies. | PfO / PO | Not started |
| DI-33 | The daily off-DB ledger digest (7.5): schedule `python -m app.workers.response_ledger` and keep the logged head. A cloud write. Record hashes are already in the platform log per append; R-22's residual "DBA alteration" stays open until a head is retained off-platform. | PfO, then Eng | Worker built; not scheduled |
| DI-34 | The evidence-panel production rollout (`EVIDENCE_PANEL_ENABLED` outside development; D-05), which also completes the task 1.11 "lexically screened" label precondition in production (today an API string only). Also the panel for reloaded threads and the Q&A panel, and the trust indicator (7.1 L2). | PO | Deferred |
| DI-35 | D-12 and H6, the provider decision. The provider generator is an interface only; wiring it is Phase 5, through the gateway. | PO, counsel | Open (PD-09) |
| DI-36 | F-1 ("100% carry span IDs, model ID, prompt hash and verdicts") cannot be measured before a two-pass response is delivered (Phase 4 exit). Legacy records carry span ids, model id, rule hash, verdict null ("no-verdict"). | MLE | Not measurable in Phase 3 |
| DI-37 | Ratify PD-08..PD-12. | PO / PI / SL | Open |
| DI-38 | Provision reviewers: no `reviewer` role exists in account provisioning (Phase 6 reviewer pool; H4, D-18). | PO | Open |
| DI-39 | `/qa/ask` deliveries are not ledgered (tutor scope only); the plan I SLI is reported for tutor deliveries. Phase 4 decides whether Q&A becomes a tutor surface. | MLE | Deferred |
| DI-40 | Client idempotency keys on `POST /tutor/turns` (7.3: "mutations carry client keys"), needed when `on` delivers (Phase 4). | Eng | Deferred |
| DI-41 | The contract step after the dual-write release: retire the legacy `_resolve_query` heuristic and the `TutorTurn` provenance columns once two-pass delivers. | Eng (Phase 4+) | Deferred |
| DI-42 | Remove configuration package v1 after one release (and its CI check). | Eng | Deferred |
| DI-43 | LQ-1 and E3 learner-state invariance with the real learner model (Phase 8/10). The three-plan replay and the three-learner test are engineering evidence only. | MLE / PI | Out of Phase 3 scope |
| DI-44 | Optional: add `/evidence/spans` and `/spans` to the frontend proxy's public route patterns, so span links never mint a guest session. | Eng | Deferred |
| DI-45 | Ledger retention period (plan 12.8: "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted)"). Until decided the ledger is kept and the privacy page says so. | PO / PI | Open |
| DI-46 | pg8000 (the production driver) is not exercised by CI; the ledger tests were run locally on pg8000 once. A CI job or matrix entry is deferred. | Eng | Deferred |

**Revised in 18.5 (second review round).** PD-11 is reworded as engineering parameters with no plan value, and its budgets moved into the package. DI-39, DI-40 and DI-44 are closed in code. DI-45 is machine-readable in the package and stays open (an owner decision). DI-46 has its CI leg. The registers in `BEP-2-12/00_meta` hold the current text; the tables above are the spec-time version.

---

## 17. Order of work, commits and verification

Commit after each step, on the branch, with the trailer. Run the full suite at steps 4, 5 and 8.

1. **Contracts, text and hash functions.** `tutor_pipeline/contracts.py`, `text.py`, and the constant/hash parts of `resolve.py` (`RESOLVER_ID`, `resolver_prompt_hash`), `evidential.py` (`EXTRACTIVE_RULE`, `evidential_prompt_hash`) and `render.py` (`TEMPLATES`, `PLANS_LAYOUT`, `pedagogical_prompt_hash`), and `package_check.py`, so the package can be pinned from final code.
2. **Configuration package v2.** `v2.json` and the schema files (`--write-schemas`, then `--rehash`); the loader, `V1_PACKAGE_PATH`, the lineage field, the `calibrate_abstention` line; the `test_config_package.py` changes. Verify: `config_package.py --check` (v2 and v1), `calibrate_abstention.py --check`. Any later change to a hashed constant needs `--rehash` and is caught by `--check`.
3. **Ledger.** ORM, triggers, Alembic revision, `ledger.py`, the worker, `verify_ledger.py`, `test_response_ledger.py`. Start the scratch PostgreSQL now (below) and run the ledger tests on SQLite, PostgreSQL (psycopg) and PostgreSQL (pg8000: `TEST_DATABASE_URL=postgresql+pg8000://postgres@127.0.0.1:<port>/qcai_test`, ledger and acceptance files only; record the result for DI-46).
4. **The rest of `tutor_pipeline` and the `claim_gate` repurpose,** plus `span_is_quotable`, `RetrievalEngine.evidence`, `manifest_sha256`, and the 13.2 unit tests. Then **wiring:** settings and validator; teaching assistant (`_retrieval`, `pipeline`), orchestrator, follow-ups and evidence panel; the `AssistantChatResponse` serializer; routes (tutor, ledger, evidence alias), authorization policies and the regenerated matrix; `main.py` start-up check, overrides and `/ready`. Full suite.
5. **Acceptance tests.** `test_phase3_acceptance.py`, `tutor_fakes.py`, and the 13.3 changes. Full suite on SQLite and PostgreSQL.
6. **Replay.** `scripts/replay_tutor_plans.py --write docs/evaluation/phase3/three_plan_replay_v1.json`, then `--check`, then `docs/evaluation/phase3/README.md`. Re-run `--write` after any later package change.
7. **Frontend.** Types, panel, chat bubble, CSS, privacy row; `npm run lint`, `npm run typecheck`, `npm run test:integration` in `apps/frontend`. If `next build` is run, restore `apps/frontend/next-env.d.ts` with `git checkout`.
8. **Docs, ADRs, the env example and CI.** Then the full verification below. The BEP-2-12 notes and register rows are written outside the repository, with no commit.

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
- run the suite with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:<port>/qcai_test` (and the pg8000 subset, step 3);
- stop it at the end with `pg_ctl -D <scratchpad>\pg17 stop`.

**Expected results**
- SQLite: the baseline of 576 passed, 2 skipped and 3 xfailed (strict), plus the new tests, with no new skips or xfails.
- PostgreSQL: 574 passed and 3 xfailed, plus the new tests.

**Exit (plan Phase 3 P)**
- "AC-3-1 to AC-3-6 green in a cited CI run; schemas in configuration package v2; ADR-001 revised".
- The cited CI run needs a push (DI-31). Every other part is produced by steps 1-8.

---

## 18. Implementation record (2026-11-19)

This section records every refinement or departure the code forced, against sections 0-17 above (which are the reviewed spec as followed). Editorial change to the spec text itself: local machine paths (the scratchpad and venv locations) are replaced by `<scratchpad>`, `<py>` and `<port>`.

### 18.1 Departures known at spec time, confirmed

- **Production stored-data change:** tutor message and turn `created_at` are set in Python (7.11), needed for a deterministic per-thread order on SQLite (M5). The user message gets `now`, the assistant reply `now + 1 µs`, the turn and `thread.updated_at` `now`.
- **`"evidence"` is omitted from serialisation when None** (conflict 28), so production response bodies keep today's keys. Test 38 pins the key set and the bytes (ids aside).
- **No delivered two-pass path in Phase 3** (R-a, conflict 31). `ledger_write_failed` is not in the abstention vocabulary.
- **The legacy append is bounded** by `TUTOR_LEDGER_APPEND_BUDGET_MS` (default 1500), which is also each PostgreSQL attempt's `lock_timeout` and `statement_timeout`; the learner waits at most the budget plus 250 ms, pool checkout included (18.4).
- **Start-up pipeline-package problems are fatal only when the pipeline is requested** (conflict 30): a governed build with `TWO_PASS_TUTOR` not off.
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

### 18.3 Verification results (local, 2026-11-19)

**Suites**
- **Full suite, SQLite:** 715 passed, 2 skipped, 3 xfailed (strict), 1 deselected (`release_artifacts`). The baseline was 576 passed, 2 skipped and 3 xfailed. There are no new skips or xfails.
- **Full API suite, PostgreSQL 17** (scratch cluster, psycopg, a fresh database): 713 passed, 3 xfailed. The baseline was 574 passed and 3 xfailed.
  - On a database reused from earlier runs, `test_demo_seed.py::test_demo_seed_is_idempotent_and_populates_public_activity` fails: the review queue shows 8 items, and earlier runs' submissions push the fixture out. This is pre-existing and does not occur on a fresh database, which CI uses.
- **pg8000** (the production driver), `test_phase3_acceptance.py` and `test_response_ledger.py` on the scratch PostgreSQL: 74 passed (DI-46).
- **The new tests on PostgreSQL with psycopg** (acceptance, ledger, resolver, authorization): 162 passed.

**Validators**
- `config_package.py --check` passes for v2 (2.0.0, sha256 `ae0daa55…`) and for v1.
- `calibrate_abstention.py --check` passes with the committed Phase 2 record unchanged.
- `replay_tutor_plans.py --check` passes. The results:
  - governed_empty: 0 of 298 answered;
  - all-approved with `bm25f-v1`: 166 answered;
  - all-approved with `p1-floor`: 146 answered;
  - 0 mismatches, and a bound-claim ratio of 1.0 beside the Phase 2 legacy 1.0.
- `authorization_matrix.py --check` passes, and so does every other CI validator (listed in the phase record).

**Frontend:** lint and typecheck are clean, and `test:integration` gives 138 of 138.

### 18.4 Review fixes (2026-11-19)

Ten confirmed review findings were fixed on the branch. Each fix has a test.
1. **Budget overrun after generation (plan L).** A shadow whose budget ran out after the generator returned counted the proposed claims as proposed and not bound. `/ready` then reported a bound-claim ratio of 0.0 and `bound_claim_ratio_stop` true for the life of the process.
   - The claims are now counted as `dropped.budget_exceeded`, and `contracts.bound_claim_ratio_terms` leaves them out of both terms.
   - `PipelineCounts` refuses counts that do not reconcile (`proposed_claims == bound_claims + sum(dropped)`, known reasons only), and `LedgerEntry` requires `bound_claims == len(claims)`.
   - Tests: the plan L "budget" case, and `test_plan_l_a_budget_overrun_after_generation_is_a_latency_event_not_a_bound_claim_stop` (a fake clock, so the generate step is the one that trips).
2. **Verbatim claim text (conflict 32, D-19).** Bind stored the generator's text, and the subset check compared NFKC forms, so a folded claim or a folded rendering passed. Bind now locks the span's own sentence, and the subset check compares whitespace forms. Tests: a folded generator claim locks the corpus characters; folded renderings (`n²`, `½`, a ligature, U+2011) are unmapped.
3. **Ledger readers (PD-12).** `admin` was withdrawn, because plan 7.3 says "(owner or reviewer)". Test: an admin gets the missing-id 404 for a shadow record and for another learner's turn, and reads its own turn as an owner; no `ledger.reviewer_read` event is written.
4. **Two locked claims with one sentence.** A sentence in two overlapping spans was proposed once per span and locked twice. The subset check, keyed on text, then rejected the honest rendering, so the shadow abstained with `subset_check_failed`.
   - Bind merges such proposals into one claim citing both spans (`dropped.merged`, counted as bound in the ratio).
   - The subset check looks claims up by `claim_id`.
   - Tests: bind and subset unit tests, the real-corpus query, and a replay regression item.
5. **OpenAPI.** The wrap `model_serializer` erased both chat response schemas; `exclude_if` on the field keeps them (conflict 28). Test: `/openapi.json` lists every field of `AssistantChatResponse` and `TutorTurnResponse`.
6. **Public `/ready`.** It no longer reports `ledger.head_seq` (the all-time count of tutor responses), only `ledger.status`.
7. **The legacy append's wait** is bounded as a whole (conflict 29): `statement_timeout` beside `lock_timeout`, and a worker pool, so neither pool checkout nor a new connection can hold the learner. Tests: a stuck pool returns within the budget plus the grace, and is counted when it ends; the in-flight cap refuses at once.
8. **The privacy row** now says what the ledger keeps: the passages the search matched, with their match scores and positions; and, for the internal two-step check, the ids of the learner's tutor messages that the question was taken from.
9. **`/evidence/spans` rate limit.** The alias and `/spans` share one window (`shared_limit`, scope `span-resolver`). Test: alternating the two paths reaches the limit at the limit.
10. **The replay record's `commit`.** It is HEAD only on a clean tree, else HEAD + `-dirty`, and `--write` refuses a dirty tree unless `--allow-dirty` is given (exit 4).
    - The record was regenerated. The 298 original items replay identically (equal `items_digest` in every configuration).
    - It was then rewritten from the committed fix, so it names that commit.

**Verification of the review fixes (local, 2026-11-19).**
- **Full suite, SQLite:** 730 passed, 2 skipped, 3 xfailed (strict), 1 deselected: 15 new tests, no new skips or xfails.
- **Full API suite, PostgreSQL 17** (scratch cluster, psycopg, a fresh database): 728 passed, 3 xfailed.
- **pg8000** (the production driver), `test_phase3_acceptance.py` and `test_response_ledger.py`: 82 passed.
- **Validators:** every CI validator passes, including `config_package.py --check` (v2 and v1, both unchanged), `authorization_matrix.py --check` (regenerated) and `replay_tutor_plans.py --check`.
- **Frontend:** lint and typecheck are clean; `test:integration` gives 138 of 138.
- **Not run:** `pip-audit` and `npm audit` (they need the network; no dependency changed).

### 18.5 Hardening, second review round (2026-11-19)

The second review round sent twelve items (C1-C12). Each is fixed with a test that fails if the defect comes back. Most tests are in `apps/api/tests/test_phase3_hardening.py`; the others are named below.

**Production changes.** These ship only with a D-05 release, like the rest of Phase 3. None adds learner-facing capability:
- the `/qa/ask` ledger record (C8);
- the pg8000 error classes (C7);
- the thread lock and the monotonic message times (C12);
- the `tutor_turn_idempotency` table, which stays empty outside development while `POST /tutor/turns` answers 404 (C9).

**C1. `license_class` is derived, and a non-public span is never emitted** (plan 7.4; plan 7.5 "The license_class gate is defense in depth"; plan H "Public-corpus spans only"). This supersedes the resolution of conflict 13.
- `CorpusRegistry.license_class(plane=, item_id=, source_filename=)` returns `"public"` only when two things hold:
  - the record's own plane is `public`;
  - the manifest does not put the item, or its source file, on another plane.
  Otherwise it returns None.
- `retrieve.evidence_span_for` builds every `EvidenceSpan` from its span record through that function. The two-pass bundle and the legacy ledger record both use it, so neither writes the literal `"public"` any more.
- A span whose class is None is left out of the bundle and counted (`slis.tutor_ledger.non_public_spans_excluded`, by surface). It is also logged as `tutor.evidence.non_public_excluded`.
- If every result is excluded, the bundle abstains with `no_quotable_evidence`.
- In the legacy record, a delivered claim that cites such a span is left out and counted under the new drop reason `not_public`, so no non-public text is ever recorded.
- `GET /spans/{id}` and `GET /evidence/spans/{id}` derive the class themselves and answer the same 404 when it is not public, even if the resolver returned the span.
- Tests: a forced private-plane record, and a manifest that moves the item private, are refused by `retrieve`, by both routes (with a resolver stubbed to leak the span) and by the legacy record.

**C2. Every `config.override` key is tested.**
- Under production settings, each of the 13 keys is checked one relaxation at a time. Each case sets one relaxation and expects exactly `{key: True}`:
  - the 2 Phase 1 keys;
  - the 7 Phase 2 keys (4 of them were untested: `semantic_retrieval_enabled`, `span_resolver_route_enabled`, `config_package_path_overridden`, `config_package_hash_unverified`);
  - the 4 Phase 3 keys.
- Another case sets all 13 relaxations together.
- An AST scan of `_record_configuration_overrides` fails when a key has no case, so deleting or adding a line fails a test.
- The path override is also checked through the real loader.

**C3. The PD-11 values are configuration, not code constants** (R-46: "One hashed configuration package per ledger record").
- Package v2 gains `tutor_pipeline.budgets` (`provisional: true`):
  - `shadow_ms` 2000 and `ledger_append_ms` 1500;
  - `ledger_append_attempts` 3 and `ledger_wait_grace_ms` 250;
  - `ledger_append_workers` 4 and `ledger_append_max_in_flight` 16.
  The last four were code constants. `tutor_pipeline` also gains `provisional: true`, and its authority now says the values are engineering parameters with no plan value, never plan defaults.
- `TWO_PASS_SHADOW_BUDGET_MS` and `TUTOR_LEDGER_APPEND_BUDGET_MS` now default to None (the package value) and are overrides only. `sentences()` has no default `max_chars`.
- The ledger needs package v2. Under v1 a legacy record fails closed and is counted (`LedgerUnavailable`); it never falls back to a code default.
- Tests:
  - a package with other budgets drives the budgets and the attempt count;
  - the loader refuses budgets that are not marked provisional or are out of bounds;
  - the old constants are gone.

**C4. Ledger retention is an open decision, and the package says "retain"** (plan 12.8: "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted)").
- `owner_decisions.PLAN-12.8` records `{state: open, behaviour: retain, ratified: false, record: DI-45}`, and `tutor_pipeline.ledger.retention` is `"retain"`.
- The loader refuses any other state, behaviour or retention value, because no retention job exists.
- Tests: old ledger rows survive `run_retention_cleanup` with a cutoff in 2100, and the chain still verifies. `retention.py` names no ledger table, and the ledger tables are outside erasure.

**C5. `test_rate_limit[database]` waits for its instances robustly.**
- The two uvicorn instances log to a file, and `/health` is polled until a bounded ceiling (`API_TEST_START_TIMEOUT_SECONDS`, 300 s by default; it was a fixed 90 s with output discarded).
- A port lost between the probe and the bind is retried once on a new port.
- A failure says why the instance did not start (its exit code, or the ceiling) and shows the last 40 lines of its output. No assertion changed.

**C6. `test_demo_seed_is_idempotent_and_populates_public_activity` is isolated.**
- It seeds an empty database of the session's dialect (`fresh_database_url`, with the full schema).
- The routes it reads are served from that database: `get_db` is overridden, and so is the Arena service's `SessionLocal`.
- So rows from earlier tests, or from earlier runs on a reused PostgreSQL database, can neither turn the first seed into an update nor push the seeded submission off the review queue's first page (8 items). Every assertion is unchanged.

**C7. pg8000 in CI (DI-46).**
- `api-postgres` is now a matrix over `psycopg` and `pg8000`, with `TEST_DATABASE_URL=postgresql+${{ matrix.driver }}://...`.
- Before the change, the full API suite on pg8000 (scratch PostgreSQL 17) had 2 failures:
  1. A check-constraint violation (SQLSTATE 23514) arrived as `ProgrammingError`. pg8000 maps only 23505 to `IntegrityError`, so application code that catches `IntegrityError`, `DataError` or `OperationalError` behaved differently in production than in CI.
  2. The demo-seed time-zone test passed the libpq-only `options` connect argument.
- Fixes:
  1. `app.core.db.classify_pg8000_errors` is a `handle_error` hook on every engine. It re-raises a pg8000 server error as the PEP 249 class psycopg raises for the same SQLSTATE class: 22 `DataError`; 23 `IntegrityError`; 08, 40, 53, 54, 55, 57 and 58 `OperationalError`. The driver error stays `.orig`.
  2. The time-zone test sends pg8000 a `TimeZone` startup parameter, uses `Asia/Kolkata` (no cluster's default), and asserts `SHOW TimeZone`.

**C8. `/qa/ask` is ledgered (DI-39).**
- The plan text does not exclude Q&A: task 3.8 is a ledger of responses, plan I says "Ledger writes 100% of deliveries", and F-1 says "100% carry span IDs, model ID, prompt hash and verdicts".
- `QAEngine.ask` prepares a legacy record exactly as a tutor turn does: `legacy_delivery_for`, `TUTOR_LEDGER_ENABLED`, the same budget, the same fail-open path and the same chain. The route appends it after its commit.
- The record has a `qa-<uuid4>` response id (`RESPONSE_ID` and `LedgerEntry` accept `qa-` for legacy records) that is stored nowhere else. It holds no question text, no user id and no learner link from the start, so only a reviewer reads it; the asker gets the missing-id 404.
- Coverage is counted per surface (`slis.tutor_ledger.legacy_by_surface.{tutor,qa}`), and `verify_ledger.py --coverage-since` also reports `qa_records_since`.
- The privacy row now names Q&A answers and says their records are not linked to the learner.
- Tests: answers and abstentions are ledgered and the chain verifies. The response bytes and the named headers are identical with the ledger on, off or failing. Erasure removes the Q&A rows and leaves the unlinkable record, which a reviewer reads.

**C9. `Idempotency-Key` on `POST /tutor/turns` (DI-40;** plan 7.3: "mutations carry client keys").
- The header is optional. It is validated against the package's `tutor_pipeline.idempotency.key_pattern`, `^[A-Za-z0-9._:-]{8,128}$`; anything else is a 422. It is read after the flag, so a disabled route still answers 404.
- A key is scoped to the caller. `tutor_turn_idempotency` stores only the key's sha256 and the sha256 of the request (message, thread, lesson, plan), unique per caller.
- The outcomes:
  - the same key and the same request return the first turn's response, with `Idempotent-Replayed: true`;
  - a different request with the same key gets 422;
  - a retry while the first request still runs gets 409;
  - past `ttl_hours` (24) the key starts a new turn.
- The row is claimed and committed before the turn runs, and filled in the turn's own transaction (`deliver_tutor_turn(before_commit=)`). It is released if the turn fails, so concurrent requests with one key create one turn.
- The table is user-keyed: erasure deletes its rows, and guest retention covers it (`test_erasure_retention` walks every user-keyed table). Otherwise a row lives as long as the turn it answers for, like the other tutor tables.
- The Phase 3 Alembic revision, which had not been applied anywhere, creates the table. The head is unchanged (`SCHEMA_REVISION`), and the reversibility test now covers the table.
- Tests: a replay, a different caller, a changed body, malformed and oversized keys, the 404, the 409, a failed turn releasing its key, a concurrent race (real threads on PostgreSQL), expiry, and erasure.

**C10. Sentence rule `sentences-v2`** (plan M residual "misleading wording within locked claims").
- A period does not end a sentence after:
  - a common abbreviation or title (e.g., i.e., vs., cf., approx., Dr., Prof. and others);
  - "et al.";
  - a reference abbreviation followed by a number or a bracket (Fig. 3, Eq. (2), Sec. 4);
  - dotted initials;
  - a single capital initial before a capitalised word or a bracket (J. Preskill; "Petruccione, F. (2021)").
- Nor does it end one before a lowercase word. Decimal numbers and version strings were never split.
- Over the 1030 dev document spans, `sentences-v1` gave 2199 sentences of 4+ words, 49 of which end in an abbreviation, a title or an initial. `sentences-v2` gives 2177, and 1 of them ends that way: a bibliography line ending "C. Y.-Y.". The sentences of 27 spans changed.
- The rule id is in the evidential prompt hash, and `package_check` now fails when the package's `sentence_rule` or `binding_rule` differs from the code's.
- The replay record was regenerated, because the package sha256 and the claim hashes changed. The answer counts are unchanged (0, 167 and 147 of 299), with 0 mismatches and a bound-claim ratio of 1.0.
- Tests: 19 split cases (abbreviations, initials, numbers, versions and real boundaries); no dev-corpus sentence ends at an abbreviation (the old rule cut 49); and the rule-id check.

**C11. Span links through the frontend proxy (DI-44).** The development evidence panel links to `/api/backend/evidence/spans/{id}`, and the proxy minted a guest session for it, which is not needed: the API reads no credential on the span routes. `PUBLIC_API_ROUTE_PATTERNS` now holds `/spans/span-<64 hex>` and `/evidence/spans/span-<64 hex>`. The API still keeps both routes off outside development. Test: `evidence-panel.integration.test.ts`, where malformed ids and other routes still require a session.

**C12. Message times** (a production change to stored data; M5).
- `tutor_orchestrator.next_message_time` sets a turn's first message time. It is timezone-aware UTC: now, but never earlier than the thread's latest message plus 1 µs. The reply follows its question by 1 µs, and the turn row takes the question's time.
- The thread row is locked first (`SELECT ... FOR UPDATE` on PostgreSQL; SQLite serialises writers). The turn's `UPDATE` of `updated_at` already held that lock until the commit; it is now taken a few statements earlier. So concurrent turns of one thread take their times in commit order, and instances with skewed clocks cannot reorder a thread.
- Before Phase 3, PostgreSQL gave a turn's question and reply the same `now()`, the transaction start, so their order in the thread view depended on random ids.
- Readers of `created_at`:
  - the thread view and the resolver order by `(created_at, id)`;
  - R1.2 `stored_before_containment` compares against a fixed cut-over;
  - erasure deletes by user key;
  - guest retention deletes rows older than 365 days;
  - no export or analytics path reads the tutor tables.
  None changes behaviour beyond the stricter order. The thread's own `created_at` stays `server_default=now()`.
- Tests: with a stalled and then backwards clock, three turns stay strictly ordered, and the thread view returns them in that order. With 6 concurrent turns of one thread on PostgreSQL (all asking for the same instant), the 12 messages are strictly ordered in question-reply pairs, timestamptz values are UTC, and the turn times equal their questions' times.

**Verification of the second review round (local, 2026-11-19, code commit `f974355`, record commit `b341e49`).** The three suites ran at the same time, which loaded the machine the way the `test_rate_limit[database]` flake needed.
- **Full suite, SQLite:** 808 passed, 2 skipped, 3 xfailed (strict), 1 deselected. The branch had 730 passed; the 78 new tests in `test_phase3_hardening.py` add no skip or xfail.
- **Full API suite, PostgreSQL 17, psycopg:** 806 passed, 3 xfailed, on a private scratch cluster (port 55441) with a fresh database. The cluster's session time zone is America/New_York, not UTC.
- **Full API suite, PostgreSQL 17, pg8000** (the production driver), on a fresh database: 806 passed, 3 xfailed. On `15b4793` the same run had 726 passed and 2 failed; the two pg8000-only failures are fixed in C7.
- **Reused databases:** `test_demo_seed.py` passed 3 of 3 twice on the reused psycopg database and once on the reused pg8000 database (C6).
- **Validators:** all exit 0.
  - `validate_corpus.py --check-public-assets --check-recall-stop` and `validate_lqs.py --allow-draft`.
  - `config_package.py --check`: v2 2.0.0, sha256 `2220e47d…`; v1 is unchanged.
  - `authorization_matrix.py --check`, `generate_manifest.py --check` and `validate_corpus.py --check-hashes --check-near-duplicates`.
  - `calibrate_abstention.py --check`, with the Phase 2 record unchanged.
  - `replay_tutor_plans.py --check`: the record is current, and its `commit` is `f974355`.
  - `scan_boundary.py --repo` with both Docker contexts: path scan pass.
- **Frontend:** lint and typecheck are clean; `test:integration` gives 139 of 139. `next build` was not run, so `next-env.d.ts` is untouched.
- **Not run:**
  - `pip-audit` and `npm audit` need the network; no dependency changed.
  - The Docker image build and its scan.
  - PostgreSQL 16 itself: the local cluster is 17, and CI runs 16 for both drivers. A cited CI run needs a push (DI-31).
