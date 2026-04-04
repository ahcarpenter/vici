---
phase: 02-gpt-extraction-service
plan: 03
subsystem: api
tags: [inngest, twilio, extraction, sms, asyncio]

requires:
  - phase: 02-01
    provides: ExtractionService.process() with job/worker/unknown classification
  - phase: 02-02
    provides: ExtractionService extended with DB session, message_id storage wiring

provides:
  - process_message Inngest function wired end-to-end to ExtractionService.process()
  - Twilio outbound SMS reply for unknown classification branch using UNKNOWN_REPLY_TEXT
  - twilio_from_number field on Settings
  - Unit tests for all three classification branches (job/worker/unknown)

affects:
  - 03-matching-service
  - phase-4-inngest-orchestration

tech-stack:
  added: []
  patterns:
    - "Inngest Function handler accessed via ._handler attribute for unit testing (avoids Function wrapper)"
    - "Twilio REST client wrapped in asyncio.to_thread() to avoid blocking async event loop"
    - "ExtractionService instantiated fresh per Inngest invocation (app.state not accessible from Inngest context)"

key-files:
  created:
    - tests/inngest/__init__.py
    - tests/inngest/test_process_message.py
  modified:
    - src/inngest_client.py
    - src/config.py

key-decisions:
  - "Call process_message._handler(ctx) in tests — Inngest Function wrapper is not directly callable"
  - "ExtractionService instantiated fresh inside process_message (not pulled from app.state) — acceptable for Phase 2, can be optimized in Phase 4"
  - "Twilio send in unknown branch uses asyncio.to_thread() — Twilio REST client is synchronous"

patterns-established:
  - "Inngest handler testing: import the Function object and call ._handler(ctx) directly"
  - "Async-blocking SDK calls: wrap in asyncio.to_thread() to keep event loop unblocked"

requirements-completed:
  - EXT-04

duration: 15min
completed: 2026-03-07
---

# Phase 2 Plan 03: Gap Closure Summary

**process_message Inngest function wired to ExtractionService with Twilio unknown-reply SMS via asyncio.to_thread**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-07T20:30:00Z
- **Completed:** 2026-03-07T20:45:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Replaced Phase 1 process_message stub with full ExtractionService pipeline wiring
- Added outbound Twilio SMS for unknown classification using UNKNOWN_REPLY_TEXT constant
- Added twilio_from_number to Settings (default empty, no existing test breakage)
- 29-test full suite passes with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add twilio_from_number to Settings and create test scaffold** - `6247252` (test)
2. **Task 2: Wire process_message — call ExtractionService and send unknown-branch Twilio reply** - `42b8e72` (feat)

## Files Created/Modified

- `src/inngest_client.py` - Replaced stub with full ExtractionService pipeline + Twilio unknown-reply branch
- `src/config.py` - Added twilio_from_number field (str, default "")
- `tests/inngest/__init__.py` - New test package
- `tests/inngest/test_process_message.py` - Three unit tests covering job/worker/unknown branches

## Decisions Made

- Used `process_message._handler(ctx)` in tests rather than `process_message(ctx)` — the Inngest `@create_function` decorator wraps the handler in a `Function` object that is not directly callable. Accessing `._handler` reaches the raw async function.
- ExtractionService instantiated fresh inside process_message per invocation — Inngest context does not expose `app.state`, so `app.state.extraction_service` is not reachable. Acceptable for Phase 2.
- Twilio client wrapped in `asyncio.to_thread()` — the Twilio REST client is fully synchronous and must not block the async event loop.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test calls changed from process_message(ctx) to process_message._handler(ctx)**
- **Found during:** Task 2 (GREEN run)
- **Issue:** Plan specified `await process_message(ctx)` but the Inngest decorator wraps the function in a `Function` object — calling it raises `TypeError: 'Function' object is not callable`
- **Fix:** Changed all three test invocations to `await process_message._handler(ctx)`
- **Files modified:** tests/inngest/test_process_message.py
- **Verification:** All 3 tests pass GREEN; 29-test suite clean
- **Committed in:** 42b8e72 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Required fix for tests to work with Inngest's decorator pattern. No scope creep.

## Issues Encountered

None beyond the Inngest Function wrapper issue documented above.

## User Setup Required

Add `TWILIO_FROM_NUMBER` to `.env` (the Twilio sender phone number in E.164 format, e.g. `+18005551234`). This setting defaults to empty string and will not break existing tests, but is required for the unknown-reply SMS to work in production.

## Next Phase Readiness

- Phase 2 EXT-04 gap is now closed — all 12 must-haves verified
- 02-VERIFICATION.md updated to status: verified, score: 12/12
- Full pipeline from webhook → Inngest → ExtractionService → DB/Pinecone → optional Twilio reply is now wired end-to-end
- Ready for Phase 3 (matching service)

---
*Phase: 02-gpt-extraction-service*
*Completed: 2026-03-07*
