<!-- generated-by: gsd-doc-writer -->
# Deployment

Vici deploys to **Google Cloud (GKE Autopilot)** using Pulumi infrastructure-as-code. Local development uses Docker Compose.

## Deployment Targets

| Target | Config | Status |
|--------|--------|--------|
| Docker Compose | `docker-compose.yml` | Local development |
| GKE via Pulumi | `infra/` | Production infrastructure (dev, staging, prod) |

## GKE (Pulumi)

Infrastructure for GKE-based deployment is managed under `infra/` using Pulumi with a Python runtime (virtualenv at `infra/.venv`, configured in `infra/Pulumi.yaml`). Three environments are configured:

| Environment | GCP Project | Cluster Name | Region | App Hostname |
|-------------|-------------|--------------|--------|--------------|
| dev | `vici-app-dev` | `vici-dev` | `us-central1` | `dev.usevici.com` |
| staging | `vici-app-staging` | `vici-staging` | `us-central1` | `staging.usevici.com` |
| prod | `vici-app-prod` | `vici-prod` | `us-central1` | `usevici.com` |

Values above are sourced from `infra/Pulumi.{dev,staging,prod}.yaml`. The GKE release channel is `REGULAR` for dev/staging and `STABLE` for prod (see `infra/components/cluster.py`). Cluster `deletion_protection` is enabled.

Pulumi components provision (see `infra/__main__.py` for the full registration order):

- **GKE Autopilot cluster** (`infra/components/cluster.py`) — Workload Identity pool `<project>.svc.id.goog`, Cloud DNS (`CLOUD_DNS` / `CLUSTER_SCOPE` / `cluster.local`), regional location
- **Cloud SQL PostgreSQL 16** (`infra/components/database.py`) — two instances per environment: `vici-app-<env>` and `vici-temporal-<env>`; tier `db-g1-small`, 10 GB `PD_SSD`, private IP via VPC peering (`servicenetworking.googleapis.com`), backups disabled in dev, enabled in staging/prod, `REGIONAL` HA only for the prod app DB
- **Artifact Registry** (`infra/components/registry.py`) — Docker repository `vici-images` at `us-central1-docker.pkg.dev/<project>/vici-images`; CI service account granted `roles/artifactregistry.writer`
- **Identity and IAM** (`infra/components/identity.py`, `infra/components/iam.py`) — CI push service account, app Google Service Account, Workload Identity bindings, and Kubernetes ServiceAccounts (`vici-app`, `temporal-app`)
- **CI / Workload Identity Federation** (`infra/components/cd.py`) — WIF pool and provider for GitHub Actions OIDC authentication
- **Kubernetes namespaces** (`infra/components/namespaces.py`) — `vici`, `temporal`, `observability`, `cert-manager`, `external-secrets`
- **External Secrets Operator** (`infra/components/secrets.py`) — Helm chart `external-secrets` v1.3.2 from `https://charts.external-secrets.io`; provisions `Secret` resources in GCP Secret Manager (named `<env>-<slug>`), namespace-scoped `SecretStore` CRs with Workload Identity auth, and `ExternalSecret` CRs with a 1h refresh interval
- **Database migrations** (`infra/components/migration.py`) — Alembic Kubernetes `Job` (`alembic-migration-<env>`) with a Cloud SQL Auth Proxy sidecar; runs `uv run alembic upgrade head`, `backoffLimit: 0`, TTL 300s after completion
- **Temporal** (`infra/components/temporal.py`) — Helm release with PostgreSQL persistence and OpenSearch visibility, preceded by a schema migration job
- **Observability** — OpenSearch (`infra/components/opensearch.py`), Jaeger collector + query (`infra/components/jaeger.py`), kube-prometheus-stack with a FastAPI ServiceMonitor (`infra/components/prometheus.py`)
- **Ingress + TLS** (`infra/components/ingress.py`, `infra/components/certmanager.py`) — cert-manager with Let's Encrypt staging and prod Issuers in the `vici` namespace; GKE Ingress (`ingress.class: gce`) with a placeholder TLS secret to break the cert-manager chicken-and-egg
- **App Deployment** (`infra/components/app.py`) — FastAPI Deployment with a Cloud SQL Auth Proxy native sidecar (image `gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1`), HPA (1–3 replicas, 70% CPU target), readiness probe on `/readyz`, liveness probe on `/health`, ClusterIP service on port 8000

**Pulumi backend.** State is stored in a GCS bucket (`gs://vici-app-pulumi-state-dev` is the default from `infra/Pulumi.yaml`; CI sets `PULUMI_BACKEND_URL=gs://vici-app-pulumi-state-<stack>` per environment in `.github/workflows/cd-base.yml`). <!-- VERIFY: staging and prod GCS state buckets exist and match the cd-base.yml naming convention -->

## Docker

