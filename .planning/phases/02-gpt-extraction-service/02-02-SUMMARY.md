---
phase: 02-gpt-extraction-service
plan: "02"
subsystem: extraction-storage
tags: [extraction, pinecone, repositories, migration, inngest, 3nf]
dependency_graph:
  requires: [02-01]
  provides: [job-persistence, work-request-persistence, pinecone-upsert, extraction-singleton]
  affects: [03-match-service]
tech_stack:
  added: [pinecone[asyncio]==8.1.0]
  patterns:
    - Alembic migration column additions with CHECK constraints
    - Async repository pattern with static create() methods
    - Fire-and-forget Pinecone upsert with pinecone_sync_queue fallback
    - SQLModel table registration via src/models.py import in conftest
key_files:
  created:
    - migrations/versions/2026-03-06_extraction_additions.py
    - src/jobs/repository.py
    - src/work_requests/schemas.py
    - src/work_requests/repository.py
    - src/extraction/pinecone_client.py
    - src/extraction/models.py
    - tests/extraction/test_persistence.py
  modified:
    - src/jobs/models.py
    - src/jobs/schemas.py
    - src/extraction/service.py
    - src/main.py
    - src/inngest_client.py
    - src/models.py
    - tests/conftest.py
decisions:
  - "WorkRequestRepository (not WorkerRepository) — 3NF schema uses work_request table"
  - "ExtractionService.process() backward-compatible: session=None skips storage (existing tests unchanged)"
  - "PineconeSyncQueue SQLModel added to src/extraction/models.py and registered in src/models.py for test metadata"
  - "pay_rate made nullable in migration 002 and Job model (Optional in GPT extraction schema)"
  - "message_sid parameter added to process() for correct audit_log writes; defaults to str(message_id)"
metrics:
  duration_minutes: 45
  completed_date: "2026-03-07"
  tasks_completed: 2
  files_modified: 14
---

# Phase 02 Plan 02: Extraction Storage Wiring Summary

**One-liner:** Job/WorkRequest async repositories, Alembic migration 002 (pay_type + pinecone_sync_queue), PineconeAsyncio upsert with fire-and-forget failure fallback, ExtractionService extended with 3NF storage branching and lifespan singleton.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Alembic migration 002 + Job/WorkRequest models and repositories | 8ed31dc |
| 2 | Pinecone client, ExtractionService storage wiring, lifespan singleton, Inngest cron stub | c451430 |

## Verification Results

- `alembic upgrade head` applied migration 002 (pay_type, raw columns, pinecone_sync_queue) cleanly
- `pytest tests/extraction/ -x -q` — 14 tests pass (5 original + 4 persistence + 4 schema + 1 service)
- `pytest tests/ -q` — 26 tests pass (full suite)
- `docker compose up -d --build && curl http://localhost:8000/health` returns `{"status": "ok"}`
- `curl http://localhost:8000/readyz` returns `{"status": "ok", "db": "connected"}`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Schema mismatch] 3NF schema uses work_request, not worker**
- **Found during:** Task 1
- **Issue:** Plan referenced `Worker`/`WorkerRepository`/`workers/` but the 3NF schema from Phase 01.1 uses `WorkRequest`/`work_request` table
- **Fix:** Created `WorkRequestRepository` and `WorkRequestCreate` in `src/work_requests/`, not a `workers/` directory
- **Files modified:** `src/work_requests/schemas.py`, `src/work_requests/repository.py`
- **Commit:** 8ed31dc

**2. [Rule 1 - Schema mismatch] plan referenced inbound_message; actual table is message**
- **Issue:** Plan used `"UPDATE inbound_message SET message_type..."` but the 3NF table is named `message`
- **Fix:** All SQL references use `message` table; message_type column already existed in migration 001
- **Commit:** c451430

**3. [Rule 2 - Missing nullable] pay_rate must be nullable**
- **Issue:** `Job.pay_rate` was NOT NULL but `JobExtraction.pay_rate` is `Optional[float]`
- **Fix:** Added `ALTER COLUMN pay_rate nullable=True` in migration 002; updated `Job.pay_rate: Optional[float] = None`
- **Commit:** 8ed31dc

**4. [Rule 3 - Missing model] PineconeSyncQueue SQLModel needed for test metadata**
- **Issue:** `pinecone_sync_queue` table not present in SQLite test DB because no SQLModel registered it
- **Fix:** Created `src/extraction/models.py` with `PineconeSyncQueue`, imported in `src/models.py`, ensured `src.models` imported in `tests/conftest.py`
- **Commit:** c451430

**5. [Rule 1 - Process signature] user_id required for 3NF FK**
- **Issue:** Plan extended process() with `message_id` + `session`, but 3NF job/work_request rows need `user_id` FK too
- **Fix:** Added `user_id` as optional parameter to `process()` alongside `message_id` and `session`
- **Commit:** c451430

**6. [Rule 2 - Missing audit param] audit_log requires message_sid string**
- **Issue:** `audit_log.message_sid` is NOT NULL; plan's `_write_audit` only used `message_id`
- **Fix:** Added `message_sid` parameter to `process()` and `_write_audit()`; defaults to `str(message_id)` if not provided
- **Commit:** c451430

## Self-Check: PASSED

All created files confirmed on disk. Both task commits verified in git log.
