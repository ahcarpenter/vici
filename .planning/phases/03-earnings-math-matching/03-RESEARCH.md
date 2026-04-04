# Phase 3: Earnings Math Matching — Research

**Researched:** 2026-04-04
**Domain:** Python DP matching algorithm, SQLAlchemy async query, Alembic migration, SMS formatting, pytest fixtures
**Confidence:** HIGH — all findings drawn from reading the actual codebase; no external sources needed for core decisions

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** `pay_type='hourly'` → `job_earnings = pay_rate × estimated_duration_hours`
- **D-02:** `pay_type='flat'` → `job_earnings = pay_rate` (flat rate is total pay; duration irrelevant)
- **D-03:** `pay_type='unknown'` → exclude from candidate set entirely
- **D-04:** Use a DP knapsack-style algorithm. Primary objective: maximize total earnings targeting `>= target_earnings`. Secondary objective: among subsets meeting the goal, minimize total `estimated_duration_hours`. Jobs with NULL `pay_rate` or NULL `estimated_duration_hours` excluded before DP runs (flat-rate jobs only require non-NULL `pay_rate`).
- **D-05:** If full candidate set cannot reach `target_earnings`, return the subset that gets as close as possible — never return empty when jobs exist.
- **D-06:** DP operates over all available jobs; NULL-field jobs excluded from candidates before DP.
- **D-06a:** Add `status` field to `Job` (`available` | `accepted` | `in_progress` | `completed`, default `available`) in this phase. Candidate query filters `job.status = 'available'`.
- **D-07:** Each SMS job entry includes: description, location, job poster's phone number, total earnings, and duration.
- **D-08:** Return all jobs in DP-selected set; format must respect 160-character SMS segment boundaries (multi-segment OK).
- **D-09:** When set partially meets the goal, include summary line: "Best available: $X of $Y goal". `MatchService` persists each matched `(job_id, work_goal_id)` pair to `match` table after computing results.
- **D-10:** Duplicate match rows handled by existing `UNIQUE(job_id, work_goal_id)` — on conflict, skip. Job poster phone number included as-is in Phase 3 (privacy proxy deferred).
- **D-11:** Results sorted by soonest `ideal_datetime` first, then shortest `estimated_duration_hours`.
- **D-12:** Jobs with NULL `ideal_datetime` sort last.
- **D-13:** When no jobs match, return a designated empty result for graceful "no matches" SMS.

### Claude's Discretion

No explicit discretion areas defined in CONTEXT.md.

### Deferred Ideas (OUT OF SCOPE)

- Phone number privacy proxy (Twilio Proxy or alias)
- Follow-up clarification flow for `pay_type='unknown'` or missing fields
- New-job follow-up notifications when goal was unmet at match time
- Job lifecycle status SMS conversation flow (workers/posters transitioning status via SMS)
- Dual-party status updates and dispute escalation
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MATCH-01 | Compute job matches using earnings math: `rate × estimated_duration >= target_earnings`, sorted by soonest available date then shortest duration | DP algorithm section; SQL query section; sorting pattern |
| MATCH-02 | Send ranked list of 3–5 matching jobs via SMS in condensed format respecting 160-char segment boundaries | SMS formatting section |
| MATCH-03 | Send graceful SMS reply when no jobs match worker goal | Empty-match handling section |
</phase_requirements>

---

## Summary

Phase 3 builds `MatchService` in a codebase with established patterns: flush-only repositories extending `BaseRepository`, structlog for all logging, OTel manual spans via `tracer.start_as_current_span()`, and async SQLAlchemy with SQLite in tests. All fixtures and test infrastructure exist in `tests/conftest.py`. The `make_job` and `make_work_goal` factory fixtures are already present and just need extension to support `status` and richer job fields.

The DP knapsack implementation is straightforward Python — no external library needed. The problem is bounded by realistic job set sizes (10–500 jobs) where an O(n × W) DP on quantized dollar amounts is well within time budget. The primary design challenge is the secondary objective (minimize duration among goal-meeting subsets), which requires tracking two values per DP state.

One critical blocker was discovered during research: **the `User` table stores only `phone_hash`, not the raw E.164 phone number.** D-07 requires "job poster's phone number" in the SMS output, but no join path through `Job → Message → User` can retrieve the original number — only `phone_hash` is persisted. The planner must resolve this before implementing `find_matches_for_goal`. Options and recommendation are in the Open Questions section.

