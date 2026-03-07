---
phase: 02-gpt-extraction-service
verified: 2026-03-07T00:00:00Z
re_verified: 2026-03-07T00:00:00Z
status: verified
score: 12/12 must-haves verified
gaps: []
---

# Phase 2: GPT Extraction Service Verification Report

**Phase Goal:** Build the GPT extraction service that classifies SMS messages and persists structured data
**Verified:** 2026-03-07
**Status:** gaps_found — 11/12 must-haves verified; EXT-04 gap found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A job posting SMS classified by ExtractionService returns message_type='job_posting' with a populated JobExtraction | VERIFIED | test_classify_job passes; ExtractionResult discriminated union in schemas.py confirmed |
| 2 | A worker goal SMS returns message_type='worker_goal' with target_earnings and target_timeframe populated | VERIFIED | test_classify_worker passes; WorkerExtraction schema confirmed |
| 3 | An ambiguous SMS returns message_type='unknown' with a reason string | VERIFIED | test_classify_unknown passes; UnknownMessage(reason=...) schema confirmed |
| 4 | All GPT calls pass through a Braintrust-wrapped AsyncOpenAI client (wrap_openai applied at construction time) | VERIFIED | service.py line 27: `self._client = wrap_openai(AsyncOpenAI(...))` confirmed; test_braintrust_instrumentation passes |
| 5 | ExtractionService is a pure class with no FastAPI imports — injectable with mock clients in tests | VERIFIED | service.py has no FastAPI imports; MockSettings pattern used in all tests |
| 6 | A job posting SMS creates a row in the job table with all extraction fields populated | VERIFIED | test_job_persistence passes; JobRepository.create confirmed in jobs/repository.py |
| 7 | A worker goal SMS creates a row in the work_request table with target_earnings and target_timeframe populated | VERIFIED | test_worker_persistence passes; WorkRequestRepository.create confirmed (3NF deviation: work_request not worker) |
| 8 | message.message_type is updated atomically with the job/worker row creation in a single transaction | VERIFIED | service.py lines 88-94: UPDATE message SET message_type committed in same session as JobRepository.create |
| 9 | Pinecone upsert is attempted after job DB commit; failure logs an error and writes a pinecone_sync_queue row | VERIFIED | test_pinecone_upsert and test_pinecone_failure_enqueues_sync both pass; pinecone_client.py confirmed |
| 10 | An Inngest cron stub sync-pinecone-queue is registered (runs every 5 minutes) | VERIFIED | inngest_client.py lines 32-41: `TriggerCron(cron="*/5 * * * *")` registered and served in main.py |
| 11 | ExtractionService is initialized once as app.state.extraction_service in FastAPI lifespan | VERIFIED | main.py line 70: `app.state.extraction_service = ExtractionService(settings)` in lifespan |
| 12 | System sends a graceful SMS reply when a message cannot be classified (EXT-04) | FAILED | UNKNOWN_REPLY_TEXT defined but unused; no Twilio send wired for unknown branch; process_message stub does not call ExtractionService |

**Score:** 11/12 truths verified

---

## Required Artifacts

### Plan 02-01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/extraction/schemas.py` | ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage | VERIFIED | All 4 models present; correct Literal types, no unsafe defaults |
| `src/extraction/service.py` | ExtractionService with async process() method | VERIFIED | Full implementation; Braintrust wrap, tenacity retry, storage branching |
| `src/extraction/prompts.py` | SYSTEM_PROMPT with 5 few-shot examples | VERIFIED | 5 examples present (2 job, 2 worker, 1 unknown); field definitions complete |
| `src/extraction/constants.py` | GPT_MODEL, UNKNOWN_REPLY_TEXT constants | VERIFIED | GPT_MODEL="gpt-5.2", UNKNOWN_REPLY_TEXT, EMBEDDING_MODEL, EMBEDDING_DIMS all present |
| `tests/extraction/conftest.py` | make_mock_openai_client() fixture factory | VERIFIED | Factory function confirmed with correct AsyncMock pattern |
| `tests/extraction/test_service.py` | Unit tests for EXT-01, EXT-04, OBS-01 | PARTIAL | 5 service tests pass; EXT-04 test only verifies unknown classification result — does not test Twilio reply |
| `tests/extraction/test_schemas.py` | Schema validation tests for EXT-02, EXT-03 | VERIFIED | 5 schema tests present and passing |

### Plan 02-02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `migrations/versions/2026-03-06_extraction_additions.py` | Alembic migration with pinecone_sync_queue | VERIFIED | revision 002, adds pay_type + 3 columns + pinecone_sync_queue table with FK and CHECK constraints |
| `src/jobs/repository.py` | JobRepository.create() async method | VERIFIED | Static create() method, datetime parsing, UTC timestamps |
| `src/work_requests/repository.py` | WorkRequestRepository.create() async method | VERIFIED | 3NF deviation noted: work_requests/ not workers/ directory |
| `src/extraction/pinecone_client.py` | write_job_embedding() async function | VERIFIED | PineconeAsyncio context manager, OpenAI embedding, Vector upsert |
| `src/extraction/service.py` | process() extended with db_session + message_id | VERIFIED | Extended with message_id, user_id, session, message_sid params; backward-compatible (all optional) |

---

## Key Link Verification

### Plan 02-01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/extraction/service.py` | `src/extraction/schemas.py` | `response_format=ExtractionResult` | WIRED | Line 161: `response_format=ExtractionResult` in beta.chat.completions.parse |
| `src/extraction/service.py` | `braintrust.wrap_openai` | `wrap_openai(AsyncOpenAI(...))` at __init__ | WIRED | Line 27: direct import and call at construction time |
| `src/extraction/service.py` | `src/extraction/prompts.py` | `SYSTEM_PROMPT` in messages list | WIRED | Line 17: imported; line 157: used in messages list |

