# Codebase Structure

**Analysis Date:** 2026-04-22

## Directory Layout

```
vici/
├── src/                        # Application source code
│   ├── main.py                 # FastAPI app factory, lifespan, DI graph, OTel setup
│   ├── config.py               # Pydantic BaseSettings, sub-model remapping
│   ├── database.py             # Async engine, sessionmaker, get_session generator
│   ├── repository.py           # BaseRepository ABC (flush-only _persist)
│   ├── models.py               # Global SQLModel import registry (for Alembic)
│   ├── metrics.py              # Prometheus metric singletons
│   ├── exceptions.py           # Global FastAPI exception handlers
│   ├── money.py                # dollars_to_cents / cents_to_dollars converters
│   ├── sms/                    # Twilio webhook ingress domain
│   │   ├── router.py           # POST /webhook/sms endpoint
│   │   ├── dependencies.py     # 4-gate dependency chain (validate, idempotency, user, rate)
│   │   ├── service.py          # hash_phone, emit_message_received_event
│   │   ├── repository.py       # MessageRepository (idempotency, rate limit, create)
│   │   ├── audit_repository.py # AuditLogRepository (write audit_log rows)
│   │   ├── models.py           # Message, RateLimit, AuditLog SQLModel tables
│   │   ├── schemas.py          # (currently empty — no Pydantic I/O schemas needed)
│   │   ├── constants.py        # RATE_LIMIT_WINDOW_SECONDS, MAX_MESSAGES_PER_WINDOW
│   │   └── exceptions.py       # EarlyReturn, DuplicateMessageSid, RateLimitExceeded, TwilioSignatureInvalid
│   ├── extraction/             # GPT classification and Pinecone embedding domain
│   │   ├── service.py          # ExtractionService (GPT classify with tenacity retry)
│   │   ├── utils.py            # write_job_embedding (OpenAI embed + Pinecone upsert)
│   │   ├── schemas.py          # ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage
│   │   ├── prompts.py          # SYSTEM_PROMPT (few-shot GPT prompt)
│   │   ├── models.py           # PineconeSyncQueue SQLModel table
│   │   └── constants.py        # GPT_MODEL, EMBEDDING_MODEL, retry/timeout constants
│   ├── pipeline/               # Chain of Responsibility message dispatch
│   │   ├── orchestrator.py     # PipelineOrchestrator (classify + dispatch)
│   │   ├── context.py          # PipelineContext dataclass (session bag)
│   │   ├── constants.py        # OTel attribute key constants
│   │   └── handlers/
│   │       ├── base.py         # MessageHandler ABC (can_handle, handle)
│   │       ├── job_posting.py  # JobPostingHandler
│   │       ├── worker_goal.py  # WorkerGoalHandler
│   │       └── unknown.py      # UnknownMessageHandler (catch-all, sends Twilio reply)
│   ├── temporal/               # Temporal workflow/activity/worker definitions
│   │   ├── workflows.py        # ProcessMessageWorkflow, SyncPineconeQueueWorkflow
│   │   ├── activities.py       # process_message_activity, sync_pinecone_queue_activity, failure activity
│   │   ├── worker.py           # get_temporal_client, run_worker, start_cron_if_needed
│   │   └── constants.py        # Task queue names, retry policy values, timeouts
│   ├── jobs/                   # Job posting domain
│   │   ├── models.py           # Job SQLModel table
│   │   ├── repository.py       # JobRepository (create, find_candidates_for_goal)
│   │   └── schemas.py          # JobCreate Pydantic model
│   ├── work_goals/             # Worker earnings goal domain
│   │   ├── models.py           # WorkGoal SQLModel table
│   │   ├── repository.py       # WorkGoalRepository (create)
│   │   └── schemas.py          # WorkGoalCreate Pydantic model
│   ├── matches/                # Job-to-work-goal matching domain (not yet wired to pipeline)
│   │   ├── models.py           # Match SQLModel table
│   │   ├── repository.py       # MatchRepository (persist_matches)
│   │   ├── service.py          # MatchService (DP knapsack selection)
│   │   ├── schemas.py          # JobCandidate, MatchResult dataclasses
│   │   └── formatter.py        # format_match_sms (SMS reply formatting)
│   └── users/                  # User identity domain
│       ├── models.py           # User SQLModel table
│       └── repository.py       # UserRepository (get_or_create by phone_hash)
├── tests/                      # Test suite (mirrors src/ domain layout)
│   ├── conftest.py             # Session-scoped fixtures: SQLite engine, async_session, client, factories
│   ├── extraction/             # Extraction domain tests
│   ├── integration/            # End-to-end route tests (per message type)
│   ├── matches/                # MatchService and formatter tests
│   ├── sms/                    # Webhook route tests
│   ├── temporal/               # Activity and worker tests
│   ├── infra/                  # Static analysis tests for infra YAML/Pulumi
│   ├── test_pipeline_orchestrator.py
│   ├── test_pipeline_hardening.py
│   ├── test_repositories.py
│   ├── test_config.py
│   ├── test_health.py
│   ├── test_logging.py
│   ├── test_otel_config.py
│   └── test_3nf_normalization.py
├── migrations/                 # Alembic migrations
│   ├── env.py                  # Alembic environment (async engine setup)
│   ├── script.py.mako          # Migration template
│   └── versions/               # Timestamped migration files (YYYY-MM-DD_slug.py)
├── infra/                      # Pulumi IaC (Python, GKE/GCP)
│   ├── __main__.py             # Pulumi entrypoint
│   ├── config.py               # Pulumi stack config helpers
│   └── components/             # One file per infrastructure component
│       ├── app.py              # K8s Deployment/Service for app
│       ├── cluster.py          # GKE cluster
│       ├── database.py         # Cloud SQL
│       ├── temporal.py         # Temporal Helm chart
│       ├── jaeger.py           # Jaeger deployment
│       ├── prometheus.py       # Prometheus deployment
│       ├── secrets.py          # External Secrets Operator
│       ├── network_policy.py   # NetworkPolicy resources
│       └── ...                 # certmanager, ingress, iam, identity, migration, namespaces, pdb, registry, opensearch, cd, state_bucket
├── docs/                       # Human-readable documentation
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── CONFIGURATION.md
│   ├── DEPLOYMENT.md
│   ├── DEVELOPMENT.md
│   ├── GETTING-STARTED.md
│   └── TESTING.md
├── grafana/                    # Grafana dashboard provisioning configs
├── jaeger/                     # Jaeger collector/query YAML configs
├── prometheus/                 # Prometheus scrape config
├── .github/workflows/          # GitHub Actions CI/CD
│   ├── ci.yml                  # Test + lint on push
│   ├── cd-base.yml             # Reusable deploy workflow
│   ├── cd-dev.yml
│   ├── cd-staging.yml
│   └── cd-prod.yml
├── .claude/skills/             # Claude agent skill definitions
│   ├── temporal/               # Temporal SDK patterns and rules
│   └── pinecone/               # Pinecone SDK reference
├── .planning/                  # GSD planning artifacts (not shipped)
├── Dockerfile                  # App container image
├── docker-compose.yml          # Local dev: postgres, temporal, jaeger, opensearch, grafana, app
├── alembic.ini                 # Alembic configuration
├── pyproject.toml              # Project metadata, dependencies, ruff, pytest config
├── AGENTS.md                   # AI agent conventions (FastAPI, SOLID, DRY, DB naming)
└── CONTRIBUTING.md             # Contributor guide
```

