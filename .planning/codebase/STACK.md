# Technology Stack

**Analysis Date:** 2026-04-22

---

## Languages

**Primary:**
- Python 3.12 — all application and infrastructure code
  - `pyproject.toml`: `requires-python = ">=3.12"`
  - `.venv/pyvenv.cfg`: `version_info = 3.12.7`
  - **Flag:** No `.python-version` file at repo root; runtime version is implicit from venv only.

**Secondary:**
- YAML — Kubernetes manifests, GitHub Actions, Helm values (via Pulumi Python dicts)
- SQL — Alembic migrations in `migrations/versions/`

---

## Runtime

**Environment:**
- CPython 3.12.7 (local venv via homebrew `python@3.12`)
- GKE Autopilot (us-central1) in production

**Package Manager:**
- `uv` (Astral) — `uv sync --frozen` enforced in CI and Dockerfile
- Lockfile: `uv.lock` present at repo root (committed). `infra/uv.lock` present for infra sub-project.

**Container base image:**
- `python:3.12-slim` (Dockerfile lines 2, 11)
- `ghcr.io/astral-sh/uv:latest` copied into builder and runtime stages — **unpinned tag**; breaks reproducibility if Astral pushes a breaking change.

---

## Frameworks

**Core Web:**
- `fastapi 0.135.1` (`pyproject.toml` lower bound `>=0.135.1`; lockfile resolves to `0.135.1`) — async API framework
- `uvicorn[standard] 0.41.0` — ASGI server

**ORM / Database:**
- `sqlmodel 0.0.37` — SQLModel (SQLAlchemy + Pydantic hybrid)
- `sqlalchemy 2.0.48` — async engine (`create_async_engine`), `src/database.py`
- `alembic 1.18.4` — migrations, `alembic.ini`, `migrations/`

**Workflow Orchestration:**
- `temporalio 1.24.0` — Temporal Python SDK; worker in `src/temporal/worker.py`

**Validation / Settings:**
- `pydantic 2.12.5` — data models
- `pydantic-settings 2.13.1` — env-driven config, `src/config.py`

**Testing:**
- `pytest 9.0.2` + `pytest-asyncio 1.3.0` — async test runner
- `pytest-cov 7.0.0` — coverage
- `httpx 0.28.1` + `ASGITransport` — async test client

**Build/Dev:**
- `ruff 0.15.5` — linting (`E`, `F`, `I` rules) and formatting; configured in `pyproject.toml`

---

## Key Dependencies

| Package | Pinned in lockfile | `pyproject.toml` lower bound | Notes |
|---|---|---|---|
| `fastapi` | `0.135.1` | `>=0.135.1` | Current |
| `sqlmodel` | `0.0.37` | `>=0.0.37` | Pre-1.0; API is not stable |
| `sqlalchemy` | `2.0.48` | (transitive) | Current 2.x |
| `alembic` | `1.18.4` | `>=1.18.4` | Current |
| `temporalio` | `1.24.0` | `>=1.24.0` | Current |
| `openai` | `2.26.0` | `>=1.0.0` | **Flag:** lower bound allows v1; actual installed is v2. Wide open range permits accidental downgrade. |
| `pinecone` | `8.1.0` | `>=8.1.0` | Used with `[asyncio]` extra |
| `twilio` | `9.10.2` | `>=9.10.2` | Current |
| `braintrust` | `0.8.0` | `>=0.0.100` | **Flag:** lower bound `0.0.100` is extremely old (pre-0.1); actual installed is `0.8.0`. The semver gap is meaningless but signals the pin was never updated from an initial placeholder. |
| `pydantic` | `2.12.5` | (transitive from pydantic-settings) | Current |
| `pydantic-settings` | `2.13.1` | `>=2.13.1` | Current |
| `structlog` | `25.5.0` | `>=25.5.0` | Current |
| `tenacity` | `9.1.4` | `>=8.0.0` | **Flag:** lower bound allows v8; lockfile installs v9. Wide range. |
| `uvicorn[standard]` | `0.41.0` | `>=0.41.0` | Current |
| `asyncpg` | `0.31.0` | `>=0.31.0` | Async Postgres driver |
| `psycopg2-binary` | `2.9.11` | `>=2.9.11` | Used by Alembic sync env only (`migrations/env.py`) |
| `greenlet` | `3.3.2` | `>=3.3.2` | Required by SQLAlchemy async bridge |
| `opentelemetry-api` | `1.40.0` | `>=1.40.0` | Full OTel suite (api, sdk, exporter-otlp, instrumentation-fastapi, instrumentation-sqlalchemy) |
| `prometheus-fastapi-instrumentator` | `7.1.0` | `>=7.1.0` | Exposes `/metrics` |
| `python-dotenv` | `1.2.2` | `>=1.2.2` | `.env` loading |
| `python-multipart` | `0.0.22` | `>=0.0.22` | Required for FastAPI form parsing (Twilio webhooks) |
| `aiosqlite` | (dev) | `>=0.22.1` | SQLite async driver for CI and tests |
| `httpx` | (dev) | `>=0.28.1` | Test HTTP client |
| `ruff` | (dev) | `>=0.15.5` | Linting/formatting |

