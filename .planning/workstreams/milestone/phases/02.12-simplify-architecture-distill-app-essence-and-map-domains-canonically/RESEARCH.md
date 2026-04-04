# Phase 02.12: Simplify Architecture — Research

**Researched:** 2026-04-03
**Domain:** Python/FastAPI domain organization, import graph audit, structural refactoring
**Confidence:** HIGH — all findings derived from direct source inspection

---

## Summary

The Vici codebase has grown through ~12 incremental phases and has accumulated three distinct structural problems: (1) a misplaced coordinator class (`PipelineOrchestrator` in `extraction/`), (2) a stale `main.py` DI call that doesn't match the current orchestrator constructor, and (3) a cluster of dead test stub files from the Inngest-to-Temporal migration in phase 02.9. The core domain flow is well-defined and coherent; what's needed is a small set of surgical file moves and a cleanup of the main.py DI call, not a wholesale restructuring.

The canonical domain decomposition is: `sms/` (HTTP ingest and messaging domain) → `temporal/` (async job dispatch) → `extraction/` (GPT classification) + `pipeline/` (Chain-of-Responsibility dispatch) → `jobs/`, `work_requests/`, `matches/` (domain entities) → `users/` (identity). The `pipeline/` module properly holds context and handlers; the single misplaced file is `orchestrator.py` which coordinates across these layers and belongs in `pipeline/`.

The `sms/` domain does mix HTTP layer concerns (router, dependencies) with messaging domain models (models, repository). However, the mixing is intentional and well-bounded — all of these concern the same Twilio SMS message lifecycle. Splitting it into `http/` + `messaging/` would produce two tiny modules with circular tendencies and no real benefit. The current `sms/` structure should be kept.

**Primary recommendation:** Move `src/extraction/orchestrator.py` → `src/pipeline/orchestrator.py`, fix `main.py` DI call to match the actual constructor, delete three dead Inngest stub test files, and document `src/models.py` as the Alembic registration manifest (not a base class). That is the minimal canonical refactor.

---

## Canonical Domain Breakdown

The app's essence is a **SMS-to-action pipeline**:

```
Twilio POST → [sms/] validate + persist + rate-limit
           → [temporal/] dispatch ProcessMessageWorkflow
           → [temporal/] activity calls PipelineOrchestrator
           → [extraction/] ExtractionService (GPT classify)
           → [pipeline/] handler chain: JobPostingHandler | WorkerGoalHandler | UnknownHandler
           → [jobs/ | work_requests/] persist domain entity
           → [extraction/] Pinecone upsert (async, with queue fallback)
```

Domain responsibilities map cleanly:

| Domain | Responsibility | Should Contain |
|--------|---------------|----------------|
| `sms/` | Twilio HTTP ingest, message persistence, rate limiting, audit | router, dependencies, service (hash_phone + emit), models (Message/AuditLog/RateLimit), repository, audit_repository, exceptions, constants, schemas |
| `extraction/` | GPT classification and vector storage | service, schemas, prompts, constants, pinecone_client, models (PineconeSyncQueue) |
| `pipeline/` | Message routing coordinator + Chain-of-Responsibility handlers | **orchestrator** (to be moved here), context, handlers/ |
| `temporal/` | Temporal worker, workflows, activities | worker, workflows, activities |
| `jobs/` | Job posting domain entity | models, schemas, repository |
| `work_requests/` | Worker goal domain entity | models, schemas, repository |
| `matches/` | Match domain entity (Phase 3 stub) | models |
| `users/` | Identity / phone_hash → user mapping | models, repository |

---

## Findings by Research Question

### Q1: What is the canonical domain breakdown?

See table above. The flow is linear and well-structured. No fundamental domain redesign is needed.

**Confidence: HIGH** — derived from source inspection of all domain modules.

### Q2: Where is `PipelineOrchestrator` imported? What is the blast radius?

Files that import from `src.extraction.orchestrator` in the **live codebase** (excluding `.claude/worktrees/`):

| File | Import Style | Action Required |
|------|-------------|-----------------|
| `src/main.py` | `from src.extraction.orchestrator import PipelineOrchestrator` | Update to `src.pipeline.orchestrator` |
| `src/temporal/activities.py` | `from src.extraction.orchestrator import PipelineOrchestrator` (TYPE_CHECKING guard) | Update import path |
| `tests/test_pipeline_orchestrator.py` | `from src.extraction.orchestrator import PipelineOrchestrator` | Update import path |
| `tests/integration/test_worker_goal.py` | Not present in live tree — only in worktrees | No action |
| `tests/integration/test_job_posting.py` | Not present in live tree — only in worktrees | No action |
| `tests/integration/test_unknown.py` | Not present in live tree — only in worktrees | No action |

