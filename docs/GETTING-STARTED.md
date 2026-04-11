<!-- generated-by: gsd-doc-writer -->
# Getting Started

This guide walks a new contributor from zero to a running Vici stack. For the full project overview see [../README.md](../README.md), for system design see [ARCHITECTURE.md](ARCHITECTURE.md), and for the complete environment-variable reference see [CONFIGURATION.md](CONFIGURATION.md).

## Prerequisites

- **Python >= 3.12** — required by `pyproject.toml` (`requires-python = ">=3.12"`) and matched by the `python:3.12-slim` base image in `Dockerfile`.
- **[uv](https://docs.astral.sh/uv/)** — used for dependency management and task execution. Install with `pip install uv` or follow the upstream instructions.
- **Docker** and **Docker Compose v2** — required to run the full local stack (Postgres, OpenSearch, Jaeger collector, Jaeger query, Temporal, Temporal UI, Prometheus, Grafana, and the FastAPI `app`) from `docker-compose.yml`.
- **API accounts** for Twilio, OpenAI, and Pinecone (Braintrust is optional). Required credentials are enforced at startup by `src/config.py::Settings._validate_required_credentials`.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/ahcarpenter/vici.git
   cd vici
   ```

2. Install Python dependencies (creates `.venv/` via uv):

   ```bash
   uv sync
   ```

3. Copy the per-service example env files and fill in secrets. Docker Compose reads a separate env file for each container (see the `env_file:` entries in `docker-compose.yml`), so all seven must exist before `docker compose up`:

   ```bash
   cp .env.app.example .env.app
   cp .env.postgres.example .env.postgres
   cp .env.opensearch.example .env.opensearch
   cp .env.jaeger-query.example .env.jaeger-query
   cp .env.temporal.example .env.temporal
   cp .env.temporal-ui.example .env.temporal-ui
   cp .env.grafana.example .env.grafana
   ```

   For the full list of variables (which are required, which have defaults, and where to obtain each value), see [CONFIGURATION.md](CONFIGURATION.md).

   The application's Pydantic `Settings` validator (`src/config.py::Settings._validate_required_credentials`) raises `ValueError: Required credentials are missing or empty: ...` at startup if any of the following are empty in `.env.app`:

   - `DATABASE_URL`
   - `TWILIO_AUTH_TOKEN`
   - `OPENAI_API_KEY`
   - `PINECONE_API_KEY`
   - `TEMPORAL_ADDRESS`
   - `WEBHOOK_BASE_URL`
   - `ENV`

## First Run

Start the full stack with Docker Compose:

```bash
docker compose up --build
```

The `app` service (defined in `docker-compose.yml`) runs:

```text
sh -c "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
```

So Alembic migrations apply automatically before Uvicorn starts. The container has `depends_on` entries for `postgres` (`service_healthy`), `jaeger-collector` (`service_started`), and `temporal` (`service_healthy`) — if Temporal is still warming up on first boot, the app may restart once or twice while it waits.

Once the stack is up, verify the API liveness and readiness endpoints defined in `src/main.py`:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/readyz
# {"status":"ok","db":"connected"}
```

Exposed ports (from `docker-compose.yml`):

| Service       | URL                    |
|---------------|------------------------|
| FastAPI app   | http://localhost:8000  |
| Postgres      | localhost:5432         |
| OpenSearch    | http://localhost:9200  |
| Temporal      | localhost:7233         |
| Temporal UI   | http://localhost:8080  |
| Jaeger UI     | http://localhost:16686 |
| Prometheus    | http://localhost:9090  |
| Grafana       | http://localhost:3000  |
| OTLP gRPC     | localhost:4317         |
| OTLP HTTP     | localhost:4318         |

### Running the App Outside Docker

If Postgres, Temporal, and OpenSearch are already reachable on your machine, you can run the FastAPI app directly with uv. In this mode Pydantic Settings loads variables from a `.env` file at the repo root (see `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` in `src/config.py`), not from `.env.app`:

```bash
# Apply migrations
uv run alembic upgrade head

# Start the API with hot reload
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Make sure `DATABASE_URL` in `.env` points at a reachable host — `postgresql+asyncpg://vici:<password>@localhost:5432/vici` if Postgres is running via Docker Compose with the default port mapping. The driver must be `postgresql+asyncpg` (SQLAlchemy async).

## Common Setup Issues

- **Missing environment variables at startup** — `Settings._validate_required_credentials` (in `src/config.py`) fails fast if any of the seven required variables listed above are empty. The error message lists exactly which ones are missing; populate them in `.env.app` (Docker) or `.env` (running locally).

- **Postgres connection refused** — When running the app outside Docker while Postgres runs inside Docker Compose, point `DATABASE_URL` at `localhost:5432`, not the Compose hostname `postgres`. The driver must be `postgresql+asyncpg` (SQLAlchemy async).

- **Temporal health check flapping** — The `temporal` service uses `temporalio/auto-setup:1.26.2` with a health check that has `start_period: 30s` and `retries: 10`. On first boot it provisions its Postgres schema, and the `app` container (which `depends_on: temporal: service_healthy`) will wait. If the app keeps restarting, check `docker compose logs temporal` for migration progress before assuming a misconfiguration.

- **Port conflicts** — The stack binds host ports 3000, 4317, 4318, 5432, 7233, 8000, 8080, 9090, 9200, and 16686. Stop any local services using these ports (a common culprit is a host Postgres on 5432) before running `docker compose up`.

- **uv not found** — All tasks are invoked via `uv run ...`. If `uv` is not on your PATH after `pip install uv`, check your Python user-site `bin/` directory or reinstall via the uv standalone installer.

## Next Steps

- [../README.md](../README.md) — Full project overview, features, tech stack, and top-level quick start.
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, domain layout under `src/`, and the inbound SMS pipeline flow.
- [CONFIGURATION.md](CONFIGURATION.md) — Complete settings reference, required vs. optional variables, defaults, and per-environment overrides.
- [DEVELOPMENT.md](DEVELOPMENT.md) — Local development workflow, linting, and build commands.
- [TESTING.md](TESTING.md) — How to run the test suite and write new tests.
