# Scheduled retention job (plan Action 22)

`python -m app.workers.retention` runs every retention rule once (`app/services/retention.py`).
It logs one structured JSON line with the fields `"job": "retention"`, `"status": "ok"`, `"deleted": {...}` and `"duration_ms"`, and exits 0 (format: `observability.md`).
On any error it logs `"status": "failed"` at ERROR with the traceback and exits 1, so the run shows as failed instead of passing silently.
The API still runs the same pass once at start-up; this job makes it run daily even when no new revision starts.

These commands are a runbook, not something CI runs. Each is a cloud write that needs Platform Owner approval (D-05).

1. Create the job from the **same image digest** the API runs, with the same database settings:

   ```bash
   gcloud run jobs create qcai-retention \
     --region us-central1 \
     --image us-central1-docker.pkg.dev/<project>/qcai-repo/qcai-api@sha256:<api-digest> \
     --command python --args=-m,app.workers.retention \
     --set-env-vars ENVIRONMENT=production,CLOUD_SQL_CONNECTION_NAME=<project>:us-central1:qcai-db \
     --set-secrets DATABASE_URL=qcai-database-url:latest \
     --service-account <api-service-account> \
     --max-retries 1 --task-timeout 600
   ```

   Update `--image` whenever the API is redeployed, so the job and the API share one schema version.

2. Run it once by hand and read the JSON line in the execution log:

   ```bash
   gcloud run jobs execute qcai-retention --region us-central1 --wait
   ```

3. Schedule it daily, at 03:15 UTC:

   ```bash
   gcloud scheduler jobs create http qcai-retention-daily \
     --location us-central1 --schedule "15 3 * * *" --time-zone Etc/UTC \
     --uri "https://run.googleapis.com/v2/projects/<project>/locations/us-central1/jobs/qcai-retention:run" \
     --http-method POST --oauth-service-account-email <scheduler-service-account>
   ```

4. Alert on failure: create a Cloud Monitoring alert on Cloud Run job executions with a failed status for `qcai-retention`. A failed run must page someone; it must not just leave a log line.

Evidence for the plan's "job log" requirement: the JSON line of the first scheduled execution, filed in BEP-1 together with the execution id.

## Phase 8

The scheduled retention worker uses the same cleanup service as API startup. With `LEARNER_PRIVACY=off`, the two-argument guest eraser uses the legacy `guest-` prefix and `created_at` rule. When privacy is on, the worker applies the class register to guest-prefixed rows and bound guest subjects. `LEARNER_SYNC`, `LEARNER_PLANNER`, and `LEARNER_IDENTITY` do not select retention rules.

| Table or class | Rule with privacy enabled |
|---|---|
| Guest study rows and foreign-key dependents | Expire after 365 days using each class's age column. Durable study records stay until erasure. |
| `learner_consents` | Guest consent ages from `updated_at`. Durable consent stays until erasure. |
| `guest_legacy_upgrades` and `learner_guest_revocations` | Delete legacy upgrade records older than 365 days and retain a credential-protection tombstone. |
| `learner_claim_audits` and `learner_erasure_audits` | Expire after 365 days from creation. |
| `learner_write_guards` | Both active guards and erasure markers expire after 365 days of inactivity, measured by `last_used_at`. Stale observations expire across the same horizon. |
| `learner_subjects`, `user_accounts`, and `user_sessions` | Keep bindings and durable credentials until erasure. Sessions follow their separate expiry. |

Plan L: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." The lifecycle worker leaves the shared adaptation-stop row alone.