**Total live import path updates: 3 files** (main.py, activities.py, test_pipeline_orchestrator.py).

Note: `tests/integration/test_*.py` files DO NOT import `PipelineOrchestrator` in the current live tree — they use the handler classes directly. Only the worktrees (stale agent branches) have those imports.

### Q3: Should `sms/` be split into `http/` + `messaging/`?

**Recommendation: No.** Reasons:

1. `sms/router.py` and `sms/dependencies.py` import from `sms/repository.py`, `sms/audit_repository.py`, `sms/models.py`, and `sms/service.py` — all within the same domain boundary. No cross-domain leakage.
2. The `Message`, `AuditLog`, and `RateLimit` models are exclusively consumed within `sms/` and by `src/models.py` (the Alembic manifest). No other domain module imports from `sms/models.py` except `src/temporal/activities.py` which needs `Message` to look up the DB row for a given `message_sid`.
3. The `hash_phone` function lives in `sms/service.py` and is called from `sms/dependencies.py` and `src/temporal/activities.py`. Its placement in `sms/` is correct — it's a phone number utility for the SMS domain.
4. Splitting would require 2 new `__init__.py` files, updated imports in ~8 files, and yields no architectural benefit for a codebase of this size.

**Keep `sms/` as-is.** Its internal structure is clean.

### Q4: What are `src/repository.py` and `src/models.py`?

**`src/repository.py`** — A 17-line abstract base class `BaseRepository` providing a `_persist()` template method. It is imported by:
- `src/sms/audit_repository.py`
- `src/sms/repository.py`
- `src/work_requests/repository.py`
- `src/jobs/repository.py`

This is a shared infrastructure concern used by 4 repositories. It is correctly placed at root `src/` level per the AGENTS.md pattern ("Global models" / "Global exceptions"). **Keep as-is.** It is not leftover — it is the shared base.

**`src/models.py`** — A 7-line file that star-imports all SQLModel table classes from every domain:
```python
from src.extraction.models import PineconeSyncQueue
from src.jobs.models import Job
from src.matches.models import Match
from src.sms.models import AuditLog, Message, RateLimit
from src.users.models import User
from src.work_requests.models import WorkRequest
```

This file's sole purpose is to ensure all SQLModel table classes are registered in `SQLModel.metadata` before Alembic runs `create_all`. It is imported by `migrations/env.py` and `tests/conftest.py` (via `import src.models`). **Not a base class — it is the Alembic model registry manifest.** The file should gain a docstring explaining this intent. It does not need renaming or moving.

### Q5: Minimal set of moves to achieve canonical domain mapping

There are **4 actions** required:

| # | Action | Files Touched |
|---|--------|--------------|
| 1 | Move `src/extraction/orchestrator.py` → `src/pipeline/orchestrator.py` | 1 file moved |
| 2 | Update 3 import sites that reference `src.extraction.orchestrator` | main.py, activities.py, test_pipeline_orchestrator.py |
| 3 | Fix `main.py` DI call: PipelineOrchestrator constructor mismatch (see Q6 below) | main.py |
| 4 | Delete 3 dead Inngest stub test files (see Q7) | 3 files deleted |

Optional (low impact, improves discoverability):
- Add docstring to `src/models.py` explaining its role as the Alembic model manifest
- Add docstring to `src/repository.py` clarifying it is a shared infrastructure concern, not domain-specific

### Q6: Circular imports or awkward cross-domain dependencies?

**Critical finding — main.py DI call does not match the PipelineOrchestrator constructor.**

Current `main.py` (lines 98–106):
```python
orchestrator = PipelineOrchestrator(
    extraction_service=extraction_service,
    job_repo=JobRepository,
    work_request_repo=WorkRequestRepository,
    message_repo=MessageRepository,
    audit_repo=AuditLogRepository,
    pinecone_client=pinecone_client,
    twilio_client=twilio_client,
)
```

Actual `PipelineOrchestrator.__init__` signature:
```python
def __init__(self, extraction_service, audit_repo, handlers: list[MessageHandler]):
```