**Primary recommendation:** Implement MatchService as a service class in `src/matches/service.py`, with `MatchRepository` in `src/matches/repository.py` extending `BaseRepository`. Add `find_available_for_match()` to `JobRepository`. The DP runs in pure Python over the candidate list. SMS formatting is a pure function — no library needed.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy (async) | Already installed | Async ORM query for candidate fetch | Used throughout codebase |
| SQLModel | Already installed | ORM model definition | Used throughout codebase |
| Alembic | Already installed | Schema migration for `status` column | Established migration pattern |
| structlog | Already installed | Structured warning logging for excluded jobs | Used throughout codebase |
| opentelemetry-api | Already installed | Manual span for `MatchService.match()` | Used throughout codebase |
| pytest + pytest-asyncio | Already installed | Async test with SQLite in-memory | `asyncio_mode = "auto"` configured |

### No External Libraries Needed
The DP algorithm, SMS character counting, and empty-match handling are all pure Python. No third-party packages required for this phase.

---

## Architecture Patterns

### Recommended File Structure
```
src/matches/
├── __init__.py      # already exists
├── models.py        # already exists (Match model)
├── repository.py    # NEW — MatchRepository(BaseRepository)
├── service.py       # NEW — MatchService
└── schemas.py       # NEW — MatchResult, JobMatch dataclasses/Pydantic models

src/jobs/
├── repository.py    # EXTEND — add find_available_for_match()

migrations/versions/
└── 2026-04-04_add_job_status.py  # NEW — adds status column to job table
```

### Pattern 1: Service receives WorkGoal, returns MatchResult

```python
# src/matches/service.py
import structlog
from opentelemetry import trace as otel_trace

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()

class MatchService:
    def __init__(self, job_repo: JobRepository, match_repo: MatchRepository):
        self._job_repo = job_repo
        self._match_repo = match_repo

    async def match(self, session: AsyncSession, work_goal: WorkGoal) -> MatchResult:
        with tracer.start_as_current_span("pipeline.match_jobs") as span:
            span.set_attribute("work_goal_id", work_goal.id)
            candidates = await self._job_repo.find_available_for_match(session)
            filtered = self._filter_candidates(candidates, work_goal)
            selected = self._dp_select(filtered, work_goal.target_earnings)
            sorted_jobs = self._sort_results(selected)
            await self._persist_matches(session, sorted_jobs, work_goal)
            return MatchResult(jobs=sorted_jobs, work_goal=work_goal)
```

### Pattern 2: DP knapsack with dual-objective tracking

The problem is a variant of the 0/1 knapsack: "find a subset of jobs whose total earnings meet or maximally approach `target_earnings`, and among subsets that meet the goal, minimize total duration."

**Key insight for this problem:** The DP does NOT need integer weights if you quantize earnings to cents. With float earnings, quantize to cents: `weight = int(round(earnings * 100))`. Target becomes `int(round(target_earnings * 100))`.

**Complexity:** O(n × W) where n = number of candidates and W = target in cents. For `target_earnings = $500` → W = 50,000 steps. For 500 jobs at $500 target: 500 × 50,000 = 25M ops — runs in < 1 second in Python.

**If target is very large (>$10,000):** cap W at max achievable earnings from the full candidate set to bound the array size.

