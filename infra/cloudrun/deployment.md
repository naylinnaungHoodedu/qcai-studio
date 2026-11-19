# Deploying by digest, with a committed deployment record (plan task 1.9, AC-1-7)

AC-1-7: "A committed deployment record names digest and commit; /health returns that commit."

**Not run yet.** A rollout is a production change. It needs the Platform Owner's approval and a D-05 release approval, and it is currently blocked by DL-2 (D-02/D-31). Images are built by Cloud Build, never on a workstation. Deploy the API and the frontend together: they share `GUEST_TOKEN_SECRET`.

## 1. Build one commit, in Cloud Build
Build from a clean checkout of the exact commit on `main`, so that what is uploaded is that commit:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/naylinnaungHoodedu/qcai-studio.git build-src
cd build-src
git checkout <commit>
git status --porcelain   # must print nothing
gcloud builds submit --project naylinnaung --config infra/cloudbuild/api-image.yaml --substitutions _GIT_SHA=$(git rev-parse HEAD) .
gcloud builds submit --project naylinnaung --config infra/cloudbuild/frontend-image.yaml --substitutions _GIT_SHA=$(git rev-parse HEAD) .
```

Source assets are not part of the build: `.gcloudignore` and `.dockerignore` keep them out of the upload and the image (AC-1-5; P1-D-07). Each image is tagged with the commit (never `:latest`) and stamped with it, so `/health` reports it. Cloud Build records each pushed digest. A missing or short `_GIT_SHA` stops the build.

## 2. Deploy by digest, check, then move traffic
```bash
python scripts/deploy_by_digest.py --service qcai-api --commit <commit>             # the plan only
python scripts/deploy_by_digest.py --service qcai-api --commit <commit> --execute --no-pin --update-secret GUEST_TOKEN_SECRET=qcai-guest-token-secret:1
python scripts/deploy_by_digest.py --service qcai-frontend --commit <commit> --execute --no-pin --update-secret GUEST_TOKEN_SECRET=qcai-guest-token-secret:1
```

`--update-secret` binds a secret by name and version, never by value. `--no-pin` stops before traffic moves, so the tagged URLs can be checked first; the script then prints the `update-traffic` command. Without it, the script moves traffic as soon as `/health` reports the commit.

With `--execute`, the script:
1. resolves the image digest;
2. deploys it with no traffic and a `c-<commit[:12]>` tag;
3. checks that the tagged URL's `/health` reports the commit. If it does not, it stops with no traffic moved;
4. pins 100% of traffic to that named revision, so traffic no longer follows "latest".

## 3. Record, and commit the record
```bash
python scripts/deployment_record.py --commit <commit> --write deploy/records
```

The record names, for each service:
- the serving revision and its image digest;
- the public `/health` response.

It exits 1 if traffic follows "latest", a digest is missing, or `/health` does not report the commit. Commit a passing record by pull request. That record, plus the `/health` it shows, is the AC-1-7 evidence.

## Rollback
Route traffic back to the previous revision by name, then record again:

```bash
gcloud run services update-traffic qcai-api --project naylinnaung --region us-central1 --to-revisions <previous revision>=100
```

Before the first digest-pinned rollout, the previous revisions are `qcai-api-00036-lzg` (`sha256:e94cadd0…4775a5`) and `qcai-frontend-00051-sw7` (BEP-0, AC-0-2).

## Phase 2: spans, manifest and citation migration (runbook)

**Approval.** Every step below that touches Cloud Run, Cloud SQL or traffic is a cloud write. Each needs the Platform Owner's approval under D-05, and **none was run in Phase 2**. The freeze still holds: what ships outside development defaults to today's behaviour:
- `RETRIEVAL_GATE` is `p1-floor`;
- `SPAN_RESOLVER_ROUTE_ENABLED` is false;
- `SEMANTIC_RETRIEVAL_ENABLED` is false;
- `CITATION_PROVISIONAL_LIFT_ENABLED` is false;
- `ALLOW_P1_FLOOR_WITH_DOCUMENTS` is false (the conflict 29 recall stop stays in force).

**Before the release:**
- `python scripts/generate_manifest.py --check`. The manifest must be current: a governed start-up stops on a changed authored curriculum.
- `python scripts/validate_corpus.py --check-public-assets --check-recall-stop --check-hashes --check-near-duplicates`.
- `python scripts/config_package.py --check`.
- `python scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json`.
- **Scan the built images** (task 2.8: "licensed-passage scans of images and releases"). On the build workstation, for each image: `docker save <image@digest> -o image.tar`, then `python scripts/scan_boundary.py --image-tar image.tar --report image-scan.json`. Paths only; file the report. For the Phase 2 exit-gate evidence, add the release bundles (`--release-zip`), the private-plane fingerprint file (`--fingerprints`, D-14) and `--require-ac-2-7`: the run exits 1 unless the report's `ac_2_7.status` is `met`.
- Take an on-demand backup.

**Steps:**
1. **Deploy** by digest, as in sections 1-3.
   - Start-up loads and verifies configuration package v1, then the manifest and its drift report. A governed build fails closed before any table is touched.
   - `create_all` adds the `corpus_spans` table, and the schema upgrades add its append-only triggers. No span row is written at start-up.
   - Check `/ready`. It must report `config_package_version` 1.0.0 (2.0.0 from the Phase 3 release; see the Phase 3 section) and `config_package_sha256`, `span_scheme` span-v2, `retrieval_gate` p1-floor with `threshold_version` score-floor-p1-v1 (floor 6, P1-D-04), `duplicate_span_ids` 0, `manifest_drift` 0, `semantic_enabled` false, and `slis`.
   - A governed start-up also stops on the conflict 29 recall stop: a manifest that approves a document while the gate is `p1-floor`.
2. **Register spans:** `python -m app.workers.register_spans --dry-run`, then `--apply`. This is a job on the API image, and its output is one JSON line. In the image only authored spans register, because the image holds no DOCX. Document spans need an approved workstation run.
3. **Dry-run the migration:** `python -m app.workers.migrate_citations --dry-run --report migration-report.json`.
   - File the report (counts only) in the phase evidence. It also answers Q-19 (row counts).
   - Compare it with D-30 (`docs/evaluation/phase2/citation_migration_report_format.md`). Exit 3 is a stop.
4. **Apply, after the report is reviewed:** `python -m app.workers.migrate_citations --apply --report migration-apply.json`.
5. **Roll back:** `python -m app.workers.migrate_citations --downgrade` restores every migrated citation byte for byte. Then route traffic back by revision name, as in "Rollback" above. Span rows stay: the table is append-only and holds no learner data.
6. **Switch production to `bm25f-v1`.** This is its own D-05 remediation release, closing R-15.
   - Attach the calibration record.
   - Expect the `config.override` event `retrieval_gate_bm25`.
   - Re-probe production read-only afterwards.

**Stop conditions:**
- Any document is approved while `p1-floor` is the default. P1 recall drops once chapter summaries are excluded (spec conflict 29), so this needs the switch in step 6 or a recalibration. The stop is enforced: governed start-up and `validate_corpus.py --check-recall-stop` refuse it. Only an owner decision sets `ALLOW_P1_FLOOR_WITH_DOCUMENTS`, which logs a `config.override` event (`p1_floor_recall_stop_overridden`).
- A governed start-up fails on the authored hash or on document drift. The manifest was not regenerated; regenerate it by PR.
- The migration reports `native_unresolved` > 0, an exact-match regression, or (in `--apply`) a non-canonical row.

## Phase 3: two-channel tutor, response ledger and shadow (runbook)

**Approval.** Every step below is a cloud write. Each needs the Platform Owner's approval under D-05, and **none was run in Phase 3**.

**Defaults that ship outside development** (the freeze holds; learners see today's behaviour):
- `TWO_PASS_TUTOR` is `off`. In development it is `shadow`. `on` is refused by settings until the configuration package records the Phase 4 exit.
- `LEDGER_ROUTE_ENABLED` and `EVIDENCE_PANEL_ENABLED` are false.
- `TUTOR_LEDGER_ENABLED` is true: the ledger is not learner-visible.
- The ledger append budget is 1500 ms and the shadow budget 2000 ms: configuration package v2 `tutor_pipeline.budgets` (PD-11). `TUTOR_LEDGER_APPEND_BUDGET_MS` and `TWO_PASS_SHADOW_BUDGET_MS` are unset; each overrides its value only. Setting either logs a `config.override` event (`ledger_append_budget_overridden`, `shadow_budget_overridden`), `/ready` shows the budgets in force (`tutor_pipeline.budgets`), and every ledger record stamps them (`versions.budgets`).
- The ledger also records each `/qa/ask` answer (the response is unchanged), under a random `qa-` id that names no learner. While the asker's Q&A history exists, the record can be matched to it (the same answer, moments apart), so treat it as pseudonymous learner data.
- `create_all` adds `tutor_turn_idempotency`, which stays empty while `POST /tutor/turns` answers 404.
- `POST /tutor/turns` answers 404.

**Before the release:**
- `python scripts/config_package.py --check`, for v2 (the default) and for v1 (`--path apps/api/app/config_package/v1.json`).
- `python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json`. Exit 3 is the plan L bound-claim stop.
- Take an on-demand backup.
- **Check CPU allocation after the response.** The legacy ledger append is on by default outside development, and an append that outlasts its budget plus the 250 ms grace finishes after the response has gone (`tutor.ledger.append_deferred`). With request-based CPU allocation such work can be throttled. Read the service's CPU allocation setting (a cloud read, DI-48) and record it in the release evidence. On PostgreSQL each attempt sets `idle_in_transaction_session_timeout` to its remaining budget, so a throttled append that holds the head row's lock is ended by the server and frees the lock. If CPU is request-based, watch `tutor.ledger.append_deferred` after the deploy: each one is investigated, and a deferred attempt that never ends (no terminal line after the horizon) is a stop (below).
- **Read the service's request timeout** (a cloud read: `gcloud run services describe <service> --region <region> --format='value(spec.template.spec.timeoutSeconds)'`) and record it in the release evidence. `deploy_by_digest.py` passes no `--timeout`, so the service keeps the value it has. The Idempotency-Key lease (600 s, PD-11) is twice Cloud Run's default 300 s; a longer timeout only lets a retry see 409 for longer. It never lets one key make two turns: a request that outlives its lease fails at its claim-token check (spec 18.8 F13).
- Optionally, run the Alembic pre-deploy job from a workstation that has the migration scripts; the image does not ship them. **Check the stamp first** with `alembic current` (spec 18.8 F14), as the rollback does:
  - `20261119_phase2_corpus_spans`: run `alembic upgrade 20261119_phase3_response_ledger` (an absolute target).
  - Nothing (a database built by `create_all`, spec M13), or any other stamp: skip the job. Start-up's `create_all` and schema upgrades build the Phase 3 tables and columns. `alembic upgrade head` on such a database replays revisions against tables `create_all` already made and fails (`learner_records` with no stamp, `corpus_spans` on a `20260827_cs595_increment` stamp).
  It connects as the API does: with `CLOUD_SQL_CONNECTION_NAME` set, `alembic/env.py` uses the API's Cloud SQL connector (`app.core.db.engine`), so set `CLOUD_SQL_CONNECTION_NAME` and `DATABASE_URL` (user and database; the password from Secret Manager) for the shell only, with the operator's own Cloud SQL Client credentials. A plain `DATABASE_URL` without the connector has no host to reach.

**Deploy** by digest, as in sections 1-3.
- `create_all` adds `response_ledger` and `response_ledger_head`, and the schema upgrades add their append-only and chain triggers (checked at each start and re-created only when they differ, tables locked head first; spec 18.8 F8) and the column `tutor_turns.ledger_record_expected`. Start-up writes nothing to the ledger (spec 18.8 F10): a revision deployed with no traffic starts while the earlier image still serves every learner, so a start time says nothing about which deliveries are recorded. The first append creates the chain head. (Corrected in 18.8 F10: start-up used to create the head with its `started_at`, and every later turn without a record then read as missing, including the turns the earlier image served before traffic moved.)
- Each tutor turn says whether it expects a record: `ledger_record_expected` is true when a Phase 3 image created it with `TUTOR_LEDGER_ENABLED` on, false under the kill switch, and null when an image that keeps no ledger created it (before this deploy, while the tagged revision had no traffic, or during a rollback window). On the ledger route a turn without a record reads `legacy_turn: true` with `unrecorded_reason: earlier_image`, or `unrecorded_reason: ledger_disabled`, or `missing` (a lost record, a plan L stop), whenever it was created (spec 18.8 F12).
- `/ready` must report:
  - `config_package_version` 2.0.0 (with `config_package_sha256`);
  - `two_pass_tutor` off and `phase4_exit_passed` false;
  - `tutor_pipeline.available` true;
  - `ledger.status` ok (the head is readable; public `/ready` never shows its sequence number).
- A pipeline-package problem (a schema pin or a prompt hash) does not stop start-up while `TWO_PASS_TUTOR` is off. It shows as `tutor_pipeline.available` false, which needs a fix before any shadow enablement.

**Verify** the chain with `python -m app.workers.response_ledger [--expect-head SEQ:HASH]`, a job on the API image. It connects as the API does (the Cloud SQL Python connector, `CLOUD_SQL_CONNECTION_NAME`), so it needs no workstation copy of `scripts/`. Its daily schedule is DI-33.
- Every `tutor.ledger.appended` log line carries `seq` and `record_hash`: the platform log is the off-database copy of the chain.
- `--expect-head SEQ:HASH` checks the chain against any logged head.
- `python -m app.workers.response_ledger --coverage-since <time>` also logs the tutor turns since then without a ledger record, split by what each turn expected (spec 18.8 F12): `unrecorded` (it expected a record: a lost record, a stop), `not_expected_earlier_image` (an image that keeps no ledger made it: before the deploy, before traffic moved, or in a rollback window; not a loss) and `ledger_disabled` (the kill switch). It also logs the `qa-` records since then (counts only). Q&A coverage is the log-based ratio (observability.md), as a `qa-` record names no Q&A row.
- Appends keep committing while the job runs. The job walks the chain up to the head it read first and counts later records as `appended_during_check`, so live traffic never reads as a broken chain.
- `--restore <path>` re-inserts an `--export` file into an empty ledger, in one transaction, recomputing every hash, and then verifies the chain (rollback, below).
- `scripts/verify_ledger.py` (the same read-only options, `--database-url`) is for development, CI and local copies; it does not use the Cloud SQL connector and has no restore.

**Enabling shadow in production** (`TWO_PASS_TUTOR=shadow`) is a separate D-05 decision (DI-32).
- Expect a `config.override` event (`two_pass_tutor_shadow`).
- First check that Cloud Run allocates CPU to work after the response (background tasks), and how keep-alive connections and the thread pool behave (spec section 9).
- Shadow processes real learner questions, so plan Phase 3 H applies.

**Stop conditions** (plan Phase 3 L):
- any `tutor.ledger.append_failed` or `tutor.ledger.conflict`, legacy or shadow (the "Ledger write failures" alert; public `slis.tutor_ledger.write_stop` turns true for a legacy one only, since a shadow record is a shadow output, spec 18.7 E15);
- ledger coverage below 100% (observability.md, "Ledger coverage"): a legacy attempt whose terminal line is `tutor.ledger.append_failed`, a legacy attempt with no terminal line 60 s after its `tutor.ledger.attempted` line, or `--coverage-since` reporting `unrecorded` above 0. Each attempt's terminal line carries its `attempt` id, so an append that ends in the next window is not a loss (spec 18.8 F11);
- the log-based shadow bound-claim ratio (`ratio_bound` over `ratio_proposed`, observability.md) below 1.0 (public `/ready` no longer carries a stop flag; spec 18.7 E15);
- `response_ledger` job problems (`status` broken).

Each `tutor.ledger.append_deferred` (ledger latency on the request path) is investigated; it is a stop only when its attempt ends in `tutor.ledger.append_failed` or has no terminal line after the 60 s horizon (coverage). A deferred append that ends `appended`, in any window, is not a stop.

On a stop:
- For the shadow, set `TWO_PASS_TUTOR=off`.
- For legacy appends, investigate the database. If appends are failing, deferred or slowing the request path, set `TUTOR_LEDGER_ENABLED=false`: it is the kill switch for every request-path ledger write. It relaxes an audit control, so it logs a `config.override` event (`tutor_ledger_disabled`) and needs the same D-05 approval as any switch; the turns not recorded meanwhile show in `--coverage-since`.

Legacy deliveries continue either way, because every ledger write fails open.

**Roll back** by digest, as in "Rollback" above. **A digest rollback needs no downgrade:** the ledger tables stay, the earlier image does not read them, and the R-22 record stays whole (it is append-only). The earlier image writes no records either: the turns it serves leave `ledger_record_expected` null, so after the roll-forward they read `unrecorded_reason: earlier_image` (and `not_expected_earlier_image` in `--coverage-since`), never as lost records (spec 18.8 F12). Record the rollback window in the release evidence: when traffic left the Phase 3 revision and when it came back (UTC). The Alembic downgrade is a separate step that is optional and rarely right: it drops the R-22 record from the database, so it needs its own owner decision (the PO, beside the D-05 approval of the rollback), recorded in the release evidence. Only then, from an operator workstation with the API's requirements installed and `apps/api` as the working directory, connecting as the API does: `CLOUD_SQL_CONNECTION_NAME` and `DATABASE_URL` (user and database; the password from Secret Manager, never typed into a file) set for the shell only, and the operator's own Cloud SQL Client credentials (Application Default Credentials). The worker and `alembic/env.py` both use the API's Cloud SQL connector then.
1. **Export:** `python -m app.workers.response_ledger --export <path>`. The worker refuses a path inside the application tree. In the image (a job), the container's disk is discarded when the job ends, so the export is a workstation step. Note the export's last head (`seq:record_hash` of its last line; the job line logs it as `head_row`).
2. **Handling the export.** It holds every record: corpus text, turn ids and, on shadow rows, the ids of the learner messages the question was taken from. While those turns exist this is pseudonymous learner data. Keep it only on an encrypted disk of the operator workstation (or a store the Platform Owner names), never in the repository, a ticket, chat, CI or a shared drive. Once the tables are dropped it is the only copy of the record. Delete it once `python -m app.workers.response_ledger --restore <path> --expect-head SEQ:HASH` (the export's last head) has re-inserted it after the upgrade is re-applied and exited 0 (step 5). If the downgrade is kept, its retention is the open plan 12.8 decision (DI-45): record where it is held in the release evidence until the PO and PI decide.
3. **Check the stamp:** `alembic current`.
   - `20261119_phase3_response_ledger (head)`: go on.
   - Nothing, or `20261119_phase2_corpus_spans`: the tables came from `create_all` (the pre-deploy job is optional, spec M13). Run `alembic stamp 20261119_phase3_response_ledger`, then `alembic check`, which must print "No new upgrade operations detected". If it reports anything, put the stamp back (`alembic stamp 20261119_phase2_corpus_spans`, or `alembic stamp base` when `alembic current` printed nothing) and stop.
   - Anything else: stop.
4. **Downgrade** to the absolute target, never `-1` (on an unstamped database `-1` fails, and on a Phase 2 stamp it reverses the Phase 2 revision, dropping `corpus_spans` and keeping the ledger): `alembic -x allow_ledger_drop=true downgrade 20261119_phase2_corpus_spans`. It drops `response_ledger`, `response_ledger_head` and `tutor_turn_idempotency`, and the column `tutor_turns.ledger_record_expected`, only. Without that column every earlier turn reads `earlier_image` after the re-apply, so first run `python -m app.workers.response_ledger --coverage-since <the Phase 3 deploy time>` and keep its counts with the release evidence: a record lost before the downgrade is visible only there.
5. **Re-applying.** After `alembic upgrade 20261119_phase3_response_ledger` (the downgrade left the stamp at `20261119_phase2_corpus_spans`, so the absolute target applies; spec 18.8 F14) or a start-up's `create_all`, run `python -m app.workers.response_ledger --restore <path> --expect-head SEQ:HASH` before the revision takes traffic (deploy it with no traffic, restore, then shift traffic). The restored chain is the exported one byte for byte, so every head logged before the drop still verifies. `--restore` refuses a ledger that already holds a record: if deliveries were recorded first, the exported records form a **retired chain**, kept in the export, the heads logged before the drop (`tutor.ledger.appended` lines, job lines) belong to it and no longer verify against the database, and the release evidence records both facts.