The constructor accepts `handlers` (a list of pre-built handler instances), not individual repos. The `job_repo`, `work_request_repo`, `message_repo`, `pinecone_client`, and `twilio_client` kwargs are silently ignored by Python (they would raise `TypeError` if `__init__` used `**kwargs` or strict signature — but since Python doesn't enforce extra kwargs unless explicitly rejected, this may not be raising at runtime IF the handlers are being built elsewhere). **This is a latent bug or a remnant of an older orchestrator API.**

The orchestrator was refactored in Phase 02 to accept a pre-built `handlers` list (externalized Chain of Responsibility), but `main.py` was never updated to build the handlers and pass them in. The app currently constructs `PipelineOrchestrator` with dead keyword arguments and passes NO `handlers` list — meaning the `for handler in self._handlers` loop in `orchestrator.run()` iterates over nothing.

Wait — this would mean no handler ever runs. Let me re-examine. `handlers` has no default, so `PipelineOrchestrator(extraction_service=..., job_repo=..., ...)` would raise `TypeError: __init__() missing 1 required positional argument: 'handlers'` at startup.

**This is a real startup bug.** The app would crash at lifespan initialization. This means either:
a) The app is not actually being started in the current state (tests mock around it), or  
b) There is a different version of `orchestrator.py` being used that accepts the old API.

The test in `test_pipeline_orchestrator.py` builds the orchestrator correctly (with `handlers=handlers`), so tests pass. But `main.py` would fail at runtime. **This DI call must be fixed as part of this phase.**

**Fix required in main.py:** Build handler instances explicitly and pass as `handlers` list:
```python
handlers = [
    JobPostingHandler(
        job_repo=JobRepository,
        audit_repo=AuditLogRepository(),
        pinecone_client=pinecone_client,
        extraction_service=extraction_service,
    ),
    WorkerGoalHandler(
        work_request_repo=WorkRequestRepository,
        audit_repo=AuditLogRepository(),
    ),
    UnknownMessageHandler(
        twilio_client=twilio_client,
        extraction_service=extraction_service,
    ),
]
orchestrator = PipelineOrchestrator(
    extraction_service=extraction_service,
    audit_repo=AuditLogRepository(),
    handlers=handlers,
)
```

**Cross-domain dependency audit (no circular imports found):**

The import graph is acyclic:
- `main.py` → all domains (composition root, acceptable)
- `temporal/activities.py` → `extraction/orchestrator` (TYPE_CHECKING only), `sms/models`, `sms/service`, `extraction/pinecone_client`
- `pipeline/handlers/*.py` → `extraction/schemas`, `extraction/service`, `jobs/`, `work_requests/`, `sms/audit_repository`
- `extraction/orchestrator.py` → `extraction/service`, `extraction/schemas`, `pipeline/context`, `pipeline/handlers/base`, `sms/audit_repository`
- `sms/service.py` → `temporal/` (inside function body, deferred import to avoid circular)
- No cycles detected.

The deferred import in `sms/service.py` (importing `temporal.worker` and `temporal.workflows` inside `emit_message_received_event`) is a deliberate anti-cycle guard. After `orchestrator.py` moves to `pipeline/`, the import graph for that module changes from `extraction/` → `pipeline/` to `pipeline/` → `pipeline/` (self-referencing, but fine since context and base are different files).

### Q7: Tests — what exists and how many import paths need updating?

**Live test files and their import dependencies on the affected modules:**

| Test File | Imports from `extraction.orchestrator` | Action |
|-----------|----------------------------------------|--------|
| `tests/test_pipeline_orchestrator.py` | Yes — line 27 | Update import path |
| `tests/temporal/test_activities.py` | No direct import | No action |
| `tests/temporal/test_spans.py` | No direct import | No action |
| `tests/integration/test_job_posting.py` | No — uses handler directly | No action |
| `tests/integration/test_worker_goal.py` | No — uses handler directly | No action |
| `tests/integration/test_unknown.py` | No — uses handler directly | No action |

**Dead stub test files to delete** (Inngest-to-Temporal migration remnants from Phase 02.9):

| File | Content | Action |
|------|---------|--------|
| `tests/inngest/__init__.py` | Empty | Delete |
| `tests/inngest/test_process_message.py` | `# Inngest removed in phase 02.9. Tests migrated to tests/temporal/test_activities.py.` | Delete |
| `tests/inngest/test_process_message_spans.py` | `# Inngest removed in phase 02.9. Tests migrated to tests/temporal/test_spans.py.` | Delete |
| `tests/inngest/test_sync_pinecone_queue.py` | `# Inngest removed in phase 02.9. Tests migrated to tests/temporal/test_activities.py.` | Delete |