```python
# Pure Python DP — no external library
def _dp_select(self, candidates: list[JobCandidate], target: float) -> list[JobCandidate]:
    """
    Returns the subset of candidates that maximizes earnings toward target,
    with secondary objective of minimizing total duration among goal-meeting subsets.

    JobCandidate: dataclass with job, earnings (float), duration (float)
    """
    if not candidates:
        return []

    # Quantize to cents to use integer DP
    SCALE = 100
    target_cents = int(round(target * SCALE))
    max_possible = sum(int(round(c.earnings * SCALE)) for c in candidates)
    capacity = min(target_cents, max_possible)

    n = len(candidates)
    # dp[w] = (max_earnings_cents, min_duration_hours, selected_indices_frozenset)
    # Memory: O(capacity) — one row, updated in reverse
    # Using (earnings, -duration) tuples so max() naturally picks right answer
    NEG_INF = float('-inf')
    # dp[w] = best (earnings_cents, neg_duration) achievable with exactly w earning capacity used
    # Better: dp[w] = best (earnings_cents, neg_total_duration) for subsets with total earnings = w
    # Track full solution: use parent pointers or re-run traceback

    # Standard 0/1 knapsack with tuple values: (total_earnings_cents, neg_total_duration)
    # "Best" = lexicographically greatest: maximize earnings first, then maximize neg_duration (= minimize duration)
    dp = [(NEG_INF, 0.0)] * (capacity + 1)
    dp[0] = (0, 0.0)

    for cand in candidates:
        e_cents = int(round(cand.earnings * SCALE))
        dur = cand.duration
        # Traverse in reverse (0/1 knapsack — each item used at most once)
        for w in range(capacity, e_cents - 1, -1):
            prev_e, prev_neg_d = dp[w - e_cents]
            if prev_e == NEG_INF:
                continue
            candidate_val = (prev_e + e_cents, prev_neg_d - dur)
            if candidate_val > dp[w]:
                dp[w] = candidate_val

    # Find best state: first prefer meeting the goal (w >= target_cents captured by capping capacity)
    # Since capacity = min(target_cents, max_possible), dp[capacity] is the target or max achievable
    # Walk from capacity down to find highest-value reachable state
    best_w = max(
        (w for w in range(capacity + 1) if dp[w][0] != NEG_INF),
        key=lambda w: dp[w],
        default=0,
    )

    # Traceback: re-run DP storing selected items
    # (simpler: re-run with explicit item tracking)
    return self._traceback(candidates, capacity, SCALE)
```

**Simpler traceback approach** — store item selections during DP using a 2D boolean table `selected[i][w]`. For n=500, capacity=50000: 500 × 50001 booleans = ~25MB. Acceptable. Alternatively, re-run greedy from DP result (not correct in general). Use the 2D table.

**Recommended implementation:** Use a list-of-lists `keep[n][capacity+1]` booleans, then traceback from `(n-1, best_w)`.

### Pattern 3: Candidate query with status filter

```python
# src/jobs/repository.py — add method
async def find_available_for_match(self, session: AsyncSession) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.status == "available")
        .where(Job.pay_type != "unknown")
        .where(
            or_(
                # Hourly: both pay_rate and estimated_duration_hours must be non-null
                and_(
                    Job.pay_type == "hourly",
                    Job.pay_rate.is_not(None),
                    Job.estimated_duration_hours.is_not(None),
                ),
                # Flat: only pay_rate required
                and_(
                    Job.pay_type == "flat",
                    Job.pay_rate.is_not(None),
                ),
            )
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

Log excluded jobs using structlog before passing to DP:

```python
for job in raw_jobs:
    if job.pay_type == "unknown":
        log.warning("match.job_excluded", job_id=job.id, reason="pay_type_unknown")
    elif job.pay_rate is None:
        log.warning("match.job_excluded", job_id=job.id, reason="null_pay_rate")
    elif job.pay_type == "hourly" and job.estimated_duration_hours is None:
        log.warning("match.job_excluded", job_id=job.id, reason="null_duration_hourly")
```

Note: The query already excludes these via WHERE clauses. Log the exclusions by querying without the filters first and diffing, OR by logging separately for jobs that had data issues. Simplest: log at the Python filter step rather than SQL, to keep SQL clean.

### Pattern 4: Job poster phone number join path

**CRITICAL FINDING:** `User.phone_hash` is a one-way SHA-256 hash. The raw E.164 phone number is NOT stored in any database table. The join path `Job.message_id → Message.user_id → User.phone_hash` returns only the hash, not a dialable number.

D-07 requires "job poster's phone number" in the SMS. This is a **schema gap** the planner must resolve. See Open Questions.

### Pattern 5: SMS formatting — pure Python, no library

160-char SMS segments are well-understood. No library needed.

```python
SMS_SEGMENT_SIZE = 160

def format_match_sms(result: MatchResult) -> str:
    """
    Build SMS text for matched jobs. Multi-segment OK (D-08).
    Each job line: "{desc} @ {location} | ${earnings:.0f} for {duration:.1f}h | {phone}"
    Include summary line if partial match (D-09).
    """
    lines = []
    for i, job_match in enumerate(result.jobs[:5], start=1):  # MATCH-02: 3-5 results
        line = _format_job_line(i, job_match)
        lines.append(line)

    if result.is_partial:
        total = sum(jm.earnings for jm in result.jobs)
        lines.append(f"Best available: ${total:.0f} of ${result.work_goal.target_earnings:.0f} goal")

    return "\n".join(lines)

