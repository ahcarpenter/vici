# Phase 02.14: Normalize Database Schema to Third Normal Form (3NF) - Research

**Researched:** 2026-04-03
**Domain:** PostgreSQL schema design, SQLModel/Alembic, relational normalization
**Confidence:** HIGH

---

## Summary

The Vici schema is already in good shape from a normalization standpoint — it was
deliberately designed with 3NF intent (the migration comment even says "3NF schema").
Most tables have single-column primary keys, no multi-valued attributes, and FK
relationships are correct. However, a targeted audit reveals **four concrete
normalization issues** ranging from a clean 3NF transitive dependency to structural
oddities that violate the spirit of 3NF or produce anomaly-prone designs.

The highest-priority finding is the `job` table: `user_id` is functionally determined
by `message_id` (because `message.user_id` already records the message owner), making
`job.user_id` a transitive dependency on the non-key column `message_id`. The same
pattern applies identically to `work_goal`. These two cases are canonical 3NF
violations and should be the focus of the normalization migration.

Secondary findings include: (1) `audit_log` redundantly stores `message_sid` alongside a
nullable FK to `message`, creating a partial denormalization; (2) `rate_limit` is a
rolling-window counter table with a stale unique constraint the codebase already flags
as a TODO for removal; (3) `job.pay_type` / `pinecone_sync_queue.status` use
unconstrained strings in the model layer despite check constraints in the DB — a minor
consistency issue, not a 3NF violation.

**Primary recommendation:** Remove `user_id` from `job` and `work_goal` (derive it via
JOIN through `message`); resolve the `audit_log` dual-key redundancy; drop the stale
unique constraint on `rate_limit`. These three migrations are independent and can be
sequenced safely.

---

## Project Constraints (from CLAUDE.md)

- Organize code by domain (`src/{domain}/`).
- Use `async def` routes with `await`; use `def` for blocking I/O.
- `BaseRepository._persist` is the flush-only write primitive; callers own transactions.
- Use `ruff check --fix src && ruff format src` for linting.
- Apply SOLID + DRY + GoF patterns; constantize all magic numbers.
- Alembic migration filenames: `YYYY-MM-DD_slug.py`; keep migrations static and reversible.
- Explicit index naming via `POSTGRES_INDEXES_NAMING_CONVENTION` in `src/database.py`.
- Use `lower_case_snake` table/column names; singular table names.

---

## Current Schema State

### Tables and Columns

#### `user`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| phone_hash | VARCHAR | UNIQUE, NOT NULL, indexed |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `message`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| message_sid | VARCHAR | UNIQUE, NOT NULL, indexed |
| user_id | INTEGER | FK → user.id RESTRICT, NOT NULL, indexed |
| body | TEXT | NOT NULL |
| message_type | VARCHAR | nullable |
| raw_gpt_response | TEXT | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `job`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| user_id | INTEGER | FK → user.id RESTRICT, NOT NULL |
| message_id | INTEGER | FK → message.id RESTRICT, NOT NULL, UNIQUE |
| description | TEXT | nullable |
| location | TEXT | nullable |
| pay_rate | FLOAT | nullable, CHECK > 0 |
| pay_type | VARCHAR | NOT NULL, default 'unknown', CHECK IN ('hourly','flat','unknown') |
| estimated_duration_hours | FLOAT | nullable, CHECK > 0 |
| raw_duration_text | TEXT | nullable |
| ideal_datetime | TIMESTAMPTZ | nullable |
| raw_datetime_text | TEXT | nullable |
| inferred_timezone | TEXT | nullable |
| datetime_flexible | BOOLEAN | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `work_goal`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| user_id | INTEGER | FK → user.id RESTRICT, NOT NULL |
| message_id | INTEGER | FK → message.id RESTRICT, NOT NULL, UNIQUE |
| target_earnings | FLOAT | NOT NULL, CHECK > 0 |
| target_timeframe | TEXT | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `match`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| job_id | INTEGER | FK → job.id RESTRICT, NOT NULL |
| work_goal_id | INTEGER | FK → work_goal.id RESTRICT, NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| — | — | UNIQUE(job_id, work_goal_id) |

#### `rate_limit`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| user_id | INTEGER | FK → user.id RESTRICT, NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| count | INTEGER | NOT NULL, default 1 |
| — | — | UNIQUE(user_id, created_at) — stale, flagged TODO |

