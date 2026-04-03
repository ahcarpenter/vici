# Language Audit: 260403-7kp

## Category 1: Stale Domain Names (Inngest references)

| # | File | Line | Current | Suggested |
|---|------|------|---------|-----------|
| 1 | src/metrics.py | 37-39 | `inngest_queue_depth = Gauge("inngest_queue_depth", "Stub gauge -- Inngest dev server...")` | Rename to `temporal_queue_depth` with description referencing Temporal, or remove entirely since it's a stub |
| 2 | src/metrics.py | 41 | `# inngest_queue_depth always reads 0; placeholder for future instrumentation` | Update comment to reference Temporal |
| 3 | src/metrics.py | 45 | `"Total number of process-message Inngest function permanent failures"` | Change to `"Total number of process-message Temporal workflow permanent failures"` |
| 4 | tests/extraction/test_metrics.py | 35-38 | `test_inngest_queue_depth_settable` importing `inngest_queue_depth` | Rename test and import to match new metric name |
| 5 | tests/integration/test_worker_goal.py | 4 | `NOTE: ... was removed when Inngest was replaced by Temporal` | This is historical context and accurate -- keep as-is |

## Category 2: Stale Domain Names (work_request references)

| # | File | Line | Current | Suggested |
|---|------|------|---------|-----------|
| 6 | tests/test_pipeline_orchestrator.py | 120 | `# Work request repo must NOT be called` | Change to `# Work goal repo must NOT be called` |

## Category 3: Stale TODO Comments

| # | File | Line | Current | Suggested |
|---|------|------|---------|-----------|
| 7 | src/sms/repository.py | 29 | `# TODO: A migration to drop the UNIQUE constraint on (user_id, created_at)` | Keep -- this is a genuine outstanding TODO |

## Category 4: Non-idiomatic Python / Inconsistent Terminology

No significant issues found. Variable naming follows PEP 8 throughout. `phone_hash` is consistent across all files. Error messages and log strings use structlog key=value style correctly.

## Summary

- 4 actionable Inngest references to update in production code and tests
- 1 stale "work_request" comment in tests
- 1 historical Inngest reference (keep as-is -- accurate context)
- 1 valid TODO (keep)
