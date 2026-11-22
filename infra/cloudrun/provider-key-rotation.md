# The retired Vertex AI API key (plan Action 24, R-06; Phase 5)

The API no longer reads `VERTEX_AI_API_KEY`: Phase 5 retired the dead Vertex path and its settings (Phase 5 spec 4.18), and model egress belongs only to the model gateway (`apps/api/app/gateway/`), which registers no real provider while D-12, D-07 and Q-09 are open. A deployment that still sets the variable starts unchanged; start-up logs `gateway.retired_setting` with its name (never its value), and the value stays masked in every log line.

The old key (`qcai-vertex-ai-api-key`, version 1, created 2026-03-31) was once sent as `?key=…` in a request URL, so it may be in Cloud Logging and must be treated as exposed. Retiring it is still required, and each step is a cloud write needing Platform Owner approval (D-05); nothing here has been run (DI-81).

1. Remove `VERTEX_AI_API_KEY` (and the other VERTEX_AI_* and OPENAI_CHAT_MODEL variables) from the Cloud Run service at the next approved release.
2. Disable the old secret version, then delete or restrict the old key in the console:

   ```bash
   gcloud secrets versions disable 1 --secret qcai-vertex-ai-api-key
   ```

3. Decide, with the Security Lead, whether existing Cloud Logging entries that may hold the old key should be purged or allowed to expire.

**Provider egress needs a per-environment opt-in** (D-23, PD-22): a non-fake provider is ineligible unless the environment's `MODEL_EGRESS_PROVIDERS` names it, and the list is empty everywhere. A future provider key is read only by the gateway's secret store, travels only in a header and is registered with the log redaction (ADR-006, revision 2026-11-21).