#### `audit_log`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| message_sid | VARCHAR | NOT NULL, indexed |
| message_id | INTEGER | FK → message.id SET NULL, nullable |
| event | VARCHAR | NOT NULL |
| detail | TEXT | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `pinecone_sync_queue`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, autoincrement |
| job_id | INTEGER | FK → job.id CASCADE, NOT NULL |
| status | VARCHAR | NOT NULL, default 'pending', CHECK IN ('pending','synced','failed') |
| attempts | INTEGER | NOT NULL, default 0 |
| last_error | TEXT | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

### Relationship Map

```
user ──< message ──< job ──< pinecone_sync_queue
              └────< work_goal
job >──< match ──< work_goal
user ──< rate_limit
message ──< audit_log (nullable)
```

---

## 3NF Violation Analysis

### Violation 1 (HIGH PRIORITY): Transitive Dependency — `job.user_id`

**3NF rule violated:** Every non-key attribute must depend on the key, the whole key,
and nothing but the key.

**The dependency chain:**
```
job.id → job.message_id → message.user_id
                ↑
job.user_id is also present — transitive dependency on message_id
```

Because `message_id` is a UNIQUE FK in `job` (one-to-one), `job.message_id` uniquely
identifies a `user`. Therefore `job.user_id` is transitively determined by
`job.message_id` via `message.user_id`. Storing it in both places creates an update
anomaly: if `message.user_id` were ever reassigned, `job.user_id` would be stale.

**Affected table:** `job`
**Column to remove:** `user_id`
**Replacement query pattern:** `SELECT m.user_id FROM job j JOIN message m ON m.id = j.message_id`

**Code impact:**
- `src/jobs/models.py` — remove `user_id` field
- `src/jobs/schemas.py` (`JobCreate`) — remove `user_id` field
- `src/jobs/repository.py` (`JobRepository.create`) — remove `user_id=job_create.user_id` assignment
- `src/pipeline/handlers/job_posting.py` — likely passes `user_id` into `JobCreate`; audit required
- Any query that filters `job.user_id` must be rewritten to join through `message`

---

### Violation 2 (HIGH PRIORITY): Transitive Dependency — `work_goal.user_id`

**Identical pattern to Violation 1.**

Because `work_goal.message_id` is UNIQUE and FK → `message.id`, and `message.user_id`
already records the owner, `work_goal.user_id` is transitively determined through
`message_id`.

**Affected table:** `work_goal`
**Column to remove:** `user_id`
**Replacement query pattern:** `SELECT m.user_id FROM work_goal wg JOIN message m ON m.id = wg.message_id`

**Code impact:**
- `src/work_goals/models.py` — remove `user_id` field
- `src/work_goals/schemas.py` (`WorkGoalCreate`) — remove `user_id` field
- `src/work_goals/repository.py` (`WorkGoalRepository.create`) — remove `user_id` assignment
- `src/pipeline/handlers/worker_goal.py` — likely passes `user_id` into `WorkGoalCreate`; audit required

---

### Violation 3 (MEDIUM PRIORITY): Dual-Key Redundancy — `audit_log.message_sid`

**3NF issue:** `audit_log` stores both `message_sid` (the natural business key) and
`message_id` (a nullable FK to `message`). The `message_sid` in `audit_log` is
functionally determined by `message_id` when the FK is non-null
(`message_id → message.message_sid`). The column exists as a fallback for pre-message
audit events (e.g., logging a duplicate before the message row is created), which is a
legitimate intentional design — but it introduces a risk: after the `message` row is
created and `message_id` is backfilled, `audit_log.message_sid` can diverge from
`message.message_sid`.

**Options:**
1. Accept the intentional denormalization and add a DB CHECK or application-level
   assertion that `message_sid` in `audit_log` equals `message.message_sid` when
   `message_id` is non-null (preferred — low-risk, no schema change needed).
2. Remove `message_sid` from `audit_log` entirely and derive it via JOIN when needed.
   This requires changing the write path: the pre-message audit events must either
   store only the raw SID in a separate column, or the audit log must allow
   `message_id = NULL` rows with no SID cross-reference. More invasive.

**Recommendation:** Option 1. Add a DB-level check constraint or comment documenting
the intended invariant. The column is deliberately kept for pre-message audit events
and is the indexed lookup key — removing it would hurt query performance.

---

### Violation 4 (LOW PRIORITY): Stale Unique Constraint — `rate_limit.(user_id, created_at)`

**Issue:** The `rate_limit` table uses a rolling-window count pattern (insert one row
per message, count rows in the last N seconds). The UNIQUE constraint on
`(user_id, created_at)` was from an earlier design (upsert pattern) and is no longer
compatible with the current insert-per-event approach. The `MessageRepository` already
has a TODO comment noting this:

