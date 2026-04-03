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