def _format_job_line(rank: int, jm: JobMatch) -> str:
    desc = (jm.job.description or "Job")[:30]  # truncate to keep under budget
    loc = (jm.job.location or "?")[:20]
    phone = jm.poster_phone  # see Open Questions
    return f"{rank}. {desc} @ {loc} | ${jm.earnings:.0f}/{jm.job.estimated_duration_hours or 0:.1f}h | {phone}"
```

Character budget per job line at 5 jobs: keep each line under ~30 chars or accept multi-segment. D-08 explicitly allows multi-segment, so don't truncate aggressively. Track cumulative `len(text)` and log a warning if exceeding 3 segments (480 chars) so the planner can tune truncation later.

### Pattern 6: Job status Alembic migration

```python
# migrations/versions/2026-04-04_add_job_status.py
def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="available",
        ),
    )
    op.create_check_constraint(
        "ck_job_status_valid",
        "job",
        "status IN ('available', 'accepted', 'in_progress', 'completed')",
    )

def downgrade() -> None:
    op.drop_constraint("ck_job_status_valid", "job", type_="check")
    op.drop_column("job", "status")
```

**SQLModel field addition:**
```python
# src/jobs/models.py — add to Job
status: str = Field(
    default="available",
    sa_column=sa.Column(sa.String(), nullable=False, server_default="available"),
)
```

**Use a string column with CHECK constraint** rather than a PostgreSQL ENUM or SQLAlchemy `Enum` type. Reason: SQLAlchemy Enum types create a PostgreSQL ENUM type that requires `ALTER TYPE` to extend — string + CHECK is easier to migrate in future phases when new statuses may be added. Consistent with existing codebase (all `pay_type` etc. are plain `str` fields with `default=`).

### Pattern 7: MatchRepository on-conflict handling

The `UNIQUE(job_id, work_goal_id)` constraint already exists. Use `INSERT ... ON CONFLICT DO NOTHING` via SQLAlchemy:

```python
# src/matches/repository.py
from sqlalchemy.dialects.postgresql import insert as pg_insert

class MatchRepository(BaseRepository):
    async def upsert_match(self, session: AsyncSession, job_id: int, work_goal_id: int) -> None:
        stmt = (
            pg_insert(Match)
            .values(job_id=job_id, work_goal_id=work_goal_id)
            .on_conflict_do_nothing(constraint="uq_match_job_work_goal")
        )
        await session.execute(stmt)
```

**SQLite test caveat:** `sqlalchemy.dialects.postgresql.insert` does not work with SQLite (used in tests). Use `sqlalchemy.dialects.sqlite.insert` or detect dialect. Recommended: abstract behind `MatchRepository.upsert_match()` and use `try/except IntegrityError` as a cross-dialect fallback, or use conditional logic based on dialect name. See Anti-Patterns.

### Anti-Patterns to Avoid

- **Postgres-only dialect in tests:** `pg_insert(...).on_conflict_do_nothing()` will error on SQLite. Use `sqlalchemy.dialects.sqlite.insert` for tests or use `try/except sqlalchemy.exc.IntegrityError` as the universal on-conflict handler.
- **Float arithmetic for earnings comparisons:** `25.0 * 2.0 = 50.0` is fine, but `0.1 * 3` produces `0.30000000000000004`. Always compare with a small epsilon or quantize to cents for DP state.
- **2D DP table for large targets:** If `target_earnings > $10,000` and there are 500 jobs, the 2D table is 500 × 1,000,001 = 500M booleans. Cap W at `min(target_cents, max_achievable_cents)` as shown above.
- **Calling `session.add()` directly:** Always use `self._persist(session, entity)` per `BaseRepository` template method.
- **Persisting matches before sort:** Persist after sort, or persist before and re-query. Simplest: compute DP → sort → persist → return.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async test client | Custom test HTTP client | Existing `client` fixture in `tests/conftest.py` | Already wired with session override |
| DB fixtures | Manual session.add() in tests | `make_job`, `make_work_goal` factory fixtures in conftest | Already defined, just add kwargs |
| Structured logging | Custom log format | `structlog.get_logger()` + keyword args | Established pattern throughout codebase |
| OTel span | Custom tracing | `tracer.start_as_current_span()` | Established pattern in all handlers |
| SMS segment detection | Unicode/GSM parser | Manual `len(text)` check | D-08 just says "respect 160-char boundaries"; no library needed for this level |

---

## Common Pitfalls

### Pitfall 1: PostgreSQL-only dialect insert in SQLite tests
**What goes wrong:** `from sqlalchemy.dialects.postgresql import insert as pg_insert` compiles fine but raises `CompileError` when executed against SQLite (test database).
**Why it happens:** Tests use `sqlite+aiosqlite:///:memory:` but production uses PostgreSQL. Dialect-specific inserts don't cross-compile.
**How to avoid:** Use `try/except sqlalchemy.exc.IntegrityError` as the universal on-conflict pattern, or check `session.bind.dialect.name` and branch. The `IntegrityError` approach is simpler and works in both environments.
**Warning signs:** `CompileError: Can't render element of type <class 'OnConflictDoNothing'>` in test output.

