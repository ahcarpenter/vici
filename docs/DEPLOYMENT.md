<!-- generated-by: gsd-doc-writer -->
# Deployment

Vici deploys to **Google Cloud (GKE)** using Pulumi infrastructure-as-code. Local development uses Docker Compose.

## Deployment Targets

| Target | Config | Status |
|--------|--------|--------|
| Docker Compose | `docker-compose.yml` | Local development |
| GKE via Pulumi | `infra/` | Production infrastructure (dev, staging, prod) |

## GKE (Pulumi)

Infrastructure for GKE-based deployment is managed under `infra/` using Pulumi with a Python runtime. Three environments are configured:

| Environment | GCP Project | Cluster Name | Region |
|-------------|-------------|--------------|--------|
| dev | `vici-app-dev` | `vici-dev` | `us-central1` |
| staging | `vici-app-staging` | `vici-staging` | `us-central1` |
| prod | `vici-app-prod` | `vici-prod` | `us-central1` |

Pulumi components provision:

- **GKE Autopilot cluster** (`infra/components/cluster.py`) with Workload Identity and Cloud DNS
- **Cloud SQL PostgreSQL 16** (`infra/components/database.py`) -- separate instances for the app and Temporal, VPC peering with private IP, regional HA in prod
- **Artifact Registry** (`infra/components/registry.py`) for Docker images at `us-central1-docker.pkg.dev/<project>/vici-images/`
- **IAM identities** (`infra/components/identity.py`) including a CI push service account and Workload Identity binding
- **Kubernetes namespaces** (`infra/components/namespaces.py`) -- `vici`, `observability`, `temporal`
- **External Secrets Operator** (`infra/components/secrets.py`) -- syncs secrets from GCP Secret Manager to K8s Secrets
- **Temporal** (`infra/components/temporal.py`) -- Helm release with PostgreSQL persistence and OpenSearch visibility
- **Observability** -- OpenSearch (`infra/components/opensearch.py`), Jaeger (`infra/components/jaeger.py`), Prometheus + Grafana (`infra/components/prometheus.py`)
- **Ingress + TLS** (`infra/components/ingress.py`, `infra/components/certmanager.py`) -- cert-manager with Let's Encrypt issuers
- **App Deployment** (`infra/components/app.py`) -- FastAPI with Cloud SQL Auth Proxy sidecar, HPA (1-3 replicas), health checks, resource limits

Pulumi state is stored in a GCS bucket (`gs://vici-app-pulumi-state-dev` by default; CI overrides via `PULUMI_BACKEND_URL`).

## Docker

The `Dockerfile` uses a multi-stage build:

1. **Builder stage** -- installs production dependencies with `uv sync --frozen --no-dev`
2. **Runtime stage** -- copies the virtualenv, application source (`src/`), migrations, and `alembic.ini`; runs as a non-root `appuser`

The container runs Uvicorn on port 8000:

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

A healthcheck probes `http://localhost:8000/health` every 30 seconds. In Docker Compose, the `app` service runs Alembic migrations before starting the server. In GKE, migrations run as a separate Kubernetes Job before the app Deployment.

## Build Pipeline

### CI (GitHub Actions)

The CI workflow (`.github/workflows/ci.yml`) runs on pushes and pull requests to `main`:

1. Checkout code
2. Set up `uv` with caching (`astral-sh/setup-uv@v5`)
3. Install dependencies: `uv sync --frozen`
4. Lint: `uv run ruff check src/ tests/`
5. Test: `uv run pytest tests/ -x --tb=short -q` (using SQLite for CI)

### CD (GitHub Actions)

The CD pipeline (`.github/workflows/cd-base.yml` reusable workflow) handles deployment:

1. Authenticate to GCP via Workload Identity Federation (OIDC)
2. Configure Docker for Artifact Registry
3. Build and push Docker image (tagged with short SHA + stack name)
4. Install Pulumi and Python dependencies
5. Execute `pulumi up` (or `pulumi preview` for PRs)

Environment-specific triggers:

| Workflow | Trigger | Action |
|----------|---------|--------|
| `cd-dev.yml` | Push to `main` | `pulumi up` (auto-deploy) |
| `cd-staging.yml` | PR to `main` | `pulumi preview` (no changes) |
| `cd-staging.yml` | `workflow_dispatch` | `pulumi up` (manual deploy) |
| `cd-prod.yml` | `workflow_dispatch` | `pulumi up` (manual, requires approval) |

## Kubernetes Deployment Sequence

On `pulumi up`:

1. **Namespaces** -- `vici`, `observability`, `temporal`
2. **Secrets** -- ExternalSecrets pulls from GCP Secret Manager into K8s Secrets
3. **Database** -- Cloud SQL instances created with VPC peering
4. **Temporal** -- PostgreSQL schema job, then Temporal Helm release
5. **Observability** -- OpenSearch, Jaeger, Prometheus, Grafana
6. **App** -- Alembic migration K8s Job, then FastAPI Deployment (1-3 replicas with HPA)
7. **Ingress** -- cert-manager Issuer, TLS Certificate, Ingress with external load balancer

## Environment Setup

Production environment variables are managed via **GCP Secret Manager** and synced to Kubernetes Secrets by the External Secrets Operator. Key required variables:

- `DATABASE_URL` -- constructed from Cloud SQL instance connection details
- `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER` -- SMS integration
- `OPENAI_API_KEY` -- LLM services
- `PINECONE_API_KEY`, `PINECONE_INDEX_HOST` -- vector search
- `BRAINTRUST_API_KEY` -- evaluation/observability
- `OTEL_EXPORTER_OTLP_ENDPOINT` -- OpenTelemetry trace export
- `ENV` -- set to `production`

See [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference.

## Domain Setup

After a fresh GKE deployment:

1. Get the Ingress external IP: `pulumi stack output ingress_external_ip`
2. Add an A record in DNS (e.g., `dev.usevici.com` pointing to the IP)
3. Wait for DNS propagation (5-30 min depending on TTL)
4. Verify HTTPS: `curl -I https://dev.usevici.com`

## Rollback Procedure

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