---

## Infrastructure Dependencies (infra/)

**Pulumi program** (`infra/pyproject.toml`) — exact-pinned:

| Package | Pin |
|---|---|
| `pulumi` | `==3.229.0` |
| `pulumi-gcp` | `==9.18.0` |
| `pulumi-kubernetes` | `==4.28.0` |

`infra/requirements.txt` contains overlapping range-pinned entries (`>=x.y.z,<next-major`) that are redundant with `infra/pyproject.toml`. The two files must be kept in sync manually — a drift risk.

---

## Helm Charts (deployed via Pulumi)

| Chart | Version | Source file |
|---|---|---|
| `temporal` | `0.74.0` (= server `1.29.1`) | `infra/components/temporal.py:27` |
| `kube-prometheus-stack` | `69.8.2` | `infra/components/prometheus.py:15` |
| `opensearch` | `2.37.0` (pinned to 2.x — OpenSearch 3 breaks Temporal ES client) | `infra/components/opensearch.py:13` |
| `external-secrets` | `1.3.2` | `infra/components/secrets.py:13` |

---

## Container Images (static pins)

| Image | Pinned tag | Source file |
|---|---|---|
| `gcr.io/cloud-sql-connectors/cloud-sql-proxy` | `2.14.1` | `infra/components/app.py:17`, `infra/components/temporal.py:18` |
| `temporalio/admin-tools` | `1.29.1-tctl-1.18` | `infra/components/temporal.py:22` |
| `jaegertracing/jaeger` | `2.16.0` | `infra/components/jaeger.py:13`, `docker-compose.yml:27,41` |
| `curlimages/curl` | `8.7.1` | `infra/components/opensearch.py:23` |
| `temporalio/auto-setup` | `1.26.2` (docker-compose only) | `docker-compose.yml:73` |
| `temporalio/ui` | `latest` (**Flag: unpinned**) | `docker-compose.yml:88` |
| `opensearchproject/opensearch` | `2.19.4` (docker-compose only) | `docker-compose.yml:14` |
| `prom/prometheus` | `v3.1.0` (docker-compose only) | `docker-compose.yml:97` |
| `grafana/grafana` | `11.4.0` (docker-compose only) | `docker-compose.yml:110` |
| `python:3.12-slim` | floating patch (no digest pin) | `Dockerfile:2,11` |
| `ghcr.io/astral-sh/uv` | `latest` (**Flag: unpinned**) | `Dockerfile:4,14` |

**Version skew flag:** `docker-compose.yml` runs `temporalio/auto-setup:1.26.2` (Temporal server 1.26) while production Helm deploys server 1.29.1. This 3-minor-version gap means local dev runs a different Temporal server than production.

---

## Configuration

**Environment:**
- Loaded from `.env` file (local) or GCP Secret Manager via External Secrets Operator (production)
- `src/config.py` — `Settings(BaseSettings)` with fail-fast `model_validator` at startup
- Required vars: `DATABASE_URL`, `TWILIO_AUTH_TOKEN`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `TEMPORAL_ADDRESS`, `WEBHOOK_BASE_URL`, `ENV`
- Optional: `BRAINTRUST_API_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `GIT_SHA`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER`

**Build:**
- `pyproject.toml` — Python deps, ruff config, pytest config
- `Dockerfile` — two-stage build (builder + runtime)
- `alembic.ini` — migration config; `file_template` uses date-slug format

**CI:**
- `.github/workflows/ci.yml` — lint, format-check, pytest on every push/PR to `main`
- **Flag:** `ci.yml` env block (lines 34–35) includes `INNGEST_DEV` and `INNGEST_BASE_URL`, which are stale references to a removed Inngest integration. No current code consumes these vars.
- **Flag:** `ci.yml` does not set `TEMPORAL_ADDRESS` or `ENV`; both are provided via `tests/conftest.py:50–51` `os.environ.setdefault` fallbacks, making the CI env block an incomplete representation of test requirements.

---

## Platform Requirements

**Development:**
- Python 3.12 (no `.python-version` file; must be installed externally)
- `uv` for dependency management
- Docker + Docker Compose for local full-stack

**Production:**
- GKE Autopilot cluster (us-central1), `infra/components/cluster.py`
- GCP Project per environment: `vici-app-dev`, `vici-app-staging`, `vici-app-prod`
- Pulumi state stored in GCS: `gs://vici-app-pulumi-state-{env}`
- GCP Secret Manager for all secrets, synced to K8s via External Secrets Operator
- GCP Artifact Registry for container images (`us-central1-docker.pkg.dev`)

---

*Stack analysis: 2026-04-22*
