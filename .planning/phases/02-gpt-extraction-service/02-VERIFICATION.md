---
phase: 02-gpt-extraction-service
verified: 2026-03-07T21:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 11/12
  gaps_closed:
    - "EXT-04 — Graceful unknown SMS reply wired via process_message calling ExtractionService and asyncio.to_thread(Twilio send)"
  gaps_remaining: []
  regressions: []
gaps: []
human_verification:
  - test: "Send a POST to /sms/incoming with a valid Twilio webhook payload for an unclassifiable message"
    expected: "Inngest fires process_message, ExtractionService returns unknown, Twilio outbound SMS is sent to the originating number containing UNKNOWN_REPLY_TEXT"
    why_human: "The full webhook->Inngest->ExtractionService->Twilio path requires a live Inngest Dev Server, real DB rows, and Twilio credentials. All unit-level wiring is confirmed but end-to-end runtime has not been exercised."
---

# Phase 2: GPT Extraction Service Verification Report

**Phase Goal:** Build the GPT extraction service that classifies inbound SMS messages as job postings or worker earnings goals, extracts structured data, and stores results.
**Verified:** 2026-03-07
**Status:** passed — 12/12 must-haves verified
**Re-verification:** Yes — after EXT-04 gap closure (02-03 plan executed)

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A job posting SMS classified by ExtractionService returns message_type='job_posting' with a populated JobExtraction | VERIFIED | test_classify_job passes; ExtractionResult discriminated union in schemas.py confirmed |
| 2 | A worker goal SMS returns message_type='worker_goal' with target_earnings and target_timeframe populated | VERIFIED | test_classify_worker passes; WorkerExtraction schema confirmed |
| 3 | An ambiguous SMS returns message_type='unknown' with a reason string | VERIFIED | test_classify_unknown passes; UnknownMessage(reason=...) schema confirmed |
| 4 | All GPT calls pass through a Braintrust-wrapped AsyncOpenAI client (wrap_openai applied at construction time) | VERIFIED | service.py line 27: wrap_openai(AsyncOpenAI(...)) confirmed; test_braintrust_instrumentation passes |
| 5 | ExtractionService is a pure class with no FastAPI imports — injectable with mock clients in tests | VERIFIED | service.py has no FastAPI imports; MockSettings pattern used across all tests |
| 6 | A job posting SMS creates a row in the job table with all extraction fields populated | VERIFIED | test_job_persistence passes; JobRepository.create confirmed in jobs/repository.py |
| 7 | A worker goal SMS creates a row in the work_request table with target_earnings and target_timeframe populated | VERIFIED | test_worker_persistence passes; WorkRequestRepository.create confirmed |
| 8 | message.message_type is updated atomically with the job/worker row creation in a single transaction | VERIFIED | service.py UPDATE message SET message_type committed in same session as JobRepository.create |
| 9 | Pinecone upsert is attempted after job DB commit; failure logs an error and writes a pinecone_sync_queue row | VERIFIED | test_pinecone_upsert and test_pinecone_failure_enqueues_sync both pass; pinecone_client.py confirmed |
| 10 | An Inngest cron stub sync-pinecone-queue is registered (runs every 5 minutes) | VERIFIED | inngest_client.py: TriggerCron(cron="*/5 * * * *") registered and served in main.py |
| 11 | ExtractionService is initialized once as app.state.extraction_service in FastAPI lifespan | VERIFIED | main.py line 70: app.state.extraction_service = ExtractionService(settings) in lifespan |
| 12 | System sends a graceful SMS reply when a message cannot be classified (EXT-04) | VERIFIED | inngest_client.py lines 66-74: unknown branch calls asyncio.to_thread(twilio_client.messages.create, ..., body=UNKNOWN_REPLY_TEXT); test_process_message_unknown_sends_sms passes |

**Score:** 12/12 truths verified

---

## Required Artifacts

### Plan 02-01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/extraction/schemas.py` | ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage | VERIFIED | All 4 models present; correct Literal types |
| `src/extraction/service.py` | ExtractionService with async process() method | VERIFIED | Full implementation; Braintrust wrap, tenacity retry, storage branching |
| `src/extraction/prompts.py` | SYSTEM_PROMPT with few-shot examples | VERIFIED | 5 examples present (2 job, 2 worker, 1 unknown) |
| `src/extraction/constants.py` | GPT_MODEL, UNKNOWN_REPLY_TEXT constants | VERIFIED | Both present; UNKNOWN_REPLY_TEXT now imported and used in inngest_client.py |
| `tests/extraction/conftest.py` | make_mock_openai_client() fixture factory | VERIFIED | Factory confirmed with correct AsyncMock pattern |
| `tests/extraction/test_service.py` | Unit tests for EXT-01, EXT-04, OBS-01 | VERIFIED | 5 service tests pass |
| `tests/extraction/test_schemas.py` | Schema validation tests for EXT-02, EXT-03 | VERIFIED | 5 schema tests present and passing |

### Plan 02-02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `migrations/versions/2026-03-06_extraction_additions.py` | Alembic migration with pinecone_sync_queue | VERIFIED | revision 002, adds pay_type + pinecone_sync_queue with FK and CHECK constraints |
| `src/jobs/repository.py` | JobRepository.create() async method | VERIFIED | Static create() method, datetime parsing, UTC timestamps |
| `src/work_requests/repository.py` | WorkRequestRepository.create() async method | VERIFIED | Confirmed |
| `src/extraction/pinecone_client.py` | write_job_embedding() async function | VERIFIED | PineconeAsyncio context manager, OpenAI embedding, Vector upsert |

