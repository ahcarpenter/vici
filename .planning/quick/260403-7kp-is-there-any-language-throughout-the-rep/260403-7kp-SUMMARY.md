---
phase: quick
plan: 260403-7kp
subsystem: codebase-wide
tags: [language-audit, naming, terminology]
key-files:
  modified:
    - src/metrics.py
    - tests/extraction/test_metrics.py
    - tests/test_pipeline_orchestrator.py
decisions:
  - "Renamed inngest_queue_depth to temporal_queue_depth (not removed) to preserve metric continuity"
  - "Kept historical Inngest reference in test_worker_goal.py docstring as accurate context"
metrics:
  completed: "2026-04-03"
  tasks: 3
  files_modified: 3
---

# Quick Task 260403-7kp: Language Audit Summary

Replaced 4 stale Inngest references with Temporal equivalents and fixed 1 stale work_request comment; all 101 tests pass, zero new lint issues.

## Changes Made

### Stale Inngest References (4 fixes)

1. **src/metrics.py**: Renamed `inngest_queue_depth` gauge to `temporal_queue_depth` with updated description
2. **src/metrics.py**: Updated `pipeline_failures_total` description from "Inngest function" to "Temporal workflow"
3. **src/metrics.py**: Updated placeholder comment to reference Temporal
4. **tests/extraction/test_metrics.py**: Renamed `test_inngest_queue_depth_settable` to `test_temporal_queue_depth_settable` with updated import

### Stale Domain References (1 fix)

5. **tests/test_pipeline_orchestrator.py:120**: Changed comment from "Work request repo" to "Work goal repo"

### Items Retained As-Is

- **tests/integration/test_worker_goal.py:4**: Historical note "removed when Inngest was replaced by Temporal" -- accurate context, not stale
- **src/sms/repository.py:29**: TODO about migration constraint -- genuine outstanding work item

## Verification

- 101 tests passed, 1 skipped
- `rg -i "inngest" src/` returns zero hits
- `rg "WorkRequest" src/ tests/` returns zero hits
- `rg "worker_request" src/ tests/` returns zero hits
- No new ruff check or format issues introduced

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 95beb5c | Audit non-canonical language across codebase |
| 2 | 3532ed7 | Replace stale Inngest and work_request references |
| 3 | (verification only, no commit) | Final grep validation |