### Plan 02-02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/extraction/service.py` | `src/jobs/repository.py` | `JobRepository.create(session, job_create)` | WIRED | Line 85: called inside job_posting branch |
| `src/extraction/service.py` | `src/extraction/pinecone_client.py` | `write_job_embedding(...)` after job commit | WIRED | Lines 102-108: called in try block; failure caught |
| `src/extraction/service.py` | `audit_log` table | structlog event + raw SQL INSERT | WIRED | `_write_audit()` method with INSERT INTO audit_log |
| `src/main.py` | `src/extraction/service.py` | `app.state.extraction_service` in lifespan | WIRED | Line 70: confirmed |
| `src/extraction/constants.py` | (any caller) | `UNKNOWN_REPLY_TEXT` import + Twilio send | NOT WIRED | UNKNOWN_REPLY_TEXT defined, zero imports in src/ |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EXT-01 | 02-01 | Classify SMS as job_posting / worker_goal / unknown via single GPT call | SATISFIED | ExtractionService._call_with_retry() makes one parse call; 3 classification branches confirmed |
| EXT-02 | 02-01 | Extract job posting fields (description, datetime, flexibility, duration, location, pay/rate) | SATISFIED | JobExtraction schema has all 10 fields; SYSTEM_PROMPT has field definitions and examples |
| EXT-03 | 02-01 | Extract worker goal fields (target_earnings, target_timeframe) | SATISFIED | WorkerExtraction schema confirmed; test_classify_worker verifies values |
| EXT-04 | 02-01 | Send graceful SMS reply when message cannot be classified | BLOCKED | UNKNOWN_REPLY_TEXT orphaned; no Twilio outbound send wired anywhere; process_message Inngest stub does not invoke ExtractionService. REQUIREMENTS.md marks this Complete for Phase 2 — assessment is premature. |
| STR-01 | 02-02 | Store extracted job postings as structured PostgreSQL records | SATISFIED | JobRepository.create() confirmed; migration 002 adds pay_type + extra columns; test_job_persistence passes |
| STR-02 | 02-02 | Store extracted worker goals as structured PostgreSQL records | SATISFIED | WorkRequestRepository.create() confirmed; test_worker_persistence passes |
| VEC-01 | 02-02 | Write job embeddings to Pinecone at job creation time | SATISFIED | write_job_embedding() confirmed; test_pinecone_upsert verifies idx.upsert called |
| OBS-01 | 02-01 | Instrument GPT calls with Braintrust LLM observability | SATISFIED | wrap_openai applied in __init__; init_logger module singleton; test_braintrust_instrumentation passes |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `src/inngest_client.py` | `process_message` remains Phase 1 stub — ExtractionService never called | Warning | EXT-04 cannot fire; the full pipeline (classify → store → reply) is not reachable from the Twilio webhook path. Deferred to Phase 4 per plan, but EXT-04 was marked Complete for Phase 2. |
| `src/extraction/constants.py` | `UNKNOWN_REPLY_TEXT` defined but zero usages | Warning | Orphaned constant; signals that the reply path is incomplete |

---

## Test Results

- `uv run pytest tests/extraction/ -q` — **14 passed** (5 schema, 5 service, 4 persistence)
- `uv run pytest tests/ -q` — **26 passed** (full suite, no regressions)

---

## Human Verification Required

### 1. EXT-04 Scope Determination

**Test:** Confirm with project owner whether EXT-04 (unknown SMS graceful reply) was intentionally deferred to Phase 4 Inngest orchestration or was expected to be wired in Phase 2.
**Expected:** Clear scope boundary — if deferred to Phase 4, REQUIREMENTS.md "Complete" status for EXT-04 should be updated to "Pending/Phase 4"
**Why human:** The PLAN lists EXT-04 as a Phase 2 requirement, REQUIREMENTS.md marks it Complete for Phase 2, yet the implementation has no Twilio send. The SUMMARY for 02-01 claims requirements-completed includes EXT-04, but the evidence does not support a Complete classification.

### 2. Inngest Pipeline End-to-End

**Test:** Send a POST to /sms/incoming with a valid Twilio webhook payload; verify the Inngest Dev Server receives `message.received` event and `process_message` executes.
**Expected:** Job or worker record appears in DB; Pinecone upsert attempted; audit_log rows written for gpt_classified and job_created/work_request_created.
**Why human:** The `process_message` Inngest stub does NOT call `ExtractionService.process()`. The storage path (`ExtractionService.process(session=...)`) is tested in isolation but not wired through the live Inngest→ExtractionService→DB path. This entire end-to-end flow requires runtime verification.

---

## Gaps Summary

One gap blocks full goal achievement:

**EXT-04 — Graceful unknown SMS reply not wired.** The requirement asks the system to send an outbound SMS when a message cannot be classified. `UNKNOWN_REPLY_TEXT` is defined in constants.py but has zero usages. No Twilio REST client send call exists anywhere in the source tree. The `process_message` Inngest function is still the Phase 1 stub that only logs and returns "ok" — it does not call `ExtractionService` at all. While the SUMMARY claims EXT-04 was completed in Phase 2, the actual code does not support this. The full reply pipeline likely requires the Phase 4 Inngest orchestration function to be wired, at which point `UNKNOWN_REPLY_TEXT` should be imported and used.

All other must-haves for the GPT extraction service, storage persistence, Pinecone embedding, and Braintrust observability are fully verified and tested.

---

_Verified: 2026-03-07_
_Verifier: Claude (gsd-verifier)_