### Plan 02-03 Artifacts (Gap Closure)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/inngest_client.py` | process_message wired to ExtractionService with unknown-branch Twilio reply | VERIFIED | Lines 30-76: full pipeline; ExtractionService.process() called with all session params; unknown branch sends Twilio SMS via asyncio.to_thread |
| `src/config.py` | twilio_from_number field on Settings | VERIFIED | Line 10: twilio_from_number: str = "" |
| `tests/inngest/__init__.py` | Package marker | VERIFIED | File exists |
| `tests/inngest/test_process_message.py` | Three unit tests for job/worker/unknown branches | VERIFIED | All three tests pass (29 total suite green) |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/extraction/service.py` | `src/extraction/schemas.py` | `response_format=ExtractionResult` | WIRED | beta.chat.completions.parse call confirmed |
| `src/extraction/service.py` | `braintrust.wrap_openai` | `wrap_openai(AsyncOpenAI(...))` at __init__ | WIRED | Line 27 of service.py |
| `src/extraction/service.py` | `src/extraction/prompts.py` | `SYSTEM_PROMPT` in messages list | WIRED | Imported and used in messages list |
| `src/extraction/service.py` | `src/jobs/repository.py` | `JobRepository.create(session, job_create)` | WIRED | Called inside job_posting branch |
| `src/extraction/service.py` | `src/extraction/pinecone_client.py` | `write_job_embedding(...)` after job commit | WIRED | Called in try block; failure caught and queue written |
| `src/main.py` | `src/extraction/service.py` | `app.state.extraction_service` in lifespan | WIRED | Confirmed |
| `src/inngest_client.py` | `src/extraction/service.ExtractionService.process` | `ExtractionService(settings).process(...)` | WIRED | Lines 56-64: instantiated and called with all required params |
| `src/inngest_client.py` | `twilio.rest.Client` | `asyncio.to_thread(twilio_client.messages.create, ..., body=UNKNOWN_REPLY_TEXT)` | WIRED | Lines 67-73; UNKNOWN_REPLY_TEXT imported line 11 and used line 72 |
| `src/extraction/constants.py` | `src/inngest_client.py` | `UNKNOWN_REPLY_TEXT` import and usage | WIRED | Previously orphaned; now imported (line 11) and used (line 72) |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EXT-01 | 02-01 | Classify SMS as job_posting / worker_goal / unknown via single GPT call | SATISFIED | ExtractionService._call_with_retry() makes one parse call; 3 classification branches confirmed |
| EXT-02 | 02-01 | Extract job posting fields (description, datetime, flexibility, duration, location, pay/rate) | SATISFIED | JobExtraction schema has all required fields; SYSTEM_PROMPT has field definitions and examples |
| EXT-03 | 02-01 | Extract worker goal fields (target_earnings, target_timeframe) | SATISFIED | WorkerExtraction schema confirmed; test_classify_worker verifies values |
| EXT-04 | 02-01/02-03 | Send graceful SMS reply when message cannot be classified | SATISFIED | inngest_client.py unknown branch calls asyncio.to_thread(Twilio send) with UNKNOWN_REPLY_TEXT; test_process_message_unknown_sends_sms passes |
| STR-01 | 02-02 | Store extracted job postings as structured PostgreSQL records | SATISFIED | JobRepository.create() confirmed; migration 002 adds pay_type; test_job_persistence passes |
| STR-02 | 02-02 | Store extracted worker goals as structured PostgreSQL records | SATISFIED | WorkRequestRepository.create() confirmed; test_worker_persistence passes |
| VEC-01 | 02-02 | Write job embeddings to Pinecone at job creation time | SATISFIED | write_job_embedding() confirmed; test_pinecone_upsert verifies idx.upsert called |
| OBS-01 | 02-01 | Instrument GPT calls with Braintrust LLM observability | SATISFIED | wrap_openai applied in ExtractionService.__init__; test_braintrust_instrumentation passes |

---

## Anti-Patterns Found

None. The previously identified orphaned UNKNOWN_REPLY_TEXT constant is now imported and used. No new anti-patterns introduced in 02-03.

---

## Test Results

- `uv run pytest tests/inngest/test_process_message.py -q` — 3 passed (job/worker/unknown branches)
- `uv run pytest tests/ -q` — 29 passed, 0 failures (full suite, no regressions)

---

## Human Verification Required

### 1. End-to-End Pipeline (Inngest Dev Server)

**Test:** Send a POST to /sms/incoming with a valid Twilio webhook payload (unclassifiable body such as "Hello"). Confirm Inngest Dev Server receives message.received event and process_message executes.
**Expected:** ExtractionService classifies as unknown; Twilio outbound SMS is sent to the originating number containing the UNKNOWN_REPLY_TEXT string; audit_log rows are written.
**Why human:** The full webhook -> Inngest -> ExtractionService -> Twilio reply path requires a live Inngest Dev Server, real DB rows, and Twilio test credentials. All unit-level wiring is verified but runtime execution has not been observed.

---

## Re-Verification Summary

The previous verification (2026-03-07) identified one gap: EXT-04 (graceful unknown SMS reply) was not wired — UNKNOWN_REPLY_TEXT was defined but unused, and process_message remained a Phase 1 stub.

Gap closure plan 02-03 (commits 6247252, 42b8e72, 2d1de01) resolved the gap by:
- Replacing the process_message stub with a full ExtractionService pipeline invocation
- Adding the Twilio unknown-branch reply using asyncio.to_thread() to avoid blocking the event loop
- Adding twilio_from_number to Settings
- Adding three unit tests covering all three classification branches

All 12 must-haves are now verified. Phase goal is achieved.

---

_Verified: 2026-03-07_
_Verifier: Claude (gsd-verifier)_
