<!-- generated-by: gsd-doc-writer -->
# Vici

An SMS-driven job-matching backend that ingests inbound Twilio text messages, extracts structured job postings and worker goals with OpenAI, indexes them in Pinecone for semantic search, and orchestrates the pipeline with Temporal workflows on a FastAPI + PostgreSQL stack.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)

## Features

- **FastAPI** async webhook API with `/webhook/sms`, `/health`, `/readyz`, and `/metrics` endpoints
- **Twilio** inbound SMS ingestion with signature validation, idempotency, and per-sender rate limiting
- **OpenAI GPT** extraction pipeline for parsing unstructured SMS into job postings and worker goals
- **Pinecone** vector index for semantic job/worker matching (async SDK)
- **Temporal** workflow orchestration with a cron-scheduled Pinecone sync worker
- **PostgreSQL** persistence via SQLAlchemy / SQLModel with **Alembic** migrations
- **OpenTelemetry** tracing (OTLP → Jaeger) and **Prometheus** metrics, with pre-built Grafana dashboards
- **Structured logging** via structlog with automatic OTel trace correlation
- **Pulumi-on-GKE** infrastructure-as-code under `infra/` for production deployments

## Tech Stack

| Layer           | Technology                                              |
|-----------------|---------------------------------------------------------|
| Runtime         | Python 3.12+                                            |
| Package manager | [uv](https://github.com/astral-sh/uv)                   |
| Web framework   | FastAPI + Uvicorn                                       |
| ORM / migrations| SQLModel / SQLAlchemy (async) + Alembic                 |
| Database        | PostgreSQL 16 (asyncpg driver)                          |
| Workflows       | Temporal 1.26                                           |
| Vector search   | Pinecone (async SDK)                                    |
| LLM             | OpenAI (wrapped by Braintrust)                          |
| SMS gateway     | Twilio                                                  |
| Observability   | OpenTelemetry, Jaeger 2.16, Prometheus 3.1, Grafana 11  |
| Infra           | Pulumi on Google Kubernetes Engine                      |

## Prerequisites

- Python 3.12 or newer
- [uv](https://github.com/astral-sh/uv) (installs and manages the virtualenv and lockfile)
- Docker and Docker Compose (for the local full-stack environment)
- Credentials for: Twilio, OpenAI, Pinecone (see `docs/CONFIGURATION.md` for the complete list)

## Installation

Clone the repository and install dependencies with `uv`:

```bash
git clone <repository-url> vici
cd vici
uv sync
```

This creates a `.venv/` and installs the runtime and dev dependencies pinned in `uv.lock`.

## Quick Start

The fastest path to a working local stack is Docker Compose, which brings up PostgreSQL, Temporal, Jaeger, Prometheus, Grafana, and the FastAPI app together.

1. Create the required env files (`.env.app`, `.env.postgres`, `.env.temporal`, `.env.temporal-ui`, `.env.jaeger-query`, `.env.grafana`, `.env.opensearch`). See `docs/GETTING-STARTED.md` and `docs/CONFIGURATION.md` for variables.
2. Start the stack:

   ```bash
   docker compose up --build
   ```

3. The app container automatically runs `alembic upgrade head` before launching Uvicorn. Once healthy, endpoints are available at:

   | URL                                | Purpose                              |
   |------------------------------------|--------------------------------------|
   | http://localhost:8000/health       | Liveness probe                       |
   | http://localhost:8000/readyz       | Readiness probe (DB connectivity)    |
   | http://localhost:8000/metrics      | Prometheus metrics                   |
   | http://localhost:8000/webhook/sms  | Twilio inbound SMS webhook           |
   | http://localhost:8080              | Temporal Web UI                      |
   | http://localhost:16686             | Jaeger UI                            |
   | http://localhost:9090              | Prometheus                           |
   | http://localhost:3000              | Grafana                              |

4. Configure a Twilio webhook pointing at `${WEBHOOK_BASE_URL}/webhook/sms` to start ingesting SMS.

To run the API outside Docker against an existing Postgres and Temporal:

```bash
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

## Project Layout

```
vici/
├── src/
│   ├── main.py          # FastAPI app factory + lifespan (OTel, Temporal worker, gauges)
│   ├── config.py        # Pydantic Settings (flat env vars remapped into sub-models)
│   ├── database.py      # Async SQLAlchemy engine + session factory
│   ├── sms/             # Twilio webhook: router, service, rate-limit, audit
│   ├── extraction/      # OpenAI GPT extraction + Pinecone embedding writes
│   ├── pipeline/        # Orchestrator + handlers (job posting, worker goal, unknown)
│   ├── jobs/            # Job posting domain (models, repository)
│   ├── work_goals/      # Worker goal domain (models, repository)
│   ├── matches/         # Semantic match results
│   ├── users/           # User domain
│   ├── temporal/        # Temporal client, worker, cron schedules
│   ├── metrics.py       # Prometheus gauges/counters
│   └── models.py        # Shared SQLModel base classes
├── migrations/          # Alembic revision scripts
├── tests/               # Pytest (async mode) suite
├── infra/               # Pulumi-on-GKE stack (Python)
├── docs/                # ARCHITECTURE, CONFIGURATION, DEPLOYMENT, DEVELOPMENT, GETTING-STARTED, TESTING
├── grafana/             # Dashboard + datasource provisioning
├── jaeger/              # Jaeger collector / query configs
├── prometheus/          # Prometheus scrape config
├── docker-compose.yml   # Local dev stack
├── Dockerfile           # Multi-stage production image (uv + python:3.12-slim)
├── alembic.ini
└── pyproject.toml
```

## Running Tests

```bash
uv run pytest
```

`pytest-asyncio` is configured in `auto` mode (see `pyproject.toml`), so async tests require no explicit marker. Coverage is available via `pytest-cov`.

See `docs/TESTING.md` for detailed testing guidance.

## Linting and Formatting

Ruff is the single source of truth for lint and format:

```bash
uv run ruff check --fix src tests
uv run ruff format src tests
```

Configuration lives in `pyproject.toml` under `[tool.ruff]` (target `py312`, rules `E`, `F`, `I`).

## Documentation

| Document                                             | Description                                   |
|------------------------------------------------------|-----------------------------------------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)         | System architecture and component overview   |
| [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)   | First-run walkthrough                         |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)           | Local development workflow                   |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md)       | Environment variables and settings           |
| [docs/TESTING.md](docs/TESTING.md)                   | Test framework and conventions                |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)             | Deployment and infrastructure                |
| [AGENTS.md](AGENTS.md)                               | FastAPI conventions for contributors          |
| [CONTRIBUTING.md](CONTRIBUTING.md)                   | Contribution guidelines                       |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines, and [AGENTS.md](AGENTS.md) for the FastAPI coding conventions this project follows (async route rules, domain-oriented layout, Pydantic settings-per-domain, etc.).

## License

Vici is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full text.
