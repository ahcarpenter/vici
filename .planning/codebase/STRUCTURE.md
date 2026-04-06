# Codebase Structure

**Analysis Date:** 2026-04-06

## Directory Layout

```
vici/
├── src/                        # Application source code
│   ├── main.py                 # FastAPI app factory, lifespan DI, OTel/structlog config
│   ├── config.py               # Pydantic Settings with nested sub-models
│   ├── database.py             # Async SQLAlchemy engine + sessionmaker
│   ├── models.py               # Central model re-export (all SQLModels)
│   ├── repository.py           # BaseRepository ABC (flush-only _persist)
│   ├── exceptions.py           # Global exception handlers
│   ├── metrics.py              # Prometheus metric singletons
│   ├── money.py                # dollars_to_cents / cents_to_dollars utilities
│   ├── __init__.py             # Package marker
│   ├── sms/                    # SMS/Twilio webhook domain
│   ├── extraction/             # GPT classification + Pinecone embedding
│   ├── pipeline/               # Message processing pipeline + handlers
│   ├── temporal/               # Temporal workflows, activities, worker
│   ├── jobs/                   # Job posting domain
│   ├── work_goals/             # Worker earnings goal domain
│   ├── users/                  # User identity domain
│   └── matches/                # Job-to-goal matching domain
├── migrations/                 # Alembic database migrations
│   └── versions/               # Migration scripts (6 files)
├── infra/                      # Pulumi IaC for GKE deployment
│   ├── __main__.py             # Pulumi entrypoint
│   ├── config.py               # Pulumi config loader
│   ├── components/             # Modular infra components
│   ├── Pulumi.yaml             # Pulumi project config
│   ├── Pulumi.dev.yaml         # Dev stack config
│   ├── Pulumi.staging.yaml     # Staging stack config
│   └── Pulumi.prod.yaml        # Prod stack config
├── tests/                      # Test suite
│   ├── extraction/             # Extraction service tests
│   ├── sms/                    # SMS domain tests
│   ├── matches/                # Match service tests
│   ├── temporal/               # Temporal workflow/activity tests
│   ├── integration/            # Integration tests
│   └── infra/                  # Infrastructure tests
├── grafana/                    # Grafana provisioning
│   └── provisioning/           # Dashboard and datasource configs
├── prometheus/                 # Prometheus config
│   └── prometheus.yml          # Scrape configuration
├── jaeger/                     # Jaeger collector/query configs
├── docs/                       # Project documentation
├── .planning/                  # GSD planning artifacts
├── .github/                    # GitHub Actions workflows
├── Dockerfile                  # Multi-stage Python 3.12 build
├── docker-compose.yml          # Local dev stack (9 services)
├── pyproject.toml              # Python project config (uv/ruff)
├── alembic.ini                 # Alembic migration config
├── AGENTS.md                   # AI agent coding conventions
├── CLAUDE.md                   # Claude entrypoint (@AGENTS.md)
└── README.md                   # Project documentation
```

## Directory Purposes

**`src/sms/`:**
- Purpose: Twilio webhook ingestion, message persistence, rate limiting, audit logging
- Contains: Router, dependencies (4-gate chain), repository, audit repository, service, models, schemas, exceptions, constants
- Key files: `src/sms/router.py` (POST /webhook/sms), `src/sms/dependencies.py` (gate chain), `src/sms/models.py` (Message, RateLimit, AuditLog)

**`src/extraction/`:**
- Purpose: GPT-powered SMS classification and structured data extraction, Pinecone embedding generation
- Contains: ExtractionService, Pydantic extraction schemas, system prompt, embedding utility, constants
- Key files: `src/extraction/service.py` (ExtractionService), `src/extraction/schemas.py` (ExtractionResult), `src/extraction/prompts.py` (SYSTEM_PROMPT), `src/extraction/utils.py` (write_job_embedding)

**`src/pipeline/`:**
- Purpose: Message processing orchestration using Chain of Responsibility pattern
- Contains: Orchestrator, context dataclass, handler ABC and concrete implementations
- Key files: `src/pipeline/orchestrator.py` (PipelineOrchestrator), `src/pipeline/handlers/base.py` (MessageHandler ABC), `src/pipeline/handlers/job_posting.py`, `src/pipeline/handlers/worker_goal.py`, `src/pipeline/handlers/unknown.py`

