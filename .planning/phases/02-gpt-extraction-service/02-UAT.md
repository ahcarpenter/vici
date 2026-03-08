---
status: testing
phase: 02-gpt-extraction-service
source: 02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md
started: 2026-03-07T21:00:00Z
updated: 2026-03-07T21:00:00Z
---

## Current Test

number: 2
name: Job posting classification
expected: |
  Send a POST to `POST /sms` (Twilio webhook format) with a body that reads like a job posting
  (e.g. "Need a plumber tomorrow morning, 2 hours, $80/hr, downtown Seattle"). The Inngest
  `process-message` function fires, calls GPT, and stores a row in the `job` table with
  `message_type = 'job_posting'`. No errors in logs.
awaiting: user response

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running containers. Run `docker compose down -v && docker compose up -d --build`. Migrations run cleanly (no errors in logs). Server boots and `curl http://localhost:8000/health` returns `{"status": "ok"}`. `curl http://localhost:8000/readyz` returns `{"status": "ok", "db": "connected"}`.
result: pass

### 2. Job posting classification
expected: Send a POST to `POST /sms` (Twilio webhook format) with a body that reads like a job posting (e.g. "Need a plumber tomorrow morning, 2 hours, $80/hr, downtown Seattle"). The Inngest `process-message` function fires, calls GPT, and stores a row in the `job` table with `message_type = 'job_posting'`. No errors in logs.
result: [pending]

### 3. Worker goal classification
expected: Send a POST to `POST /sms` with a worker earnings goal (e.g. "I need to make $200 today"). The Inngest `process-message` function fires, calls GPT, and stores a row in the `work_request` table with `message_type = 'worker_goal'`. No errors in logs.
result: [pending]

### 4. Unknown classification triggers Twilio SMS reply
expected: Send a POST to `POST /sms` with an unclassifiable message (e.g. "Hello?"). GPT classifies it as `unknown`. The service calls Twilio and sends an outbound SMS back to the sender's number using the `UNKNOWN_REPLY_TEXT` constant. (Requires `TWILIO_FROM_NUMBER` set in `.env` and a test Twilio number.)
result: [pending]

### 5. Full test suite passes
expected: Run `pytest tests/ -q` in the project root. All 29 tests pass, 0 failures, 0 errors.
result: [pending]

## Summary

total: 5
passed: 1
issues: 0
pending: 4
skipped: 0

## Gaps

[none yet]