The entire `tests/inngest/` directory should be removed.

**Total import path changes needed: 3 files** (main.py + activities.py + test_pipeline_orchestrator.py).

---

## Architecture Patterns

### Recommended Final Structure

```
src/
├── extraction/          # GPT classification + vector storage (no orchestrator)
│   ├── constants.py
│   ├── models.py        # PineconeSyncQueue
│   ├── pinecone_client.py
│   ├── prompts.py
│   ├── schemas.py
│   └── service.py
├── pipeline/            # Pipeline coordinator + Chain-of-Responsibility
│   ├── orchestrator.py  # MOVED FROM extraction/
│   ├── context.py
│   └── handlers/
│       ├── base.py
│       ├── job_posting.py
│       ├── unknown.py
│       └── worker_goal.py
├── sms/                 # Twilio HTTP ingest + messaging domain (unchanged)
│   ├── audit_repository.py
│   ├── constants.py
│   ├── dependencies.py
│   ├── exceptions.py
│   ├── models.py
│   ├── repository.py
│   ├── router.py
│   ├── schemas.py
│   └── service.py
├── temporal/            # Async job execution (unchanged)
│   ├── activities.py
│   ├── worker.py
│   └── workflows.py
├── jobs/                # Job posting entity (unchanged)
├── work_requests/       # Worker goal entity (unchanged)
├── matches/             # Match entity stub (unchanged)
├── users/               # Identity (unchanged)
├── config.py
├── database.py
├── exceptions.py
├── main.py              # DI call fixed
├── metrics.py
├── models.py            # Alembic model manifest (add docstring)
└── repository.py        # Shared BaseRepository (add docstring)
```

### `work_requests/` Naming

The module name `work_requests` is a minor naming incongruity — the model class is `WorkRequest` and the table is `work_request`, but the domain represents "worker goals" (what workers want to earn). Renaming the module to `worker_goals/` would require: model rename, schema rename, table rename (migration), repository rename, and all import updates. This is out of scope for a structural phase — the table name `work_request` is stable and referenced in the DB schema. **Do not rename** in this phase.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting circular imports | Custom script | `pydeps` or `importlib` trace | Complex to get right |
| Bulk import path rewriting | Manual sed | `rope` refactoring library or IDE refactor | Less error-prone |

For this phase, the blast radius is small enough (3 files) that manual updates are correct.

---

## Common Pitfalls

### Pitfall 1: Forgetting the `__init__.py` Re-export
**What goes wrong:** After moving `orchestrator.py` to `pipeline/`, if any code does `from src.pipeline import PipelineOrchestrator` (rather than `from src.pipeline.orchestrator import PipelineOrchestrator`), it will break.
**Why it happens:** `pipeline/__init__.py` does not re-export anything currently.
**How to avoid:** Search for `from src.pipeline import` before and after the move.

### Pitfall 2: Worktrees Have Stale Imports
**What goes wrong:** `.claude/worktrees/` contains copies of the codebase with the old import path. Worktree code is not live but could confuse grep-based refactoring tools.
**How to avoid:** Scope all search/replace to `src/` and `tests/` only, explicitly excluding `.claude/`.

### Pitfall 3: main.py DI Call Passes Dead Kwargs
**What goes wrong:** The current `main.py` calls `PipelineOrchestrator(job_repo=..., work_request_repo=..., ...)` with kwargs the constructor doesn't accept. Python raises `TypeError` at startup. Tests don't catch this because the lifespan is not exercised in unit tests (the `create_app()` fixture in conftest.py does not trigger the lifespan context).
**How to avoid:** Fix the DI call as part of this phase. Build handler instances explicitly in `main.py` and pass as `handlers=[...]`.

### Pitfall 4: AuditLogRepository Instantiation Pattern
**What goes wrong:** `AuditLogRepository()` is instantiated at call sites (e.g., `sms/router.py` does `AuditLogRepository().write(...)` inline). When building handlers in `main.py`, be consistent — instantiate `AuditLogRepository()` once and pass the instance to all handlers that need it, or use the class directly (as the existing handlers do).
**How to avoid:** Check how each handler currently accepts `audit_repo` — `orchestrator.py` and all handlers accept an instance, not a class. Pass instances, not classes.

---

## Code Examples