```python
# TODO: A migration to drop the UNIQUE constraint on (user_id, created_at)
# in the rate_limit table is needed before deploying this rolling-window change.
```

This is not a 3NF violation per se, but it is a schema correctness issue that lives
in the same migration work.

**Fix:** Drop `uq_rate_limit_user_window` constraint. Add a non-unique index on
`(user_id, created_at)` for query performance on the rolling COUNT query.

---

### Non-Issues (Confirmed Not Violations)

| Item | Verdict | Reason |
|------|---------|--------|
| `message.raw_gpt_response` | Not a violation | Stores raw AI output tied to this message; no transitive dep |
| `job.raw_datetime_text`, `raw_duration_text` | Not a violation | Raw extraction artifacts stored alongside parsed values; all depend on job.id |
| `job.inferred_timezone` | Not a violation | A derived/inferred attribute, but it describes the job fact, not another entity |
| `pinecone_sync_queue` standalone table | Not a violation | Correctly extracted as its own entity keyed by job_id |
| `match` table | Not a violation | Correctly models M:M between job and work_goal |
| `work_goal.target_timeframe` as text | Not a violation | Unstructured text; no hidden entity to extract |

---

## Recommended Normalization Changes

### Change 1: Remove `job.user_id`

```sql
-- Migration: drop column
ALTER TABLE job DROP COLUMN user_id;

-- New query pattern for "get jobs by user":
SELECT j.*
FROM job j
JOIN message m ON m.id = j.message_id
WHERE m.user_id = :user_id;
```

**Model change (`src/jobs/models.py`):** Remove `user_id` field and its FK definition.
**Schema change (`src/jobs/schemas.py`):** Remove `user_id` from `JobCreate`.
**Repository change (`src/jobs/repository.py`):** Remove `user_id` kwarg from `Job(...)`.
**Handler audit required:** `src/pipeline/handlers/job_posting.py`.

---

### Change 2: Remove `work_goal.user_id`

```sql
ALTER TABLE work_goal DROP COLUMN user_id;
```

Same pattern as Change 1 applied to work_goal.

**Model change:** `src/work_goals/models.py`
**Schema change:** `src/work_goals/schemas.py`
**Repository change:** `src/work_goals/repository.py`
**Handler audit required:** `src/pipeline/handlers/worker_goal.py`

---

### Change 3: Drop stale unique constraint on `rate_limit`

```sql
ALTER TABLE rate_limit DROP CONSTRAINT uq_rate_limit_user_window;
CREATE INDEX ix_rate_limit_user_created_at ON rate_limit (user_id, created_at);
```

No model, schema, or repository code changes required beyond removing the
`UniqueConstraint` from `RateLimit.__table_args__` in `src/sms/models.py`.

---

### Change 4 (optional): Enforce `audit_log` invariant

Add a DB-level check or documentation comment that `audit_log.message_sid` must
equal `message.message_sid` when `message_id IS NOT NULL`. No column removals.

---

## Migration Strategy

### Order of Operations

Changes 1 and 2 are DDL-only (`DROP COLUMN`). They are safe to apply after the
application code is updated to stop writing those columns. Changes 3 is also
DDL-only and independent.

**Recommended sequence:**

```
Wave 1 (code): Remove user_id from Job, WorkGoal models + schemas + repositories + handlers
Wave 2 (migration): Single Alembic revision: drop job.user_id, work_goal.user_id,
                    drop uq_rate_limit_user_window, add rate_limit index
Wave 3 (optional): Add audit_log check constraint or comment
```

### Single Migration File Approach

All three structural changes can go in one migration revision since they are
independent DDL operations with no data transformation required (we are dropping
columns, not transforming values).

```python
# migrations/versions/2026-04-XX_normalize_3nf.py
def upgrade():
    op.drop_column("job", "user_id")
    op.drop_column("work_goal", "user_id")
    op.drop_constraint("uq_rate_limit_user_window", "rate_limit", type_="unique")
    op.create_index("ix_rate_limit_user_created_at", "rate_limit",
                    ["user_id", "created_at"])

def downgrade():
    op.drop_index("ix_rate_limit_user_created_at", table_name="rate_limit")
    op.create_unique_constraint("uq_rate_limit_user_window", "rate_limit",
                                ["user_id", "created_at"])
    op.add_column("work_goal", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "work_goal", "user", ["user_id"], ["id"],
                          ondelete="RESTRICT")
    op.add_column("job", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "job", "user", ["user_id"], ["id"],
                          ondelete="RESTRICT")
```

Note: downgrade columns come back as nullable because we cannot restore the original
NOT NULL constraint without data. This is acceptable for a reversible migration.