---

## Directory Purposes

**`src/`:**
- All application Python code. Organized by domain (one subdirectory per bounded context).
- Top-level files (`main.py`, `config.py`, `database.py`, `repository.py`, `models.py`, `metrics.py`, `exceptions.py`, `money.py`) are cross-cutting infrastructure shared by all domains.

**`src/sms/`:**
- Everything related to Twilio SMS ingress: webhook validation, idempotency, user creation, rate limiting, message persistence.
- The only domain with a FastAPI `router.py` — it is the sole HTTP surface area of the app.

**`src/extraction/`:**
- GPT classification and embedding generation. Pure I/O: no DB writes. `service.py` only takes text in, returns structured Pydantic objects out.
- `models.py` here contains `PineconeSyncQueue` — a queue table owned by the extraction failure recovery path. This placement is a minor smell; the table is managed by `JobPostingHandler`, not `ExtractionService`.

**`src/pipeline/`:**
- Orchestration layer. Owns the Chain of Responsibility dispatch. Handlers in `handlers/` are the only code that owns a transaction commit in the async processing path.
- `context.py` is a pure value object (dataclass) — no logic.
- `constants.py` contains only OTel attribute key strings.

**`src/temporal/`:**
- Temporal SDK integration. Workflows must be deterministic; all side effects live in activities. Worker startup and cron scheduling in `worker.py`.
- Module-level singletons `_orchestrator` and `_openai_client` in `activities.py` are set by `worker.py` before worker start.