**`src/temporal/`:**
- Purpose: Temporal workflow definitions, activity implementations, worker lifecycle
- Contains: Workflow classes, activity functions, worker setup, constants for timeouts/retries
- Key files: `src/temporal/workflows.py` (ProcessMessageWorkflow, SyncPineconeQueueWorkflow), `src/temporal/activities.py` (process_message_activity, sync_pinecone_queue_activity), `src/temporal/worker.py` (run_worker, get_temporal_client)

**`src/jobs/`:**
- Purpose: Job posting domain -- model, repository, create schema
- Contains: Job SQLModel, JobRepository (create + find_candidates_for_goal), JobCreate Pydantic schema
- Key files: `src/jobs/models.py`, `src/jobs/repository.py`, `src/jobs/schemas.py`

**`src/work_goals/`:**
- Purpose: Worker earnings goal domain -- model, repository, create schema
- Contains: WorkGoal SQLModel, WorkGoalRepository (create), WorkGoalCreate Pydantic schema
- Key files: `src/work_goals/models.py`, `src/work_goals/repository.py`, `src/work_goals/schemas.py`

**`src/users/`:**
- Purpose: User identity domain -- phone-hash-based upsert
- Contains: User SQLModel, UserRepository (get_or_create static method)
- Key files: `src/users/models.py`, `src/users/repository.py`

**`src/matches/`:**
- Purpose: Job-to-goal matching via 0/1 knapsack DP, SMS reply formatting
- Contains: MatchService, MatchRepository, JobCandidate/MatchResult dataclasses, format_match_sms formatter
- Key files: `src/matches/service.py` (MatchService with _dp_select), `src/matches/repository.py`, `src/matches/schemas.py`, `src/matches/formatter.py`

**`infra/`:**
- Purpose: Pulumi infrastructure-as-code for GKE-based production deployment
- Contains: Main Pulumi program, per-stack configs, modular component files
- Key files: `infra/__main__.py`, `infra/config.py`, `infra/components/cluster.py`, `infra/components/database.py`, `infra/components/temporal.py`, `infra/components/secrets.py`, `infra/components/app.py`

**`migrations/`:**
- Purpose: Alembic database migration scripts
- Contains: 6 versioned migration files covering initial schema through 3NF normalization
- Key files: `migrations/versions/2026-03-05_initial_schema.py`, `migrations/versions/2026-04-03_normalize_3nf.py`

## Key File Locations

**Entry Points:**
- `src/main.py`: FastAPI app factory, lifespan DI graph, OTel/structlog configuration
- `src/temporal/worker.py`: Temporal worker lifecycle (run_worker, start_cron_if_needed)
- `infra/__main__.py`: Pulumi infrastructure entrypoint

**Configuration:**
- `src/config.py`: Application settings (Pydantic BaseSettings with nested sub-models)
- `docker-compose.yml`: Local development stack (9 services)
- `Dockerfile`: Multi-stage production build (Python 3.12-slim, uv)
- `alembic.ini`: Alembic migration configuration
- `pyproject.toml`: Python project metadata, dependencies, ruff/pytest config
- `.env.app.example`: Application env var template (never read .env files directly)

**Core Logic:**
- `src/pipeline/orchestrator.py`: Central message processing orchestrator
- `src/extraction/service.py`: GPT classification and extraction
- `src/matches/service.py`: Job matching algorithm (0/1 knapsack DP)
- `src/sms/dependencies.py`: Webhook validation gate chain

**Shared Utilities:**
- `src/repository.py`: BaseRepository with _persist Template Method
- `src/money.py`: Cent/dollar conversion functions
- `src/metrics.py`: Prometheus metric singletons
- `src/exceptions.py`: Global exception handlers
- `src/database.py`: Async SQLAlchemy engine and session factories
- `src/models.py`: Central re-export of all SQLModel classes

