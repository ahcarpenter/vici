<!-- generated-by: gsd-doc-writer -->
# Development

Guide for setting up and contributing to the Vici project locally. For a high-level tour of the system, see [ARCHITECTURE.md](ARCHITECTURE.md); for the full environment-variable reference, see [CONFIGURATION.md](CONFIGURATION.md); for the first-run walkthrough, see [GETTING-STARTED.md](GETTING-STARTED.md).

## Local setup

1. Clone the repository:

   ```bash
   git clone https://github.com/ahcarpenter/vici.git
   cd vici
   ```

2. Install [uv](https://docs.astral.sh/uv/) (the project package manager):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. Install all dependencies including the dev group:

   ```bash
   uv sync
   ```

   This creates a `.venv/` alongside `pyproject.toml` and installs everything under `[project].dependencies` plus the `dev` group defined in `[dependency-groups]` (aiosqlite, httpx, pytest, pytest-asyncio, pytest-cov, ruff).

4. Copy the example env files for each service and fill in required values. Every file under `.env.*.example` at the repository root has a matching `env_file:` entry in `docker-compose.yml`. See [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference.

   ```bash
   cp .env.app.example .env.app
   cp .env.postgres.example .env.postgres
   cp .env.opensearch.example .env.opensearch
   cp .env.jaeger-query.example .env.jaeger-query
   cp .env.temporal.example .env.temporal
   cp .env.temporal-ui.example .env.temporal-ui
   cp .env.grafana.example .env.grafana
   ```

5. Start infrastructure services with Docker Compose:

   ```bash
   docker compose up -d postgres temporal jaeger-collector opensearch
   ```

6. Run database migrations:

   ```bash
   uv run alembic upgrade head
   ```

7. Start the development server:

   ```bash
   uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

   The app will be available at `http://localhost:8000`. The `docker-compose.yml` `app` service performs steps 6-7 automatically (its command is `uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload`) if you prefer running everything in containers via `docker compose up`.

## Build commands

| Command | Description |
|---------|-------------|
| `uv sync` | Install all dependencies including the dev group |
| `uv sync --frozen` | Install from the locked `uv.lock` without resolving (matches CI) |
| `uv sync --frozen --no-dev` | Install production dependencies only (reproducible lockfile) |
| `uv run uvicorn src.main:app --reload` | Start the dev server with hot reload |
| `uv run alembic upgrade head` | Apply all pending database migrations |
| `uv run alembic revision --autogenerate -m "description"` | Generate a new migration from model changes |
| `uv run ruff check src/ tests/` | Lint source and test files |
| `uv run ruff check --fix src/ tests/` | Lint and auto-fix where possible |
| `uv run ruff format src/ tests/` | Format source and test files |
| `uv run pytest tests/ -x --tb=short -q` | Run the test suite (fail-fast, matches CI) |
| `uv run pytest tests/ --cov=src` | Run tests with coverage reporting |
| `docker compose up` | Start the full stack (app, Postgres, OpenSearch, Jaeger, Temporal, Temporal UI, Prometheus, Grafana) |
| `docker compose up -d postgres temporal` | Start only database and workflow infrastructure |

See [TESTING.md](TESTING.md) for the full pytest guide and coverage details.

## Code style

- **Ruff** handles both linting and formatting. Configuration lives in `pyproject.toml` under `[tool.ruff]`.
  - Target version: Python 3.12 (`target-version = "py312"`)
  - Lint rules enabled: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort import sorting)
  - Per-file ignore: `src/extraction/prompts.py` exempts `E501` (long lines) for LLM prompt strings
- The pinned dev version is `ruff>=0.15.5` (see `[dependency-groups].dev` in `pyproject.toml`).
- Run before committing:

  ```bash
  uv run ruff check --fix src/ tests/
  uv run ruff format src/ tests/
  ```

- CI runs `uv run ruff check src/ tests/` on every push to `main` and every pull request targeting `main` (see `.github/workflows/ci.yml`, `Lint` step). Lint failures fail the build — `continue-on-error` is not set on the Lint step.

## Project structure conventions

The `src/` tree is organized by **domain**, not by file type, following the FastAPI best-practices described in `AGENTS.md`. Each domain package may contain:

- `router.py` — API endpoints
- `schemas.py` — Pydantic request/response models
- `models.py` — SQLModel database models
- `service.py` — Business logic
- `repository.py` — Data access layer
- `dependencies.py` — Route dependencies (validation + DI)
- `config.py` — Domain-scoped `BaseSettings`
- `constants.py` — Constants and error codes
- `exceptions.py` — Domain-specific exceptions
- `utils.py` — Helper functions

Current domains under `src/`: `extraction/`, `jobs/`, `matches/`, `pipeline/`, `sms/`, `temporal/`, `users/`, `work_goals/`. Shared modules live at the top level: `config.py`, `database.py`, `exceptions.py`, `main.py`, `metrics.py`, `models.py`, `money.py`, `repository.py`.

When importing across domains, use explicit module names to preserve namespace clarity:

```python
from src.extraction import service as extraction_service
from src.users import constants as user_constants
```

## Branch conventions

No formal branch naming convention is documented. The default branch is `main`. Commit messages follow the conventional-commits style `type(scope): description` (examples from recent history: `fix(ci): ...`, `docs(05.1): ...`, `chore: ...`). Long-running feature branches use a `gsd/` prefix (e.g., `gsd/v1.0-milestone`) to denote in-progress milestone work.

## PR process

- Open pull requests against the `main` branch.
- CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request targeting `main`. The `test` job runs on `ubuntu-latest` and performs four steps:
  1. `actions/checkout@v4`
  2. `astral-sh/setup-uv@v5` (with cache enabled)
  3. `uv sync --frozen`
  4. `uv run ruff check src/ tests/`
  5. `uv run pytest tests/ -x --tb=short -q`
- Tests execute against an in-memory-style SQLite database in CI (`DATABASE_URL=sqlite+aiosqlite:///./test.db`), so no external services are required for the test suite to pass. CI also injects placeholder secrets for Twilio, OpenAI, Pinecone, Braintrust, Inngest, and the webhook base URL — see the `env:` block of the `Test` step in `ci.yml` for the exact list.
- No pull request template is configured under `.github/`. Ensure your PR description explains the motivation for the change, the scope of affected domains, and any manual testing performed.
- The deployment workflows (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) are documented in [DEPLOYMENT.md](DEPLOYMENT.md); they are not part of the PR-time feedback loop.

## Docker Compose services

The full local stack is defined in `docker-compose.yml`:

| Service | Image | Port(s) | Purpose |
|---------|-------|---------|---------|
| `postgres` | `postgres:16` | 5432 | Primary PostgreSQL 16 database |
| `opensearch` | `opensearchproject/opensearch:2.19.4` | 9200 | Trace storage backend for Jaeger |
| `jaeger-collector` | `jaegertracing/jaeger:2.16.0` | 4317, 4318 | Receives OpenTelemetry traces (gRPC and HTTP) |
| `jaeger-query` | `jaegertracing/jaeger:2.16.0` | 16686 | Jaeger UI for viewing traces |
| `app` | built from `./Dockerfile` | 8000 | The Vici FastAPI application |
| `temporal` | `temporalio/auto-setup:1.26.2` | 7233 | Temporal workflow server |
| `temporal-ui` | `temporalio/ui:latest` | 8080 | Temporal web dashboard |
| `prometheus` | `prom/prometheus:v3.1.0` | 9090 | Metrics collection and querying |
| `grafana` | `grafana/grafana:11.4.0` | 3000 | Metrics dashboards and alerting |

## Migrations

Alembic manages database migrations. Migration files live in `migrations/versions/` and use the file template `%(year)d-%(month).2d-%(day).2d_%(slug)s` configured in `alembic.ini` (e.g., `2026-04-04_add_job_status.py`). The `sqlalchemy.url` is set programmatically in `migrations/env.py` — it reads `DATABASE_URL` from the environment first (so migration-only containers such as K8s Jobs need not instantiate the full `Settings` model) and falls back to `src.config.get_settings().database_url` otherwise. `migrations/env.py` also imports every SQLModel in `src.models` so `SQLModel.metadata` is populated before autogeneration runs.

To create a new migration after modifying SQLModel models:

```bash
uv run alembic revision --autogenerate -m "short_description"
```

Review the generated file to ensure the `upgrade()` and `downgrade()` functions are correct and reversible before committing. Keep migrations static — do not edit previously merged revision files.
