# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## pinecone-sync-queue-description-column-missing — raw SQL selects columns from wrong table
- **Date:** 2026-04-03
- **Error patterns:** UndefinedColumnError, description, phone_hash, pinecone_sync_queue, asyncpg, SELECT
- **Root cause:** The raw SQL in sync_pinecone_queue_activity selected `description` and `phone_hash` from `pinecone_sync_queue`, but those columns only exist in the `job` and `user` tables respectively.
- **Fix:** Replaced flat SELECT with JOIN: pinecone_sync_queue JOIN job ON job.id = pinecone_sync_queue.job_id JOIN "user" ON "user".id = job.user_id to source description and phone_hash from the correct tables.
- **Files changed:** src/temporal/activities.py
---

## sms-webhook-signature-403 — Twilio signature validation returns 403 in CI due to URL/token mismatch
- **Date:** 2026-04-05
- **Error patterns:** 403, TwilioSignatureInvalid, webhook, X-Twilio-Signature, RequestValidator, test_valid_signature_real
- **Root cause:** test_valid_signature_real hardcoded the signing URL and/or token rather than reading from settings; conftest also lacked ENV and other env var defaults, so the URL/token used to compute the test signature could diverge from what the dependency reconstructed in CI.
- **Fix:** Test reads settings.webhook_base_url and settings.sms.auth_token dynamically via get_settings(). Conftest _test_env sets ENV, WEBHOOK_BASE_URL, TWILIO_AUTH_TOKEN, and other required vars via setdefault before clearing the settings LRU cache.
- **Files changed:** tests/sms/test_webhook.py, tests/conftest.py
---