### Pitfall 2: `make_job` fixture missing `status` and `estimated_duration_hours`
**What goes wrong:** Existing `make_job` fixture in `tests/conftest.py` doesn't pass `status` or `estimated_duration_hours` to `Job(...)`. After adding the `status` column, the factory needs to pass it or rely on `server_default`.
**Why it happens:** The fixture was written before `status` existed.
**How to avoid:** Update `make_job` to pass `status=kwargs.get("status", "available")` and `estimated_duration_hours=kwargs.get("estimated_duration_hours", None)`. Note `estimated_duration_hours` is already nullable in the model but the fixture doesn't pass it — tests that seed jobs for DP testing will need it.
**Warning signs:** `NOT NULL constraint failed: job.status` in tests after migration, or DP test returns no candidates because duration is None.

### Pitfall 3: `src/models.py` import list must include new models
**What goes wrong:** Alembic's `env.py` imports all models from `src/models.py`. If `MatchRepository` or updated `Job` model adds imports that aren't reflected in `src/models.py`, Alembic autogenerate won't see them.
**Why it happens:** `migrations/env.py` explicitly imports from `src.models` to populate `SQLModel.metadata`.
**How to avoid:** After adding any new SQLModel table class, verify it's imported in `src/models.py`.

### Pitfall 4: Float precision in DP capacity calculation
**What goes wrong:** `int(round(25.5 * 3.0 * 100))` = 7650 (correct), but `int(25.5 * 3.0 * 100)` = 7649 due to float representation.
**Why it happens:** IEEE 754 floating point.
**How to avoid:** Always use `int(round(value * SCALE))` not `int(value * SCALE)` when quantizing.

### Pitfall 5: `ideal_datetime` timezone-aware sort
**What goes wrong:** Comparing timezone-aware and timezone-naive datetimes raises `TypeError: can't compare offset-naive and offset-aware datetimes`.
**Why it happens:** Some `ideal_datetime` values may be stored without timezone (existing records before the UTC fix in Phase 2.11).
**How to avoid:** In the sort key, normalize: `job.ideal_datetime.replace(tzinfo=UTC) if job.ideal_datetime.tzinfo is None else job.ideal_datetime`. Use `datetime.max.replace(tzinfo=UTC)` as the sentinel for NULL `ideal_datetime` (D-12: NULL sorts last).

---

## Open Questions

### 1. Job poster phone number is not stored — D-07 is currently unimplementable
**What we know:** `User.phone_hash` is a one-way SHA-256 hash of the E.164 number. The raw phone number is never persisted. The join path `Job → Message → User` returns only `phone_hash`. The `PipelineContext` has `from_number` at pipeline runtime but this is not saved to any table.

**What's unclear:** D-07 says "job poster's phone number" must appear in the SMS output. This cannot be retrieved from the DB without a schema change.

**Recommendation (planner must decide):** Add a `phone_e164` column to the `User` table as part of this phase, populated in `UserRepository.get_or_create()`. This requires one Alembic migration and one repository change. The column should be nullable initially (existing rows have no value) and populated going forward. If this is not done, Phase 3 must use `phone_hash` in the SMS output, which is not human-readable. The planner should treat this as a required task for D-07 compliance, not a deferral.

### 2. MATCH-02 says "3–5 results" but DP may select more or fewer
**What we know:** MATCH-02 says send "3–5 matching jobs." The DP selects the subset that meets the earnings goal — this could be 1 job (one high-value flat job) or 10 jobs (many small hourly jobs).

