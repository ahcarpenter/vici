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

Values above are sourced from `infra/Pulumi.{dev,staging,prod}.yaml`. The GKE release channel is `REGULAR` for dev/staging and `STABLE` for prod (see `infra/components/cluster.py`). Cluster `deletion_protection` is enabled, and `vertical_pod_autoscaling`, `node_config`, `node_pool`, and `initial_node_count` are excluded from drift detection because GKE Autopilot mutates them post-creation.

Pulumi components provision (see `infra/__main__.py` for the full import list):

- **GKE Autopilot cluster** (`infra/components/cluster.py`) — Regional location, Workload Identity pool `<project>.svc.id.goog`, explicit DNS config (`CLOUD_DNS` / `CLUSTER_SCOPE` / `cluster.local`), `ip_allocation_policy` left empty so GKE allocates pod/service CIDRs automatically
- **Cloud SQL PostgreSQL 16** (`infra/components/database.py`) — two instances per environment: `vici-app-<env>` and `vici-temporal-<env>`; tier `db-g1-small`, 10 GB `PD_SSD`, private IP via VPC peering on `servicenetworking.googleapis.com` (CIDR prefix length 16), backups disabled in dev and enabled in staging/prod, `REGIONAL` HA only for the prod app DB (all others `ZONAL`). Databases created: `vici` on the app instance; `temporal` and `temporal_visibility` on the temporal instance.
- **Artifact Registry** (`infra/components/registry.py`) — Docker repository `vici-images` at `us-central1-docker.pkg.dev/<project>/vici-images`; CI service account granted `roles/artifactregistry.writer`
- **Identity and IAM** (`infra/components/identity.py`, `infra/components/iam.py`) — CI push service account, app Google Service Account, Workload Identity bindings, and Kubernetes ServiceAccounts (`vici-app`, `temporal-app`)
- **CI / Workload Identity Federation** (`infra/components/cd.py`) — WIF pool and provider for GitHub Actions OIDC authentication
- **Kubernetes namespaces** (`infra/components/namespaces.py`) — `vici`, `temporal`, `observability`, `cert-manager`, `external-secrets`. The shared `k8s_provider` builds its kubeconfig using `gke-gcloud-auth-plugin`, which must be installed locally (`gcloud components install gke-gcloud-auth-plugin`).
- **External Secrets Operator** (`infra/components/secrets.py`) — Helm chart `external-secrets` v1.3.2 from `https://charts.external-secrets.io`; provisions `Secret` resources in GCP Secret Manager (named `<env>-<slug>`), namespace-scoped `SecretStore` CRs with Workload Identity auth in the `vici`, `temporal`, and `observability` namespaces, and `ExternalSecret` CRs with a 1h refresh interval
- **Database migrations** (`infra/components/migration.py`) — Alembic Kubernetes `Job` (`alembic-migration-<env>`) with a Cloud SQL Auth Proxy native sidecar init container; runs `uv run alembic upgrade head` with `backoffLimit: 0` (fail fast) and `ttlSecondsAfterFinished: 300`
- **Temporal** (`infra/components/temporal.py`) — Helm release with PostgreSQL persistence and OpenSearch visibility, preceded by a schema migration job
- **Observability** — OpenSearch (`infra/components/opensearch.py`), Jaeger collector + query (`infra/components/jaeger.py`), kube-prometheus-stack v69.8.2 with a FastAPI `ServiceMonitor` and sidecar-provisioned FastAPI and Temporal Grafana dashboards (`infra/components/prometheus.py`). Prometheus retention is 15 days, storage 10 GiB. Alertmanager is disabled for v1. Node-level scrape targets (node-exporter, kube-proxy, kube-controller-manager, kube-scheduler, kube-etcd, core-dns, kube-dns) are disabled because GKE Autopilot does not permit node-level access.
- **cert-manager** (`infra/components/certmanager.py`) — Helm chart `cert-manager` v1.20.0 from `https://charts.jetstack.io`, with CRDs enabled, installed in the `cert-manager` namespace
- **Ingress + TLS** (`infra/components/ingress.py`) — `letsencrypt-staging` and `letsencrypt-prod` Issuers in the `vici` namespace; GKE Ingress (annotation `kubernetes.io/ingress.class: gce`) with a placeholder TLS secret to break the cert-manager chicken-and-egg
- **App Deployment** (`infra/components/app.py`) — FastAPI Deployment with a Cloud SQL Auth Proxy native sidecar (image `gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1`), HPA (1–3 replicas, 70% CPU target), readiness probe on `/readyz` (initial delay 15s, period 10s), liveness probe on `/health` (initial delay 30s, period 30s), ClusterIP service on port 8000