**`src/jobs/`, `src/work_goals/`, `src/users/`:**
- Pure domain modules: model + repository (+ schema where needed). No service layer — business logic lives in pipeline handlers or `MatchService`.

**`src/matches/`:**
- Fully implemented matching domain (0/1 knapsack DP, SMS formatter) but **not connected to the live pipeline**. `MatchService.match()` is never called from a workflow or handler. This domain is ready for wiring but currently dead code.

**`tests/`:**
- Mirrors `src/` domain layout with subdirectory-per-domain test packages.
- Root-level test files are for cross-cutting concerns (config, health, logging, OTel, pipeline orchestrator, 3NF normalization assertions).
- `tests/infra/` contains static analysis tests against Pulumi/GitHub Actions YAML — not application tests.
- All tests use SQLite in-memory for DB (via `aiosqlite`); no real PostgreSQL or Temporal required.

**`migrations/`:**
- Alembic async migrations. File naming convention: `YYYY-MM-DD_slug.py`. Six migrations to date:
  - `2026-03-05_initial_schema.py`
  - `2026-03-06_extraction_additions.py`
  - `2026-04-03_normalize_3nf.py`
  - `2026-04-04_add_job_status.py`
  - `2026-04-04_add_phone_e164.py`
  - `2026-04-04_money_columns_to_cents.py`

**`infra/`:**
- Separate Python package with its own `pyproject.toml` and `.venv`. Pulumi IaC targeting GKE/GCP.
- `components/` has one file per infrastructure resource type (cluster, database, temporal, jaeger, prometheus, secrets, ingress, etc.).

---

## Key File Locations

**Entry Points:**
- `src/main.py` — FastAPI `app` object; `create_app()` factory; `lifespan()` context manager
- `src/temporal/worker.py` — `run_worker()`, `start_cron_if_needed()`

**Configuration:**
- `src/config.py` — `Settings` (Pydantic BaseSettings), `get_settings()` (lru_cache singleton)
- `src/database.py` — `get_engine()`, `get_sessionmaker()`, `get_session()`
- `alembic.ini` — Alembic config (file_template, script_location)
- `pyproject.toml` — Dependencies, pytest config, ruff config

**Domain Models (SQLModel tables):**
- `src/users/models.py` — `User`
- `src/sms/models.py` — `Message`, `RateLimit`, `AuditLog`
- `src/jobs/models.py` — `Job`
- `src/work_goals/models.py` — `WorkGoal`
- `src/matches/models.py` — `Match`
- `src/extraction/models.py` — `PineconeSyncQueue`
- `src/models.py` — Import registry (Alembic/test `create_all`)

**Core Business Logic:**
- `src/pipeline/orchestrator.py` — Classification dispatch
- `src/pipeline/handlers/job_posting.py` — Job persistence + Pinecone upsert
- `src/pipeline/handlers/worker_goal.py` — WorkGoal persistence
- `src/extraction/service.py` — GPT classification
- `src/matches/service.py` — Knapsack matching (currently unwired)

**Testing:**
- `tests/conftest.py` — All shared fixtures
- `tests/integration/` — Full route tests per message type

---

## Naming Conventions

**Files:**
- Domain modules use `snake_case.py` matching AGENTS.md prescribed layout
- Test files: `test_<subject>.py` — either flat in `tests/` or in `tests/<domain>/`
- Migration files: `YYYY-MM-DD_slug.py` (enforced by `alembic.ini` `file_template`)

**Directories:**
- Domain directories: `snake_case` singular noun (`sms`, `jobs`, `work_goals`, `matches`, `extraction`, `users`, `pipeline`, `temporal`)
- No plural directory names except `handlers/` inside `pipeline/`

**Python Identifiers:**
- Classes: `PascalCase` (`JobRepository`, `ExtractionService`, `WorkGoalHandler`)
- Functions/methods: `snake_case` (`get_or_create`, `find_candidates_for_goal`)
- Constants: `UPPER_SNAKE_CASE` in `constants.py` files
- Module-level private singletons: `_leading_underscore` (`_orchestrator`, `_openai_client`)
- OTel attribute keys: `OTEL_ATTR_*` prefix in `src/pipeline/constants.py`

**Database Tables:**
- `lower_case_snake` singular nouns: `user`, `message`, `job`, `work_goal`, `match`, `audit_log`, `rate_limit`, `pinecone_sync_queue`
- DateTime columns: `_at` suffix (`created_at`)
- FK columns: `{referenced_table}_id` (e.g., `user_id`, `message_id`, `job_id`)