---

## Risk Assessment

### Change 1 & 2: Remove `user_id` from `job` / `work_goal` — MEDIUM RISK

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Application writes `user_id` after column dropped | HIGH if not sequenced | Update code before running migration |
| Query filters on `job.user_id` directly | MEDIUM — must audit all query sites | grep for `job.user_id` and `work_goal.user_id` in all files |
| Performance regression on "jobs by user" queries | LOW — add index on `message.user_id` if not present | Verify `ix_message_user_id` index exists (it does, per migration 001) |
| Tests that assert `job.user_id` | MEDIUM | `tests/test_repositories.py`, integration tests need updating |

**Already mitigated:** `message.user_id` has an index (`ix_message_user_id`) from the
initial schema migration. The JOIN path is fast.

### Change 3: Drop unique constraint on `rate_limit` — LOW RISK

The `enforce_rate_limit` method already inserts without relying on ON CONFLICT
(plain INSERT). The constraint currently causes integrity errors in the rolling-window
path if two messages arrive at the same timestamp. Dropping it is strictly an
improvement. A non-unique index replaces it for query performance.

### Change 4: `audit_log` constraint — NEGLIGIBLE RISK

Adding a check constraint or comment has zero behavioral impact on existing code paths.

---

## Impact on Existing Code

### Files requiring changes for Changes 1 & 2

```
src/jobs/models.py            — remove user_id field
src/jobs/schemas.py           — remove user_id from JobCreate
src/jobs/repository.py        — remove user_id kwarg in Job(...)
src/work_goals/models.py      — remove user_id field
src/work_goals/schemas.py     — remove user_id from WorkGoalCreate
src/work_goals/repository.py  — remove user_id kwarg in WorkGoal(...)
src/pipeline/handlers/job_posting.py    — remove user_id from JobCreate construction
src/pipeline/handlers/worker_goal.py   — remove user_id from WorkGoalCreate construction
```

### Files requiring changes for Change 3

```
src/sms/models.py             — remove UniqueConstraint from RateLimit.__table_args__
```

### Test files requiring updates

```
tests/test_repositories.py            — rate_limit and message tests
tests/integration/test_job_posting.py — JobCreate construction
tests/integration/test_worker_goal.py — WorkGoalCreate construction
```

### Files confirmed NOT requiring changes

- `src/matches/models.py` — no user_id
- `src/extraction/models.py` — no user_id
- `src/users/repository.py` — not affected
- `src/sms/repository.py` — only inserts rate_limit rows, no user_id on job/work_goal
- `src/sms/audit_repository.py` — not affected

---

## Architecture Patterns

### Recommended: Derive user_id via JOIN, not redundant column

After removing `job.user_id` and `work_goal.user_id`, any service code that needs
"the user who posted this job" should use a JOIN:

```python
# Source: project pattern — message is the authoritative user_id source
from sqlmodel import select
from src.jobs.models import Job
from src.sms.models import Message

stmt = (
    select(Job, Message.user_id)
    .join(Message, Message.id == Job.message_id)
    .where(Message.user_id == user_id)
)
```

This is idiomatic for 3NF schemas and avoids update anomalies.

### Recommended: Index strategy after changes

After dropping `job.user_id` and `work_goal.user_id`, confirm these indexes exist:
- `ix_message_user_id` on `message(user_id)` — EXISTS (migration 001)
- `ix_job_message_id` — does NOT exist as a named index (only implicit from UNIQUE constraint `uq_job_message_id`)

The UNIQUE constraint on `job.message_id` provides equivalent lookup performance for
joining job → message. No new indexes required.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Schema migration | Manual SQL scripts | Alembic with static, reversible revisions |
| Null-safe column removal | Custom data migration | Alembic `drop_column` — no data to migrate since we're dropping redundant FKs |
| Index creation | ORM meta | Alembic `create_index` with explicit names per naming convention |

---

## Common Pitfalls

### Pitfall 1: Code changes after migration runs
**What goes wrong:** Migration drops `job.user_id` while application still writes it — INSERT fails.
**Prevention:** Always update application code and deploy BEFORE running the migration. In this project's dev workflow, that means running `alembic upgrade head` only after the model/schema/repository/handler code no longer references `user_id`.

### Pitfall 2: Downgrade leaves NOT NULL restored incorrectly
**What goes wrong:** Downgrade adds `user_id` back as nullable but original was NOT NULL — any row inserted during the migration window has NULL user_id and will fail NOT NULL check if it's later re-added as NOT NULL.
**Prevention:** Keep downgrade as nullable. Document this limitation. In practice, this migration should be treated as one-way for production.

