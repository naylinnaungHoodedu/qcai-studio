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
