---
phase: 01-infrastructure-foundation
plan: 02
subsystem: api
tags: [twilio, fastapi, sqlite, hmac, rate-limiting, idempotency, webhook]

requires:
  - phase: 01-01
    provides: SQLModel domain models (Phone, InboundMessage, RateLimit, AuditLog), database session dependency, FastAPI app

provides:
  - POST /webhook/sms route enforcing four-gate security chain (HMAC, idempotency, rate limiting, phone registration)
  - validate_twilio_request FastAPI Depends() — HMAC validation raising HTTP 403 on failure
  - hash_phone — SHA-256 of E.164 phone number
  - check_idempotency — MessageSid duplicate detection
  - enforce_rate_limit — upsert-based 1-minute window rate limiter (5 msg/min cap)
  - register_phone — idempotent phone identity creation
  - write_audit_log / write_inbound_message — record persistence
  - 7 passing webhook tests covering all security gates

affects:
  - 01-03 (Inngest event emission — adds emit_message_received_event call to existing router)

tech-stack:
  added: [python-multipart==0.0.22]
  patterns:
    - FastAPI Depends() for request validation gates
    - Raw SQL ON CONFLICT upserts for idempotent writes (SQLite and PostgreSQL compatible)
    - Phone identity hashed at boundary, hash stored throughout system

key-files:
  created:
    - src/sms/dependencies.py
    - src/sms/service.py
  modified:
    - src/sms/router.py
    - tests/sms/test_webhook.py
    - pyproject.toml

key-decisions:
  - "validate_twilio_request raises HTTPException(403) directly rather than TwilioSignatureInvalid — simpler for dependency pattern"
  - "register_phone raw SQL includes created_at explicitly — SQLModel default_factory does not fire for raw SQL inserts"
  - "enforce_rate_limit uses commit-then-read pattern to get accurate count after upsert"

patterns-established:
  - "Security gate pattern: Depends() handles Gate 1; remaining gates are ordered cheapest-first in route body"
  - "Raw SQL upserts for PostgreSQL ON CONFLICT DO UPDATE — compatible with SQLite test DB via aiosqlite"

requirements-completed: [SEC-01, SEC-02, SEC-03, SEC-04, IDN-01, IDN-02]

duration: 15min
completed: 2026-03-06
---

# Phase 1 Plan 02: Webhook Security Gate Chain Summary

**POST /webhook/sms with Twilio HMAC validation, MessageSid idempotency, upsert-based rate limiting, and phone auto-registration via four-gate FastAPI dependency chain**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-06T07:20:00Z
- **Completed:** 2026-03-06T07:35:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Implemented full four-gate security chain: HMAC (Twilio RequestValidator), idempotency, rate limiting, phone auto-registration
- All 7 webhook behavior tests pass; test_inngest_event_emitted skipped cleanly for Plan 03
- Fixed register_phone raw SQL to include created_at (NOT NULL constraint on SQLite)
- Added python-multipart dependency required for form parsing

## Task Commits

1. **Task 1: dependencies.py + service.py** - `d7d6ad5` (feat)
2. **Task 2: router.py + test_webhook.py** - `d7c897c` (feat)

## Files Created/Modified

- `src/sms/dependencies.py` - validate_twilio_request FastAPI dependency
- `src/sms/service.py` - hash_phone, check_idempotency, enforce_rate_limit, register_phone, write_audit_log, write_inbound_message
- `src/sms/router.py` - POST /webhook/sms four-gate route
- `tests/sms/test_webhook.py` - 7 webhook behavior tests (1 skipped)
- `pyproject.toml` - added python-multipart

## Decisions Made

- validate_twilio_request raises HTTPException(403) directly rather than TwilioSignatureInvalid — simpler in dependency pattern
- register_phone raw SQL must include created_at explicitly — SQLModel default_factory only fires for ORM inserts, not raw SQL
- enforce_rate_limit commits after upsert then reads back count — ensures consistent read after write in async SQLAlchemy

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing python-multipart dependency**
- **Found during:** Task 2 (running webhook tests)
- **Issue:** Starlette raised AssertionError for form parsing without python-multipart installed
- **Fix:** `uv add python-multipart`
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** All tests pass after install
- **Committed in:** d7c897c (Task 2 commit)

**2. [Rule 1 - Bug] register_phone raw SQL missing created_at**
- **Found during:** Task 2 (test_valid_signature failure)
- **Issue:** Raw SQL INSERT omitted created_at; SQLite enforces NOT NULL at DB level even though SQLModel sets default_factory
- **Fix:** Added `:created_at` parameter with `datetime.utcnow()` to raw SQL INSERT
- **Files modified:** src/sms/service.py
- **Verification:** test_valid_signature and test_phone_created_at both pass
- **Committed in:** d7c897c (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes essential for tests to pass. No scope creep.

## Issues Encountered

None beyond the two auto-fixed deviations above.

## Next Phase Readiness

- Webhook security gate chain complete; ready for Plan 03 (Inngest event emission)
- Plan 03 will add `emit_message_received_event` call after write_inbound_message in router.py
- test_inngest_event_emitted stub is in place and skipped, ready to be un-skipped in Plan 03

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-03-06*