**Testing:**
- `tests/extraction/`: Extraction service tests
- `tests/sms/`: SMS domain tests
- `tests/matches/`: Match service/formatter tests
- `tests/temporal/`: Temporal workflow/activity tests
- `tests/integration/`: End-to-end integration tests
- `tests/infra/`: Infrastructure tests

## Naming Conventions

**Files:**
- `snake_case.py` for all Python modules
- Domain modules follow the canonical set: `models.py`, `repository.py`, `schemas.py`, `service.py`, `router.py`, `dependencies.py`, `constants.py`, `exceptions.py`
- Not every domain has every file -- only create what is needed

**Directories:**
- `snake_case/` for all domain packages (e.g., `work_goals/`, `sms/`)
- Singular names for domain concepts following DB naming convention (e.g., `jobs/` contains `Job` model for `job` table)
- `handlers/` sub-package under `pipeline/` for Chain of Responsibility implementations

**Database Tables:**
- `lower_case_snake`, singular: `user`, `job`, `message`, `work_goal`, `match`, `audit_log`, `rate_limit`, `pinecone_sync_queue`
- DateTime columns use `_at` suffix: `created_at`
- Foreign keys: `{referenced_table}_id` (e.g., `user_id`, `message_id`, `job_id`)

## Where to Add New Code

**New Domain (e.g., notifications, payments):**
- Create `src/{domain}/` package with `__init__.py`
- Add `models.py` (SQLModel), `repository.py` (extends BaseRepository), `schemas.py` (Pydantic)
- Add `service.py` if business logic beyond CRUD is needed
- Add `router.py` if the domain exposes HTTP endpoints; register in `src/main.py` `create_app()`
- Re-export model in `src/models.py` for Alembic auto-detection
- Create migration: `alembic revision --autogenerate -m "{description}"`
- Add tests in `tests/{domain}/`

**New Pipeline Handler (new message type):**
- Create `src/pipeline/handlers/{type_name}.py` extending `MessageHandler` from `src/pipeline/handlers/base.py`
- Implement `can_handle(result)` and `handle(ctx)` methods
- Add to handlers list in `src/main.py` lifespan -- order matters (before `UnknownMessageHandler`)
- Add `message_type` literal value to `ExtractionResult.message_type` in `src/extraction/schemas.py`
- Update GPT system prompt in `src/extraction/prompts.py` with new type definition and few-shot examples

**New Temporal Workflow:**
- Define workflow class in `src/temporal/workflows.py`
- Define activity functions in `src/temporal/activities.py`
- Register workflow and activities in `src/temporal/worker.py` `run_worker()`
- Add timeout/retry constants to `src/temporal/constants.py`

**New API Endpoint:**
- Create or extend `router.py` in the relevant domain package
- Register router in `src/main.py` `create_app()` via `app.include_router()`
- Add dependencies in the domain's `dependencies.py` if validation/auth gates are needed

**New Prometheus Metric:**
- Define metric singleton in `src/metrics.py` (module-level, never inside classes)
- Import and use in the relevant module

**New Migration:**
- Run `alembic revision --autogenerate -m "{description}"` (generates file in `migrations/versions/`)
- File naming follows `%%(year)d-%%(month).2d-%%(day).2d_%%(slug)s` pattern per `alembic.ini`

**New Infrastructure Component:**
- Create `infra/components/{component}.py`
- Import and wire in `infra/__main__.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning artifacts -- phases, research, todos, workstreams, codebase analysis
- Generated: By GSD commands (automated planning)
- Committed: Yes

**`migrations/versions/`:**
- Purpose: Alembic database migration scripts
- Generated: By `alembic revision --autogenerate`
- Committed: Yes

**`grafana/provisioning/`:**
- Purpose: Grafana dashboard and datasource provisioning configs
- Generated: No (manually authored)
- Committed: Yes

**`infra/`:**
- Purpose: Pulumi IaC -- not part of the application runtime
- Generated: No (manually authored)
- Committed: Yes
- Note: Has its own `requirements.txt` and `.venv/` separate from the app

**`.github/workflows/`:**
- Purpose: GitHub Actions CI/CD pipeline definitions
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-04-06*
