<!-- generated-by: gsd-doc-writer -->
# Development

Guide for setting up and contributing to the Vici project locally.

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

3. Install all dependencies including dev tools:

   ```bash
   uv sync
   ```

4. Copy the example env files for each service and fill in required values (see [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference):

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

   The app will be available at `http://localhost:8000`. The `docker-compose.yml` `app` service performs steps 6-7 automatically if you prefer running everything in containers via `docker compose up`.

## Build commands

| Command | Description |
|---------|-------------|
| `uv sync` | Install all dependencies (including dev group) |
| `uv sync --frozen --no-dev` | Install production dependencies only (reproducible lockfile) |
| `uv run uvicorn src.main:app --reload` | Start the dev server with hot reload |
| `uv run alembic upgrade head` | Apply all pending database migrations |
| `uv run alembic revision --autogenerate -m "description"` | Generate a new migration from model changes |
| `uv run ruff check src/ tests/` | Lint source and test files |
| `uv run ruff check --fix src/ tests/` | Lint and auto-fix where possible |
| `uv run ruff format src/ tests/` | Format source and test files |
| `uv run pytest tests/ -x --tb=short -q` | Run the test suite |
| `uv run pytest tests/ --cov=src` | Run tests with coverage reporting |
| `docker compose up` | Start the full stack (app, Postgres, Temporal, Jaeger, Prometheus, Grafana) |
| `docker compose up -d postgres temporal` | Start only database and workflow infrastructure |

## Code style

- **Ruff** is used for both linting and formatting. Configuration lives in `pyproject.toml` under `[tool.ruff]`.
  - Target version: Python 3.12
  - Lint rules enabled: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort import sorting)
  - Long lines are exempted in `src/extraction/prompts.py` for LLM prompt strings
- Run before committing:

  ```bash
  uv run ruff check --fix src/ tests/
  uv run ruff format src/ tests/
  ```

- CI runs `uv run ruff check src/ tests/` on every push and pull request (see `.github/workflows/ci.yml`). The lint step currently uses `continue-on-error: true` while formatting is being normalized.

## Branch conventions

No formal branch naming convention is documented. The default branch is `main`. Recent commit messages follow the pattern `type(scope): description` (e.g., `docs(phase-03): add security threat verification`), suggesting conventional-commit style is preferred.

## PR process

- Open pull requests against the `main` branch.
- CI automatically runs linting and tests on every pull request (`.github/workflows/ci.yml`).
- Tests execute against an in-memory SQLite database in CI, so no external services are required for the test suite to pass.
- No pull request template is configured. Ensure your PR description explains the motivation for the change and any testing performed.

## Docker Compose services

The full local stack is defined in `docker-compose.yml`:

| Service | Port | Purpose |
|---------|------|---------|
| `postgres` | 5432 | Primary PostgreSQL 16 database |
| `opensearch` | 9200 | Trace storage backend for Jaeger |
| `jaeger-collector` | 4317, 4318 | Receives OpenTelemetry traces (gRPC and HTTP) |
| `jaeger-query` | 16686 | Jaeger UI for viewing traces |
| `app` | 8000 | The Vici FastAPI application |
| `temporal` | 7233 | Temporal workflow server |
| `temporal-ui` | 8080 | Temporal web dashboard |
| `prometheus` | 9090 | Metrics collection and querying |
| `grafana` | 3000 | Metrics dashboards and alerting |

## Migrations

Alembic is used for database migrations. Migration files live in `migrations/versions/` and follow the naming template `YYYY-MM-DD_slug.py` (configured in `alembic.ini`).

To create a new migration after modifying SQLModel models:

```bash
uv run alembic revision --autogenerate -m "short_description"
```

Review the generated file to ensure the `upgrade()` and `downgrade()` functions are correct before committing.