The `Dockerfile` uses a multi-stage build based on `python:3.12-slim`:

1. **Builder stage** — installs `uv` from `ghcr.io/astral-sh/uv:latest` and runs `uv sync --frozen --no-dev`
2. **Runtime stage** — copies the built virtualenv, application source (`src/`), `migrations/`, and `alembic.ini`; installs `curl` for the healthcheck; runs as a non-root `appuser`

The container runs Uvicorn on port 8000:

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

A `HEALTHCHECK` probes `http://localhost:8000/health` every 30 seconds (timeout 5s, start period 10s, 3 retries). In Docker Compose, the `app` service runs Alembic migrations before starting the server. In GKE, migrations run as a separate Kubernetes `Job` (`alembic-migration-<env>`) before the app `Deployment`.

## Build Pipeline

### CI (GitHub Actions)

The CI workflow (`.github/workflows/ci.yml`) runs on pushes and pull requests to `main`:

1. Checkout code
2. Set up `uv` with caching (`astral-sh/setup-uv@v5`)
3. Install dependencies: `uv sync --frozen`
4. Lint: `uv run ruff check src/ tests/`
5. Test: `uv run pytest tests/ -x --tb=short -q` using SQLite (`DATABASE_URL=sqlite+aiosqlite:///./test.db`) with synthetic values for required Twilio / OpenAI / Pinecone / Braintrust env vars

### CD (GitHub Actions)

The CD pipeline (`.github/workflows/cd-base.yml` reusable workflow) handles deployment:

1. Authenticate to GCP via Workload Identity Federation (`google-github-actions/auth@v3`, using the `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` secrets)
2. Configure Docker for Artifact Registry: `gcloud auth configure-docker us-central1-docker.pkg.dev --quiet`
3. Build and push Docker image (tagged with both short SHA and stack name): `us-central1-docker.pkg.dev/<project>/vici-images/vici:<sha>` and `:<stack>`
4. Install Pulumi dependencies: `cd infra && uv sync --frozen`
5. Execute `pulumi up` (or `pulumi preview` for PRs) via `pulumi/actions@v6` with `work-dir: infra`, `PULUMI_CONFIG_PASSPHRASE`, and `PULUMI_BACKEND_URL=gs://vici-app-pulumi-state-<stack>`

Environment-specific triggers:

| Workflow | Trigger | Action |
|----------|---------|--------|
| `cd-dev.yml` | Push to `main` | `pulumi up` (auto-deploy to `dev` stack) |
| `cd-staging.yml` | PR to `main` | `pulumi preview` against `staging` stack |
| `cd-staging.yml` | `workflow_dispatch` | `pulumi up` against `staging` stack |
| `cd-prod.yml` | `workflow_dispatch` | `pulumi up` against `prod` stack, `environment: prod` (uses GitHub Environment protection rules) |

The following GitHub repository secrets must be configured for CD to run:

- `GCP_WIF_PROVIDER_{DEV,STAGING,PROD}` — Workload Identity Provider resource names
- `GCP_CI_SA_{DEV,STAGING,PROD}` — CI push service account emails
- `PULUMI_CONFIG_PASSPHRASE` — shared Pulumi config passphrase used to decrypt `Pulumi.<stack>.yaml` secure values

<!-- VERIFY: GitHub Environment "prod" is configured with required reviewers for manual approval -->

## Kubernetes Deployment Sequence

On `pulumi up`, Pulumi builds a DAG from `depends_on` edges declared in each component. The effective ordering is:

1. **Cluster** — GKE Autopilot cluster (`vici-<env>`)
2. **Namespaces** — `vici`, `temporal`, `observability`, `cert-manager`, `external-secrets`
3. **Databases** — VPC peering, Cloud SQL `vici-app-<env>` and `vici-temporal-<env>`
4. **IAM** — Google Service Accounts, Workload Identity bindings, Kubernetes ServiceAccounts
5. **Registry** — Artifact Registry `vici-images` with CI writer IAM
6. **Secrets** — GCP Secret Manager secrets, External Secrets Operator Helm release, `SecretStore` and `ExternalSecret` CRs
7. **cert-manager** — Helm release, `letsencrypt-staging` and `letsencrypt-prod` Issuers
8. **Temporal** — schema migration Job, then Temporal Helm release
9. **Observability** — OpenSearch, Jaeger, kube-prometheus-stack, FastAPI `ServiceMonitor`
10. **Migration Job** — `alembic-migration-<env>` runs `alembic upgrade head`
11. **App** — FastAPI `Deployment` (1–3 replicas), ClusterIP `Service`, HPA
12. **Ingress** — placeholder TLS Secret, GKE `Ingress` (`ingress.class: gce`), `webhook-base-url` SecretVersion update

## Environment Setup