**Recommendation:** Format and send all jobs in the DP-selected set, up to 5 in the SMS reply. If the DP selects more than 5, sort by D-11/D-12 and show top 5. If the DP selects fewer than 3, show what's available and rely on D-09 summary line if partial. The "3–5" in MATCH-02 is a UI guideline, not a hard DP constraint.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_match_service.py -x` |
| Full suite command | `pytest tests/ --cov=src` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MATCH-01 | DP returns only jobs meeting `rate × duration >= target`, sorted by soonest then shortest | unit | `pytest tests/test_match_service.py::test_dp_meets_goal -x` | Wave 0 |
| MATCH-01 | DP returns best-effort subset when full candidate set is insufficient | unit | `pytest tests/test_match_service.py::test_dp_partial_match -x` | Wave 0 |
| MATCH-01 | NULL `pay_rate` and NULL `estimated_duration_hours` (hourly) are excluded with structlog warning | unit | `pytest tests/test_match_service.py::test_null_exclusion -x` | Wave 0 |
| MATCH-01 | `pay_type='unknown'` jobs are excluded | unit | `pytest tests/test_match_service.py::test_unknown_pay_type_excluded -x` | Wave 0 |
| MATCH-01 | Jobs with `status != 'available'` are not returned by query | unit | `pytest tests/test_match_service.py::test_status_filter -x` | Wave 0 |
| MATCH-02 | SMS formatter produces output fitting within 3 × 160 chars for 5 jobs | unit | `pytest tests/test_match_service.py::test_sms_format -x` | Wave 0 |
| MATCH-02 | `is_partial=True` result includes "Best available: $X of $Y goal" summary line | unit | `pytest tests/test_match_service.py::test_partial_summary_line -x` | Wave 0 |
| MATCH-03 | Empty candidate set returns `MatchResult` with `jobs=[]` and no crash | unit | `pytest tests/test_match_service.py::test_empty_match -x` | Wave 0 |
| MATCH-01 | Match records persisted with `UNIQUE` conflict ignored | unit | `pytest tests/test_match_service.py::test_match_persistence_idempotent -x` | Wave 0 |

### Wave 0 Gaps
- [ ] `tests/test_match_service.py` — all MATCH-01/02/03 test cases above
- [ ] Update `tests/conftest.py` `make_job` factory: add `status` kwarg, ensure `estimated_duration_hours` and `pay_rate` are passable
- [ ] No framework install needed — pytest + pytest-asyncio already installed

---

## Environment Availability

Step 2.6: SKIPPED — this phase adds Python code and one Alembic migration. All required tools (Python, pytest, Alembic, SQLAlchemy) are already installed in the project. No new external dependencies.

---

## Sources

### Primary (HIGH confidence)
- `/Users/ahcarpenter/workspace/vici/src/matches/models.py` — Match model, UNIQUE constraint
- `/Users/ahcarpenter/workspace/vici/src/jobs/models.py` — Job model fields, CHECK constraints
- `/Users/ahcarpenter/workspace/vici/src/jobs/repository.py` — JobRepository pattern
- `/Users/ahcarpenter/workspace/vici/src/work_goals/models.py` — WorkGoal.target_earnings type
- `/Users/ahcarpenter/workspace/vici/src/repository.py` — BaseRepository._persist() signature
- `/Users/ahcarpenter/workspace/vici/src/pipeline/handlers/worker_goal.py` — structlog + OTel span pattern
- `/Users/ahcarpenter/workspace/vici/src/pipeline/handlers/job_posting.py` — structlog + OTel span pattern
- `/Users/ahcarpenter/workspace/vici/src/users/models.py` — Confirmed User stores phone_hash only (not raw E.164)
- `/Users/ahcarpenter/workspace/vici/src/sms/models.py` — Message model, join path from Job to User
- `/Users/ahcarpenter/workspace/vici/tests/conftest.py` — All fixture patterns, make_job, make_work_goal
- `/Users/ahcarpenter/workspace/vici/migrations/versions/2026-04-03_normalize_3nf.py` — Alembic migration pattern
- `/Users/ahcarpenter/workspace/vici/alembic.ini` — Migration file naming: `YYYY-MM-DD_slug.py`
- `/Users/ahcarpenter/workspace/vici/pyproject.toml` — pytest asyncio_mode = "auto"

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — reading actual installed dependencies
- Architecture patterns: HIGH — derived from reading existing handler/repository code
- DP algorithm: HIGH — standard CS algorithm, quantization approach well understood
- Phone number blocker: HIGH — confirmed by reading User model and Message model
- Pitfalls: HIGH — derived from reading test infrastructure and dialect differences
- SMS formatting: HIGH — straightforward string manipulation, no library needed

**Research date:** 2026-04-04
**Valid until:** Phase 4 start (no time decay — findings are codebase facts, not ecosystem research)
