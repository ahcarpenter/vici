---
status: resolved
trigger: "pinecone-sync-queue-description-column-missing"
created: 2026-04-03T00:00:00Z
updated: 2026-04-03T00:00:00Z
---

## Current Focus

hypothesis: The raw SQL in sync_pinecone_queue_activity selects `description` and `phone_hash` directly from `pinecone_sync_queue`, but those columns don't exist there. They live in the `job` and `user` tables respectively.
test: Read the PineconeSyncQueue model and Job model to confirm column ownership.
expecting: PineconeSyncQueue only has id, job_id, status, attempts, last_error, created_at.
next_action: Fix the SQL to JOIN job and user tables.

## Symptoms

expected: sync-pinecone-queue sweep runs successfully, processing pending queue items
actual: activity fails with `asyncpg.exceptions.UndefinedColumnError: column "description" does not exist`
errors: |
  SQL: SELECT id, job_id, description, phone_hash FROM pinecone_sync_queue WHERE status = 'pending' LIMIT 50
  File "/app/src/temporal/activities.py", line 106, in sync_pinecone_queue_activity
    result = await session.execute(
reproduction: runs automatically every 30s via SyncPineconeQueueWorkflow cron
started: visible in current docker logs

## Eliminated

- hypothesis: description/phone_hash columns exist but have wrong name in migration
  evidence: PineconeSyncQueue model only defines id, job_id, status, attempts, last_error, created_at — no description or phone_hash
  timestamp: 2026-04-03T00:00:00Z

## Evidence

- timestamp: 2026-04-03T00:00:00Z
  checked: src/extraction/models.py (PineconeSyncQueue)
  found: Model has only id, job_id, status, attempts, last_error, created_at
  implication: description and phone_hash are not columns in pinecone_sync_queue

- timestamp: 2026-04-03T00:00:00Z
  checked: src/jobs/models.py (Job)
  found: Job has description (Optional[str]) and user_id FK to user.id
  implication: description must come from JOIN to job table

- timestamp: 2026-04-03T00:00:00Z
  checked: src/users/models.py (User)
  found: User has phone_hash (str, unique)
  implication: phone_hash must come from JOIN to user table via job.user_id

- timestamp: 2026-04-03T00:00:00Z
  checked: join path
  found: pinecone_sync_queue.job_id -> job.id -> job.description, job.user_id -> user.id -> user.phone_hash
  implication: Fix is a 2-table JOIN in the SELECT query

## Resolution

root_cause: The raw SQL in sync_pinecone_queue_activity (activities.py line 108) selects `description` and `phone_hash` from `pinecone_sync_queue`, but those columns only exist in the `job` and `user` tables respectively. The query needs to JOIN both tables.
fix: Replace the flat SELECT with a JOIN query: pinecone_sync_queue JOIN job ON job.id = pinecone_sync_queue.job_id JOIN "user" ON "user".id = job.user_id
verification: Fix replaces flat SELECT with JOIN across pinecone_sync_queue, job, and user tables so description and phone_hash are sourced from the correct tables.
files_changed: [src/temporal/activities.py]