Production environment variables are managed via **GCP Secret Manager** and synced to Kubernetes Secrets by the External Secrets Operator. Secrets are named `<env>-<slug>` in Secret Manager and exposed to the app container via `envFrom: secretRef:`. The full set from `infra/components/app.py`:

- `twilio-auth-token`, `twilio-account-sid`, `twilio-from-number` — Twilio SMS integration
- `openai-api-key` — OpenAI LLM services
- `pinecone-api-key`, `pinecone-index-host` — Pinecone vector search
- `braintrust-api-key` — Braintrust evaluation/observability
- `database-url` — Cloud SQL connection string (uses the Unix socket at `/cloudsql/<connection-name>` exposed by the Auth Proxy sidecar)
- `temporal-address` — Temporal frontend address
- `otel-exporter-otlp-endpoint` — OpenTelemetry trace export endpoint
- `webhook-base-url` — `https://<app_hostname>`, written by Pulumi after the Ingress is provisioned (`infra/components/ingress.py`)

The `ENV` variable is injected directly by Pulumi from the stack name (`dev`, `staging`, or `prod`). See [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference.

<!-- VERIFY: all 11 Secret Manager secrets are populated with real values in each GCP project prior to first deploy -->

### Resource Limits

The `vici-app` container requests 250m CPU / 512Mi memory and limits at 500m CPU / 1Gi memory. The Cloud SQL Auth Proxy sidecar requests 100m CPU / 256Mi memory and limits at 200m CPU / 512Mi memory. The HPA scales between 1 and 3 replicas based on 70% CPU utilization.

## Domain Setup

After a fresh GKE deployment (full runbook in `infra/DOMAIN-SETUP.md`):

1. Get the Ingress external IP: `pulumi stack output ingress_external_ip` (from `infra/`). If it returns `PENDING`, check `kubectl get ingress vici-ingress -n vici`.
2. Get the target hostname: `pulumi stack output app_hostname`
3. Add an A record in Squarespace DNS (**Domains > usevici.com > DNS Settings > Custom Records**) pointing the host (`dev`, `staging`, or `@` for apex) to the Ingress IP. Squarespace does not support apex CNAMEs, so A records are required for `usevici.com`.
4. Wait for DNS propagation (5–30 min depending on TTL); verify with `dig <hostname> +short`
5. Verify HTTPS: `curl -I https://<hostname>`

<!-- VERIFY: current A records for dev.usevici.com / staging.usevici.com / usevici.com in Squarespace -->

### TLS Certificates

The Ingress is annotated with `cert-manager.io/issuer: letsencrypt-prod` in `infra/components/ingress.py`, but a `letsencrypt-staging` Issuer is also provisioned. The recommended bootstrap sequence is to initially point the Ingress at `letsencrypt-staging` (untrusted CA, higher rate limits), verify ACME HTTP-01 challenges succeed, then switch to `letsencrypt-prod` and delete the existing `vici-tls` Certificate so cert-manager re-issues with the production CA. ACME email is hard-coded to `ops@usevici.com`.

## Rollback Procedure

For GKE deployments managed by Pulumi, rollback options:

1. **Revert the commit and redeploy** (preferred) — Revert the offending change on `main`; `cd-dev.yml` auto-deploys. For staging/prod, re-run the workflow via `workflow_dispatch`.
2. **Re-tag a previous image** — CI tags images with both the short SHA and the stack name. To force a previous image version, update the Deployment image tag:
   ```bash
   kubectl set image deployment/vici-app \
     vici-app=us-central1-docker.pkg.dev/<project>/vici-images/vici:<previous-sha> \
     -n vici
   ```
   Note this is transient — the next `pulumi up` will reset the image back to the `<stack>` tag.
3. **Roll back infrastructure** — From `infra/`: `pulumi stack select <env>`, then `pulumi stack history` to identify a previous state, and `pulumi stack export` / `pulumi stack import` to revert state if necessary.

<!-- VERIFY: production rollback runbook / incident response process -->

## Monitoring

The application uses OpenTelemetry and Prometheus for observability:

- **OpenTelemetry** — traces are exported via OTLP (`opentelemetry-exporter-otlp`). FastAPI and SQLAlchemy are auto-instrumented (`opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`). The exporter endpoint is provided via the `otel-exporter-otlp-endpoint` secret.
- **Prometheus** — metrics are exposed via `prometheus-fastapi-instrumentator` and scraped by the `fastapi_service_monitor` `ServiceMonitor` CR registered by `infra/components/prometheus.py` (selector `app: vici`).
- **In-cluster stack** — kube-prometheus-stack (Prometheus + Grafana + Alertmanager) runs in the `observability` namespace; Jaeger collector and query run in the same namespace backed by OpenSearch.

<!-- VERIFY: external dashboards / alert routing (PagerDuty, Slack webhooks, Grafana Cloud, etc.) -->

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