### Pitfall 3: Test fixtures pass `user_id` to `JobCreate` / `WorkGoalCreate`
**What goes wrong:** Tests fail immediately after removing the field from the schema because fixtures still construct the Pydantic model with the removed field.
**Prevention:** Update all test fixture `make_job` / `make_work_goal` helpers in `tests/conftest.py` as part of the same PR as the model changes.

### Pitfall 4: Forgetting to update `UniqueConstraint` in model `__table_args__`
**What goes wrong:** Alembic `autogenerate` sees a mismatch between the model (which still declares the constraint) and the DB (which no longer has it) and generates a spurious re-create migration.
**Prevention:** Remove the `UniqueConstraint` entry from `RateLimit.__table_args__` at the same time as the migration.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/test_repositories.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| 3NF-01 | `job` table has no `user_id` column | schema/smoke | `pytest tests/integration/test_job_posting.py -x` | Yes |
| 3NF-02 | `work_goal` table has no `user_id` column | schema/smoke | `pytest tests/integration/test_worker_goal.py -x` | Yes |
| 3NF-03 | `JobCreate` Pydantic schema has no `user_id` field | unit | `pytest tests/ -k "job" -x` | Partial |
| 3NF-04 | `WorkGoalCreate` Pydantic schema has no `user_id` field | unit | `pytest tests/ -k "work_goal" -x` | Partial |
| 3NF-05 | `rate_limit` unique constraint removed; inserts succeed under rolling-window | unit | `pytest tests/test_repositories.py::test_enforce_rate_limit_under_limit -x` | Yes |
| 3NF-06 | `rate_limit` rolling-window count correctly detects over-limit | unit | `pytest tests/test_repositories.py::test_enforce_rate_limit_over_limit -x` | Yes |

### Wave 0 Gaps

- [ ] Add model-level test asserting `Job` has no `user_id` attribute (covers 3NF-01 at unit level)
- [ ] Add model-level test asserting `WorkGoal` has no `user_id` attribute (covers 3NF-02 at unit level)
- [ ] Update `tests/conftest.py` fixtures: `make_job` and `make_work_goal` must not pass `user_id`

---

## Open Questions

1. **Does any external caller (Temporal activity, router) pass `user_id` to `JobCreate`?**
   - What we know: `src/pipeline/handlers/job_posting.py` and `worker_goal.py` construct these objects
   - What's unclear: whether they receive `user_id` from Temporal workflow context and pass it through
   - Recommendation: Read both handler files fully before writing plan tasks; add grep for `user_id` across all `src/` files

2. **Does `match` need a `user_id` for fast "matches for user X" queries?**
   - What we know: `match` links `job_id` → `work_goal_id`; user is derivable through either FK chain
   - What's unclear: whether there's a planned query that filters matches by user without joining both sides
   - Recommendation: Accept the JOIN path for now; add a covering index if profiling reveals a bottleneck

3. **Is `job.inferred_timezone` a candidate for a lookup table (enum normalization)?**
   - What we know: stored as free-text string (e.g., "America/New_York")
   - What's unclear: whether the set of valid values is bounded and whether queries filter on it
   - Recommendation: Leave as text for now; IANA timezone strings are a well-known controlled set but a lookup table adds complexity with minimal normalization benefit

---

## Sources

### Primary (HIGH confidence)
- Direct inspection of `src/jobs/models.py`, `src/work_goals/models.py`, `src/sms/models.py`, `src/extraction/models.py`, `src/matches/models.py`, `src/users/models.py`
- Direct inspection of `migrations/versions/2026-03-05_initial_schema.py` and `2026-03-06_extraction_additions.py`
- Direct inspection of all repository files under `src/`
- Direct inspection of `tests/test_repositories.py` and integration test files
- 3NF definition: Codd (1971) — a relation is in 3NF if every non-key attribute depends on the key, the whole key, and nothing but the key

### Secondary (MEDIUM confidence)
- SQLModel documentation (version 0.0.37) — column and FK declaration patterns
- Alembic documentation — `drop_column`, `drop_constraint`, `create_index` operations

---

## Metadata

**Confidence breakdown:**
- Schema inventory: HIGH — read directly from source files
- 3NF violation analysis: HIGH — follows from functional dependency analysis of actual columns
- Migration strategy: HIGH — standard Alembic patterns, no exotic operations
- Code impact: HIGH — traced through all relevant files
- Test coverage gaps: MEDIUM — integration tests exist but their exact fixture signatures require reading `tests/conftest.py` fully

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (schema is stable; valid until next schema migration)
