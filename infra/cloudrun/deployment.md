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
   - Check `/ready`. It must report `config_package_version` 1.0.0 and `config_package_sha256`, `span_scheme` span-v2, `retrieval_gate` p1-floor with `threshold_version` score-floor-p1-v1 (floor 6, P1-D-04), `duplicate_span_ids` 0, `manifest_drift` 0, `semantic_enabled` false, and `slis`.
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