---

## Where to Add New Code

**New domain (e.g., `notifications`):**
```
src/notifications/
├── __init__.py
├── models.py       # SQLModel table(s)
├── repository.py   # Extends BaseRepository
├── schemas.py      # Pydantic create/response models
├── service.py      # Business logic
├── constants.py    # Domain constants
└── exceptions.py   # Domain exceptions (if needed)
```
Register new SQLModel tables in `src/models.py` for Alembic discovery.
Add tests under `tests/notifications/`.

**New pipeline handler:**
- Create `src/pipeline/handlers/<name>.py` implementing `MessageHandler` ABC (`can_handle`, `handle`)
- Add new classification type to `ExtractionResult.message_type` Literal in `src/extraction/schemas.py`
- Register handler in `src/main.py` lifespan DI graph (`handlers` list, order matters — `UnknownMessageHandler` must remain last)

**New Temporal workflow:**
- Define `@workflow.defn` class in `src/temporal/workflows.py`
- Define `@activity.defn` functions in `src/temporal/activities.py`
- Register both in `Worker(...)` in `src/temporal/worker.py`

**New API endpoint:**
- Add route to `src/sms/router.py` (existing router) or create `src/<domain>/router.py` and register with `app.include_router()` in `src/main.py`

**New configuration value:**
- Add to the relevant `BaseModel` sub-config in `src/config.py` (`SmsSettings`, `ExtractionSettings`, etc.)
- Add flat env var to `Settings` and map it in `_build_sub_models` validator
- Add to `.env.app.example`

**New database migration:**
- Run `uv run alembic revision --autogenerate -m "slug"` (naming enforced by `alembic.ini`)
- Verify migration is reversible (add `downgrade()` body)

**Shared utilities:**
- Money conversions: `src/money.py`
- OTel attribute keys: `src/pipeline/constants.py`
- Prometheus metrics: `src/metrics.py` (module-level singletons only — never instantiate inside functions)

---

## Special Directories

**`.planning/`:**
- Purpose: GSD planning artifacts, codebase maps, phase plans, todos
- Generated: No (hand-edited + agent-written)
- Committed: Yes

**`.claude/skills/`:**
- Purpose: Claude agent skill definitions for Temporal and Pinecone SDK patterns
- Generated: No
- Committed: Yes

**`infra/.venv/`:**
- Purpose: Separate virtualenv for Pulumi IaC (different dependency set from app)
- Generated: Yes
- Committed: No

**`.venv/` (root):**
- Purpose: App virtualenv managed by `uv`
- Generated: Yes
- Committed: No

---

## Folders That Violate or Diverge from the Stated Structure

**`src/extraction/models.py` contains `PineconeSyncQueue`:**
The `PineconeSyncQueue` table is a persistence concern for the Pinecone upsert failure path, which is owned by `JobPostingHandler` in the `pipeline` domain. Placing it in `extraction/` leaks the queue abstraction into the wrong domain. It would be more cohesive in `src/jobs/models.py` or a dedicated `src/pinecone/` domain. Currently `src/models.py` imports it from `src/extraction/models.py`, which is correct for registration but wrong for ownership.

**`src/sms/` has two repository files (`repository.py` and `audit_repository.py`):**
AGENTS.md prescribes a single `repository.py` per domain. `AuditLogRepository` is split into its own file because it is used cross-domain (by `pipeline/orchestrator.py` and all pipeline handlers). It could be renamed `src/sms/audit_repository.py` as a deliberate exception or moved to `src/` root if it is truly cross-cutting. Current placement is not wrong but deviates from convention.

**`tests/` root-level flat test files mixed with subdirectory packages:**
`tests/test_pipeline_orchestrator.py`, `tests/test_pipeline_hardening.py`, `tests/test_repositories.py`, etc. exist at root level alongside `tests/extraction/`, `tests/sms/`, etc. The pipeline and repository tests would be more consistent under `tests/pipeline/` and `tests/repositories/`. The mixed flat + package layout makes it harder to run domain-scoped test subsets.

**`tests/infra/` tests infrastructure YAML, not application code:**
Static assertions against Pulumi component files and GitHub Actions workflows live here. They are not application tests and are not parallelized with unit/integration tests. A separate `make test-infra` target or a distinct CI step would better delineate these from the pytest application suite.

---

*Structure analysis: 2026-04-22*
