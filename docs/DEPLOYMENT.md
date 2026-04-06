<!-- generated-by: gsd-doc-writer -->
# Deployment

Vici deploys to **Google Cloud (GKE Autopilot)** via Pulumi infrastructure-as-code. Local development uses Docker Compose.

## Deployment Targets

| Target | Config | Status |
|--------|--------|--------|
| GKE via Pulumi | `infra/` | Production infrastructure |
| Docker Compose | `docker-compose.yml` | Local development |

### GKE (Pulumi)

Infrastructure for GKE-based deployment is managed under `infra/` using Pulumi with a Python runtime. Three environments are configured:

| Environment | GCP Project | Cluster Name | Region |
|-------------|-------------|--------------|--------|
| dev | `vici-app-dev` | `vici-dev` | `us-central1` |
| staging | `vici-app-staging` | `vici-staging` | `us-central1` |
| prod | `vici-app-prod` | `vici-prod` | `us-central1` |

Pulumi components provision:

- **GKE Autopilot cluster** (`infra/components/cluster.py`) with Workload Identity and Cloud DNS
- **Artifact Registry** (`infra/components/registry.py`) for Docker images at `us-central1-docker.pkg.dev/<project>/vici-images/`
- **Cloud SQL** (`infra/components/database.py`) for application and Temporal databases
- **External Secrets Operator** (`infra/components/secrets.py`) with GCP Secret Manager
- **IAM identities** (`infra/components/identity.py`) including a CI push service account and Workload Identity binding
- **Kubernetes namespaces** (`infra/components/namespaces.py`)
- **Temporal Server** (`infra/components/temporal.py`) via Helm in dedicated namespace
- **OpenSearch** (`infra/components/opensearch.py`) for Temporal visibility

Pulumi state is stored in a GCS bucket (`gs://vici-app-pulumi-state-dev` by default; CI overrides via `PULUMI_BACKEND_URL`).

## Docker

The `Dockerfile` uses a multi-stage build:

1. **Builder stage** -- installs production dependencies with `uv sync --frozen --no-dev`
2. **Runtime stage** -- copies the virtualenv, application source (`src/`), migrations, and `alembic.ini`; runs as a non-root `appuser`

The container runs Uvicorn on port 8000:

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

A healthcheck probes `http://localhost:8000/health` every 30 seconds.

## Build Pipeline

### CI (GitHub Actions)

The CI workflow (`.github/workflows/ci.yml`) runs on pushes and pull requests to `main`:

1. Checkout code
2. Set up `uv` with caching (`astral-sh/setup-uv@v5`)
3. Install dependencies: `uv sync --frozen`
4. Lint: `uv run ruff check src/ tests/`
5. Test: `uv run pytest tests/ -x --tb=short -q` (using SQLite for CI)

## Environment Setup

Production environment variables are managed via GCP Secret Manager and delivered to pods through External Secrets Operator. See [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference.

Key required variables for production:

- `DATABASE_URL` -- Cloud SQL connection string via Auth Proxy sidecar
- `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER` -- SMS integration
- `OPENAI_API_KEY` -- LLM services
- `PINECONE_API_KEY`, `PINECONE_INDEX_HOST` -- vector search
- `BRAINTRUST_API_KEY` -- evaluation/observability
- `OTEL_EXPORTER_OTLP_ENDPOINT` -- OpenTelemetry trace export
- `ENV` -- environment name (`dev`, `staging`, `production`)

## Rollback Procedure

### GKE

For GKE deployments managed by Pulumi, roll back by redeploying a previous Docker image tag:

```bash
# From the infra/ directory, target the desired environment
pulumi stack select <env>
pulumi up
```

Alternatively, use `kubectl` to set the previous container image directly on the deployment.

## Monitoring

The application uses OpenTelemetry and Prometheus for observability:

- **OpenTelemetry** -- traces are exported via OTLP (`opentelemetry-exporter-otlp`). FastAPI and SQLAlchemy are auto-instrumented (`opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`).
- **Prometheus** -- metrics are exposed via `prometheus-fastapi-instrumentator`.

### Local Observability Stack

The `docker-compose.yml` includes a full local observability stack:

| Service | Port | Purpose |
|---------|------|---------|
| Jaeger Collector | 4317, 4318 | OTLP trace ingestion |
| Jaeger Query UI | 16686 | Trace visualization |
| OpenSearch | 9200 | Trace storage backend |
| Prometheus | 9090 | Metrics collection |
| Grafana | 3000 | Metrics dashboards |

Grafana provisioning configuration lives in `grafana/provisioning/` and Prometheus scrape config in `prometheus/prometheus.yml`.
