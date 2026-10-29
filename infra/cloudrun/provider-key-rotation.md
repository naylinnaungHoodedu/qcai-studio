# Rotating the Vertex AI API key (plan Action 24, R-06)

Until this change, the API sent the key as `?key=…` in the request URL. `httpx` error messages quote that URL, and the assistant logged them on any provider failure. So the current key (`qcai-vertex-ai-api-key`, version 1, created 2026-03-31) may already be in Cloud Logging, and it must be treated as exposed.

The new code sends the key in the `x-goog-api-key` header and masks credentials in every log record (`app/core/log_redaction.py`). Rotation is still required. These steps are cloud writes needing Platform Owner approval (D-05); nothing here has been run.

1. Create a replacement key in the Google Cloud console (APIs & Services → Credentials). Restrict it to the Vertex AI API.
2. Add it as a new secret version, without writing it to a file or to shell history:

   ```bash
   gcloud secrets versions add qcai-vertex-ai-api-key --data-file=-
   ```

3. Deploy the API revision that contains this change, by digest. The service reads `VERTEX_AI_API_KEY` from the secret's `latest` version, so new instances pick up the new key.
4. Verify:
   - one tutor request returns `provider: vertex-ai-api-key`;
   - the request log line shows no `key=` parameter;
   - a deliberately failing call (for example a wrong model id on staging) logs no key.
5. Disable the old version, then delete or restrict the old key in the console:

   ```bash
   gcloud secrets versions disable 1 --secret qcai-vertex-ai-api-key
   ```

6. Decide, with the Security Lead, whether existing Cloud Logging entries that may hold the old key should be purged or allowed to expire.

**If the key is not rotated, generation must stay off** (plan Action 24 stop condition). Removing `VERTEX_AI_API_KEY` alone does **not** do that on Cloud Run. Without a key, the code falls back to the service account's application-default credentials and keeps calling Vertex AI (plan E-109). Turning generation off reliably needs an explicit per-environment opt-in, which is Decision D-23 and is not built yet.