**Pulumi backend.** State is stored in a GCS bucket. `infra/Pulumi.yaml` sets a default of `gs://vici-app-pulumi-state-dev`; CI overrides this per environment in `.github/workflows/cd-base.yml` via `PULUMI_BACKEND_URL=gs://vici-app-pulumi-state-${{ inputs.stack }}`. <!-- VERIFY: staging and prod GCS state buckets (gs://vici-app-pulumi-state-staging, gs://vici-app-pulumi-state-prod) exist and match the cd-base.yml naming convention -->

## Docker

The `Dockerfile` uses a multi-stage build based on `python:3.12-slim`:

1. **Builder stage** — installs `uv` from `ghcr.io/astral-sh/uv:latest` and runs `uv sync --frozen --no-dev` against the committed `pyproject.toml` and `uv.lock`
2. **Runtime stage** — copies the built virtualenv, application source (`src/`), `migrations/`, and `alembic.ini`; installs `curl` for the healthcheck; runs as a non-root `appuser`

The container runs Uvicorn on port 8000:

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

A `HEALTHCHECK` probes `http://localhost:8000/health` every 30 seconds (timeout 5s, start period 10s, 3 retries). In Docker Compose, the `app` service runs Alembic migrations before starting the server (with `--reload` enabled in compose for local dev). In GKE, migrations run as a separate Kubernetes `Job` (`alembic-migration-<env>`) before the app `Deployment`.

## Build Pipeline

### CI (GitHub Actions)

The CI workflow (`.github/workflows/ci.yml`) runs on pushes and pull requests to `main`:

1. Checkout code (`actions/checkout@v4`)
2. Set up `uv` with caching (`astral-sh/setup-uv@v5`)
3. Install dependencies: `uv sync --frozen`
4. Lint: `uv run ruff check src/ tests/`
5. Test: `uv run pytest tests/ -x --tb=short -q` using SQLite (`DATABASE_URL=sqlite+aiosqlite:///./test.db`) with synthetic values for required Twilio, OpenAI, Pinecone, Braintrust, Inngest, and webhook env vars (see the `env:` block of `ci.yml` for the full list)

### CD (GitHub Actions)

The CD pipeline (`.github/workflows/cd-base.yml` reusable workflow) handles deployment:

1. Authenticate to GCP via Workload Identity Federation (`google-github-actions/auth@v3`, consuming the `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` secrets passed by the caller workflow)
2. Configure Docker for Artifact Registry: `gcloud auth configure-docker us-central1-docker.pkg.dev --quiet`
3. Build and push Docker image, tagged with both the short SHA and the stack name: `us-central1-docker.pkg.dev/<project>/vici-images/vici:<sha>` and `:<stack>` (build+push step runs only when `command == 'up'`)
4. Set up `uv` with caching (`astral-sh/setup-uv@v5`)
5. Install Pulumi dependencies: `cd infra && uv sync --frozen`
6. Execute `pulumi up` (or `pulumi preview` for PRs) via `pulumi/actions@v6` with `work-dir: infra`, `PULUMI_CONFIG_PASSPHRASE`, and `PULUMI_BACKEND_URL=gs://vici-app-pulumi-state-<stack>`

The job requests `permissions: contents: read, id-token: write` and runs on `ubuntu-latest`. When the caller workflow passes an `environment` input (prod does), the job runs under that GitHub Environment.

Environment-specific triggers:

| Workflow | Trigger | Action |
|----------|---------|--------|
| `cd-dev.yml` | Push to `main` | `pulumi up` (auto-deploy to `dev` stack) |
| `cd-staging.yml` | PR to `main` | `pulumi preview` against `staging` stack |
| `cd-staging.yml` | `workflow_dispatch` | `pulumi up` against `staging` stack |
| `cd-prod.yml` | `workflow_dispatch` | `pulumi up` against `prod` stack, `environment: prod` |

The following GitHub repository secrets must be configured for CD to run (referenced by the caller workflows in `.github/workflows/cd-{dev,staging,prod}.yml`):

- `GCP_WIF_PROVIDER_{DEV,STAGING,PROD}` — Workload Identity Provider resource names (passed into cd-base.yml as `WIF_PROVIDER`)
- `GCP_CI_SA_{DEV,STAGING,PROD}` — CI push service account emails (passed into cd-base.yml as `WIF_SERVICE_ACCOUNT`)
- `PULUMI_CONFIG_PASSPHRASE` — shared Pulumi config passphrase used to decrypt `Pulumi.<stack>.yaml` secure values

<!-- VERIFY: GitHub Environment "prod" is configured with required reviewers / protection rules for manual approval gating -->

## Kubernetes Deployment Sequence

On `pulumi up`, Pulumi builds a DAG from `depends_on` edges declared in each component. The effective ordering is:

1. **Cluster** — GKE Autopilot cluster (`vici-<env>`)
2. **Namespaces** — `vici`, `temporal`, `observability`, `cert-manager`, `external-secrets`
3. **Databases** — VPC peering (global address + servicenetworking connection), Cloud SQL `vici-app-<env>` and `vici-temporal-<env>`, plus the `vici`, `temporal`, and `temporal_visibility` databases
4. **IAM** — Google Service Accounts, Workload Identity bindings, Kubernetes ServiceAccounts (`vici-app`, `temporal-app`, `observability-app`)
5. **Registry** — Artifact Registry `vici-images` with CI writer IAM
6. **Secrets** — GCP Secret Manager secrets, External Secrets Operator Helm release, `SecretStore` and `ExternalSecret` CRs
7. **cert-manager** — Helm release, `letsencrypt-staging` and `letsencrypt-prod` Issuers
8. **Temporal** — schema migration Job, then Temporal Helm release
9. **Observability** — OpenSearch, Jaeger, kube-prometheus-stack, FastAPI `ServiceMonitor`, Grafana dashboard ConfigMaps
10. **Migration Job** — `alembic-migration-<env>` runs `alembic upgrade head`
11. **App** — FastAPI `Deployment` (1–3 replicas), ClusterIP `Service`, HPA
12. **Ingress** — placeholder TLS Secret, GKE `Ingress`, `webhook-base-url` Secret Manager SecretVersion update

## Environment Setup

Production environment variables are managed via **GCP Secret Manager** and synced to Kubernetes Secrets by the External Secrets Operator. Each secret is stored in Secret Manager as `<env>-<slug>` with automatic replication, and exposed to the app container via `envFrom: secretRef:`. The `_SECRET_DEFINITIONS` list in `infra/components/secrets.py` defines 11 secrets; all 11 are mounted into the app container via `_ENV_FROM_SOURCES` in `infra/components/app.py`:

- `twilio-auth-token`, `twilio-account-sid`, `twilio-from-number` — Twilio SMS integration
- `openai-api-key` — OpenAI LLM services
- `pinecone-api-key`, `pinecone-index-host` — Pinecone vector search
- `braintrust-api-key` — Braintrust evaluation/observability
- `database-url` — Cloud SQL connection string (uses the Unix socket at `/cloudsql/<connection-name>` exposed by the Auth Proxy sidecar)
- `temporal-address` — Temporal frontend address
- `otel-exporter-otlp-endpoint` — OpenTelemetry trace export endpoint
- `webhook-base-url` — `https://<app_hostname>`, written by Pulumi after the Ingress is provisioned (`infra/components/ingress.py` creates a `SecretVersion` whose value is `https://` concatenated with `APP_HOSTNAME`)

Each `ExternalSecret` maps the Secret Manager entry to a K8s `Secret` in the `vici` namespace with the same name as the slug; the `secretKey` inside the synced K8s Secret is the slug uppercased with dashes replaced by underscores (e.g., `twilio-auth-token` -> `TWILIO_AUTH_TOKEN`).

The `ENV` variable is injected directly by Pulumi from the stack name (`dev`, `staging`, or `prod`). See [CONFIGURATION.md](CONFIGURATION.md) for the full variable reference.

<!-- VERIFY: all 11 Secret Manager secret values are populated in each GCP project (vici-app-dev, vici-app-staging, vici-app-prod) prior to first deploy — Pulumi creates the Secret resources but not the SecretVersions -->

### Resource Limits

The `vici-app` container requests 250m CPU / 512Mi memory and limits at 500m CPU / 1Gi memory. The Cloud SQL Auth Proxy sidecar requests 100m CPU / 256Mi memory and limits at 200m CPU / 512Mi memory. The HPA scales between 1 and 3 replicas based on 70% CPU utilization.

## Domain Setup

After a fresh GKE deployment (full runbook in `infra/DOMAIN-SETUP.md`):

1. Get the Ingress external IP: `pulumi stack output ingress_external_ip` (from `infra/`). If it returns `PENDING`, check `kubectl get ingress vici-ingress -n vici`.
2. Get the target hostname: `pulumi stack output app_hostname`
3. Add an A record in Squarespace DNS (**Domains > usevici.com > DNS Settings > Custom Records**) pointing the host (`dev`, `staging`, or `@` for apex) to the Ingress IP. Squarespace does not support apex CNAMEs, so A records are required for `usevici.com`.
4. Wait for DNS propagation (5–30 min depending on TTL); verify with `dig <hostname> +short`
5. Verify HTTPS: `curl -I https://<hostname>`

<!-- VERIFY: current A records for dev.usevici.com / staging.usevici.com / usevici.com in Squarespace DNS -->

### TLS Certificates

The Ingress is annotated with `cert-manager.io/issuer: letsencrypt-prod` in `infra/components/ingress.py`, but a `letsencrypt-staging` Issuer is also provisioned (both Issuers are namespace-scoped to `vici` and use HTTP-01 solvers against the `vici-ingress`). The recommended bootstrap sequence is to initially point the Ingress at `letsencrypt-staging` (untrusted CA, higher rate limits), verify ACME HTTP-01 challenges succeed, then switch to `letsencrypt-prod` and delete the existing `vici-tls` Certificate so cert-manager re-issues with the production CA. ACME email is hard-coded to `ops@usevici.com`. ACME servers used: `https://acme-staging-v02.api.letsencrypt.org/directory` (staging) and `https://acme-v02.api.letsencrypt.org/directory` (prod).

## Rollback Procedure

For GKE deployments managed by Pulumi, rollback options:

1. **Revert the commit and redeploy** (preferred) — Revert the offending change on `main`; `cd-dev.yml` auto-deploys. For staging/prod, re-run the workflow via `workflow_dispatch`.
2. **Re-tag a previous image** — CI tags images with both the short SHA and the stack name. To force a previous image version, update the Deployment image tag:
   ```bash
   kubectl set image deployment/vici-app \
     vici-app=us-central1-docker.pkg.dev/<project>/vici-images/vici:<previous-sha> \
     -n vici
   ```
   Note this is transient — the next `pulumi up` will reset the image back to the `<stack>` tag written by `infra/components/app.py`.
3. **Roll back infrastructure** — From `infra/`: `pulumi stack select <env>`, then `pulumi stack history` to identify a previous state, and `pulumi stack export` / `pulumi stack import` to revert state if necessary.

<!-- VERIFY: production rollback runbook / incident response process — no runbook currently lives in the repo beyond the steps above -->

## Monitoring

The application uses OpenTelemetry and Prometheus for observability:

- **OpenTelemetry** — traces are exported via OTLP (`opentelemetry-exporter-otlp`). FastAPI and SQLAlchemy are auto-instrumented (`opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`). The exporter endpoint is provided via the `otel-exporter-otlp-endpoint` secret.
- **Prometheus** — metrics are exposed via `prometheus-fastapi-instrumentator` and scraped by the `fastapi-metrics` `ServiceMonitor` (port `http`, path `/metrics`, interval 30s) registered by `infra/components/prometheus.py` against services with label selector `app: vici` in the `vici` namespace.
- **In-cluster stack** — kube-prometheus-stack (Prometheus + Grafana, Alertmanager disabled) runs in the `observability` namespace with 15-day retention and a 10 GiB PVC; Jaeger collector and query run in the same namespace backed by OpenSearch. Grafana is pre-provisioned with a Jaeger datasource pointing at `http://jaeger-query.observability.svc.cluster.local:16686` and with FastAPI + Temporal dashboards loaded via sidecar ConfigMaps labeled `grafana_dashboard: "1"`.

<!-- VERIFY: external dashboards / alert routing (PagerDuty, Slack webhooks, Grafana Cloud, live Grafana URLs, on-call rotation) — Alertmanager is disabled in-cluster -->

### Local Observability Stack

The `docker-compose.yml` includes a full local observability stack:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| Jaeger Collector | `jaegertracing/jaeger:2.16.0` | 4317, 4318 | OTLP trace ingestion |
| Jaeger Query UI | `jaegertracing/jaeger:2.16.0` | 16686 | Trace visualization |
| OpenSearch | `opensearchproject/opensearch:2.19.4` | 9200 | Trace storage backend |
| Prometheus | `prom/prometheus:v3.1.0` | 9090 | Metrics collection |
| Grafana | `grafana/grafana:11.4.0` | 3000 | Metrics dashboards |

Grafana provisioning configuration lives in `grafana/provisioning/` and Prometheus scrape config in `prometheus/prometheus.yml`. Compose also runs `postgres:16`, `temporalio/auto-setup:1.26.2`, and `temporalio/ui:latest` alongside the observability services for a full local stack.
