# Phase 3: Earnings Math Matching - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a `MatchService` that accepts a persisted `WorkGoal` record and returns a ranked list of jobs satisfying earnings math, sorted by soonest available date then shortest duration. Includes an SMS formatter for the ranked result and empty-match fallback. Match records are persisted to the `match` table.

This phase does NOT wire the service into the pipeline — that is Phase 4. Phase 3 ends when `MatchService` is tested and ready to be called from the Temporal `ProcessMessageWorkflow`.

Requirements in scope: MATCH-01, MATCH-02, MATCH-03.

</domain>

<decisions>
## Implementation Decisions

### Earnings math by pay_type
- **D-01:** `pay_type='hourly'` → `pay_rate × estimated_duration_hours >= target_earnings`
- **D-02:** `pay_type='flat'` → `pay_rate >= target_earnings` (duration irrelevant for flat-rate jobs)
- **D-03:** `pay_type='unknown'` → exclude from matches entirely (math is unverifiable)

### NULL field policy
- **D-04:** Jobs with NULL `pay_rate` or NULL `estimated_duration_hours` are excluded from results
- **D-05:** Exclusion is logged as a structlog warning with `job_id` so extraction quality issues are visible
- Note: For flat-rate jobs (`pay_type='flat'`), NULL `estimated_duration_hours` is acceptable — only `pay_rate` is required

### SMS format per matched job
- **D-06:** Each job entry includes: description, location, job poster's phone number, total earnings (computed: `pay_rate × duration` for hourly, `pay_rate` for flat), and duration
- **D-07:** 3–5 jobs per reply; format must respect 160-character SMS segment boundaries
- **D-08:** Job poster's phone number is included as-is in Phase 3 (privacy proxy is deferred — see Deferred Ideas)

### Match persistence
- **D-09:** `MatchService` persists each matched `(job_id, work_goal_id)` pair to the `match` table after computing results
- **D-10:** Duplicate match rows are handled by the existing `UNIQUE(job_id, work_goal_id)` constraint — on conflict, skip (upsert or ignore)

### Sorting
- **D-11:** Results sorted by soonest `ideal_datetime` first, then shortest `estimated_duration_hours` — per ROADMAP success criteria
- **D-12:** Jobs with NULL `ideal_datetime` sort last (can't determine soonest available)

### Empty match handling
- **D-13:** When no jobs match the worker goal, `MatchService` returns a designated empty result that the caller can format into a graceful "no matches" SMS reply (MATCH-03)

</decisions>

<specifics>
## Specific Ideas

- SMS reply fields explicitly requested: description, location, job poster phone number, total earnings, duration
- Privacy concern noted: poster phone number should eventually be proxied — captured as a deferred todo

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external spec documents for this phase — requirements are fully captured in REQUIREMENTS.md and decisions above.

### Key files to read before planning
- `.planning/REQUIREMENTS.md` §MATCH — MATCH-01, MATCH-02, MATCH-03 acceptance criteria
- `.planning/ROADMAP.md` §Phase 3 — Success criteria and plan 03-01 scope
- `src/matches/models.py` — Existing `Match` model (job_id, work_goal_id, UNIQUE constraint)
- `src/jobs/models.py` — `Job` schema: pay_rate (nullable), pay_type, estimated_duration_hours (nullable), ideal_datetime (nullable)
- `src/jobs/repository.py` — `JobRepository` base to extend with earnings math query method
- `src/work_goals/models.py` — `WorkGoal` schema: target_earnings, target_timeframe
- `src/pipeline/handlers/worker_goal.py` — Integration point where Phase 4 will call MatchService

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/repository.py` — `BaseRepository` with `_persist()` helper; `MatchRepository` should extend this
- `src/jobs/repository.py` — `JobRepository` to extend with `find_matches_for_goal(work_goal)` method
- `src/pipeline/handlers/worker_goal.py` — `WorkerGoalHandler._do_handle()` is the future call site for MatchService (Phase 4 wires it)

### Established Patterns
- Flush-only repositories; caller controls transaction boundary (single commit per pipeline branch)
- structlog for all logging with contextual fields (e.g., `job_id=`, `work_goal_id=`)
- OTel manual spans for all meaningful operations: wrap MatchService.match() in a `pipeline.match_jobs` span
- `BaseRepository._persist()` for all DB writes — do not call `session.add()` directly

### Integration Points
- `WorkerGoalHandler._do_handle()` in `src/pipeline/handlers/worker_goal.py` — Phase 4 will inject and call MatchService here after committing the work_goal
- `src/temporal/activities.py` — `process_message_activity` runs the orchestrator; MatchService will be reachable through the handler chain

### Data Shape
- `Job.pay_type` values: `'hourly'` | `'flat'` | `'unknown'`
- `Job.pay_rate`: `Optional[float]`, CHECK constraint `pay_rate > 0` when not null
- `Job.estimated_duration_hours`: `Optional[float]`, CHECK constraint `> 0` when not null
- `Match` table has `UNIQUE(job_id, work_goal_id)` — handle on-conflict gracefully

</code_context>

<deferred>
## Deferred Ideas

- **Phone number privacy proxy** — Job poster's phone number appears in SMS replies in Phase 3 as-is. A proxy/masking layer (e.g., Twilio Proxy or a short alias) should be added before production to protect poster privacy. Add as a backlog todo.
- **Follow-up clarification flow** — When a job has `pay_type='unknown'` or missing fields, send a follow-up SMS to the job poster requesting the missing info. This is a multi-turn conversation concern; deferred to a future phase.

</deferred>

---

*Phase: 03-earnings-math-matching*
*Context gathered: 2026-04-04*
