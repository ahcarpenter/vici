---
phase: 03-earnings-math-matching
plan: 01
subsystem: matches
tags: [matching, dp-knapsack, sms-formatter, earnings-math]
dependency_graph:
  requires: [jobs, work_goals, users, sms]
  provides: [MatchService, format_match_sms, MatchRepository]
  affects: [pipeline, temporal]
tech_stack:
  added: []
  patterns: [0/1-knapsack-DP, savepoint-idempotency, bulk-N+1-avoidance]
key_files:
  created:
    - src/matches/schemas.py
    - src/matches/service.py
    - src/matches/formatter.py
    - src/matches/repository.py
    - migrations/versions/2026-04-04_add_phone_e164.py
    - migrations/versions/2026-04-04_add_job_status.py
    - tests/matches/__init__.py
    - tests/matches/test_match_service.py
  modified:
    - src/users/models.py
    - src/users/repository.py
    - src/jobs/models.py
    - src/jobs/repository.py
    - tests/conftest.py
decisions:
  - "DP capacity uses max_possible_cents (not capped at target) to allow single items exceeding target to be selected"
  - "MatchRepository uses begin_nested() savepoint per insert for cross-dialect idempotency instead of full session rollback"
  - "make_user fixture uses incrementing counter for unique phone_hash to avoid UNIQUE constraint violations across multiple factory calls"
metrics:
  duration: 6m 32s
  completed: 2026-04-04
  tasks: 3
  files: 13
---

# Phase 03 Plan 01: Earnings Math Matching Summary

MatchService with 0/1 knapsack DP selecting jobs by earnings math, SMS formatter with poster phone and partial-match summary, cross-dialect idempotent persistence via savepoint pattern.

## What Was Built

1. **Schema extensions**: `User.phone_e164` (nullable E.164 phone) and `Job.status` (CHECK-constrained, server_default='available') with two chained Alembic migrations (004, 005).

2. **MatchService**: Accepts a WorkGoal, queries candidate jobs via `JobRepository.find_candidates_for_goal()` (SQL pre-filter + Python-level exclusion logging), builds `JobCandidate` list with bulk N+1 avoidance (single query for messages, single query for users), runs 0/1 knapsack DP (earnings quantized to cents, dual-objective: maximize earnings then minimize duration), sorts by soonest `ideal_datetime` then shortest duration (NULL dates last), persists match records.

3. **SMS Formatter**: `format_match_sms()` produces ranked job lines with poster phone, partial-match summary when `is_partial=True`, graceful empty-match fallback, max 5 jobs per SMS.

4. **MatchRepository**: `persist_matches()` uses `begin_nested()` savepoints per insert with IntegrityError catch for cross-dialect (PostgreSQL + SQLite) idempotent duplicate handling.

5. **Test Suite**: 15 tests covering all MATCH-01/02/03 acceptance criteria. Full regression suite passes (116 tests + 15 new = 131 total, 1 skipped).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DP capacity cap prevented items exceeding target from selection**
- **Found during:** Task 3 (test_dp_meets_goal failure)
- **Issue:** Plan code used `capacity = min(target_cents, max_possible_cents)` which prevented a $50 job from being selected for a $40 target because `e_cents (5000) > capacity (4000)` made the inner loop range empty.
- **Fix:** Changed to `capacity = max_possible_cents` so all items can be considered regardless of whether individual earnings exceed target.
- **Files modified:** src/matches/service.py
- **Commit:** 74a492a

**2. [Rule 1 - Bug] MatchRepository rollback destroyed prior inserts**
- **Found during:** Task 3 (test_match_persistence_idempotent failure)
- **Issue:** Plan code used `await session.rollback()` on IntegrityError, which rolled back the entire session including previously successful inserts in the same `persist_matches` call.
- **Fix:** Changed to `async with session.begin_nested()` (SAVEPOINT) so only the duplicate insert is rolled back, preserving prior successful inserts.
- **Files modified:** src/matches/repository.py
- **Commit:** 74a492a

**3. [Rule 1 - Bug] make_user fixture created duplicate phone_hash**
- **Found during:** Task 3 (test_null_pay_rate_excluded failure)
- **Issue:** Default phone_hash was static `sha256(b"default_phone")`, causing UNIQUE constraint violations when multiple `make_job` calls each created a new user within the same test.
- **Fix:** Added incrementing counter to generate unique phone_hash per factory call.
- **Files modified:** tests/conftest.py
- **Commit:** 74a492a

## Verification Results

- `pytest tests/matches/test_match_service.py -v`: 15/15 passed
- `pytest tests/ -x -q`: 116 passed, 1 skipped, 0 failures
- All model imports clean, migration files exist with correct chained revisions

## Self-Check: PASSED