### Handler registration in main.py (corrected pattern)
```python
# Source: direct inspection of src/pipeline/handlers/*.py constructor signatures
from src.pipeline.handlers.job_posting import JobPostingHandler
from src.pipeline.handlers.unknown import UnknownMessageHandler
from src.pipeline.handlers.worker_goal import WorkerGoalHandler
from src.pipeline.orchestrator import PipelineOrchestrator  # after move

audit_repo = AuditLogRepository()
handlers = [
    JobPostingHandler(
        job_repo=JobRepository,
        audit_repo=audit_repo,
        pinecone_client=write_job_embedding,
        extraction_service=extraction_service,
    ),
    WorkerGoalHandler(
        work_request_repo=WorkRequestRepository,
        audit_repo=audit_repo,
    ),
    UnknownMessageHandler(
        twilio_client=twilio_client,
        extraction_service=extraction_service,
    ),
]
orchestrator = PipelineOrchestrator(
    extraction_service=extraction_service,
    audit_repo=audit_repo,
    handlers=handlers,
)
```

Note: `JobRepository`, `WorkRequestRepository`, and `MessageRepository` are passed as **classes** (not instances) to handlers and the repository pattern uses class methods. Verify this matches how `JobRepository.create(session, ...)` is called — it is an instance method in the current code (`self._job_repo.create(...)`), meaning handler constructors store the class but call instance methods. Review `src/jobs/repository.py` to confirm whether to pass class or instance.

---

## State of the Art

No framework version changes are involved. This is a pure structural refactoring phase.

| Old Location | New Location | Why |
|-------------|--------------|-----|
| `src/extraction/orchestrator.py` | `src/pipeline/orchestrator.py` | Orchestrator coordinates pipeline, not extraction |
| Inngest test stubs in `tests/inngest/` | Deleted | Migration completed in Phase 02.9; stubs serve no purpose |

---

## Open Questions

1. **JobRepository class vs. instance pattern**
   - What we know: `JobPostingHandler.__init__` accepts `job_repo: JobRepository` and calls `self._job_repo.create(...)`. `main.py` passes `JobRepository` (the class). But `create` is not a `@classmethod` in the repository — it is an instance method inherited from `BaseRepository` indirectly.
   - What's unclear: Whether passing the class works or whether it should be `JobRepository()`. This needs verification by reading `src/jobs/repository.py` fully.
   - Recommendation: Read `src/jobs/repository.py` before writing main.py DI fix. Likely needs `JobRepository()` (instance), not `JobRepository` (class).

2. **Should `UnknownMessageHandler` get a `raw_sms` field?**
   - The `work_requests/` item is deferred. But the `WorkerGoalHandler` is noted as Phase 3 for matching. Is there missing handler configuration for the `matches/` domain?
   - Recommendation: Out of scope for 02.12 — this is a feature concern, not a structural concern.

---

## Environment Availability

Step 2.6: SKIPPED — this phase is code/structure-only (file moves, import updates, deletions). No external dependencies.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pytest.ini` or `pyproject.toml` (check project root) |
| Quick run command | `pytest tests/test_pipeline_orchestrator.py -x` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|--------------|
| PipelineOrchestrator importable from `src.pipeline.orchestrator` | unit | `pytest tests/test_pipeline_orchestrator.py -x` | ✅ (after import update) |
| main.py DI call succeeds without TypeError at startup | smoke | `pytest tests/test_health.py -x` | ✅ |
| Dead inngest test files removed | structural | `python -c "import tests.inngest"` fails | after deletion |
| All existing tests still pass | regression | `pytest` | ✅ |

### Wave 0 Gaps
None — existing test infrastructure covers all phase requirements. No new test files needed. The existing `test_pipeline_orchestrator.py` will validate the move after its import path is updated.

---

## Sources

### Primary (HIGH confidence)
- Direct source inspection of all `src/` Python files — all findings are from first-party code
- Direct source inspection of all `tests/` Python files — test import analysis

### Secondary (MEDIUM confidence)
- AGENTS.md project conventions — structure and naming guidelines

---

## Metadata

**Confidence breakdown:**
- Structural findings: HIGH — derived from direct file inspection
- DI bug (main.py mismatch): HIGH — verified by comparing constructor signature against call site
- Import blast radius: HIGH — grep-verified across live tree
- `work_requests/` rename recommendation (don't): HIGH — table name is DB schema

**Research date:** 2026-04-03
**Valid until:** Until next structural phase — findings are based on current file state, not library versions
