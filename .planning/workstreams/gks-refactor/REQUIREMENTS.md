# Requirements: Vici GKE Migration

**Milestone:** v1.0 GKE Migration
**Workstream:** gks-refactor
**Created:** 2026-04-04
**Status:** Active

---

## Architecture Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IaC | Pulumi Python | Consistent with Python codebase |
| Cluster mode | GKE Autopilot | No node management |
| Region | us-central1 | Best Autopilot feature availability, cost, Twilio latency |
| Environments | dev, staging, prod — 1:1 mirrored | Same Pulumi program, env-specific stack configs |
| Ingress | GKE Ingress (GCP Load Balancer) | Native Autopilot integration, zero ops |
| TLS | cert-manager + Let's Encrypt | Universal, portable |
| App database | Cloud SQL PG16 per env | Replaces Render managed Postgres |
| Temporal database | Dedicated Cloud SQL PG16 per env | Isolation from app DB |
| ESO scope | Namespace-scoped `SecretStore` | Stricter RBAC per namespace |
| Cloud SQL connectivity | Auth Proxy native sidecar | GKE-native, IAM-authenticated |
| Identity | Workload Identity Federation | No static GCP credentials |
| Data migration | Start fresh | No Render → Cloud SQL pg_dump needed |
| Pulumi state | GCS backend | Team-safe, per-env state buckets |
| Container registry | Artifact Registry (us-central1) | GCP-native, IAM-integrated |
| OpenSearch | Shared instance per env (Jaeger + Temporal visibility) | Fewer resources; dual-use is supported |

---

## Milestone Requirements

### Infrastructure (INFRA)

- [ ] **INFRA-01**: Operator can run `pulumi up --stack dev` to provision a complete GKE Autopilot cluster in us-central1 from scratch
- [ ] **INFRA-02**: Pulumi program uses a single codebase with three stack configs (`Pulumi.dev.yaml`, `Pulumi.staging.yaml`, `Pulumi.prod.yaml`) — env differences are config values only
- [ ] **INFRA-03**: GKE cluster has Workload Identity enabled at cluster creation time
- [ ] **INFRA-04**: Pulumi cluster resource has `ignore_changes` guards on volatile GKE fields (dns_config, node_version) so `pulumi up` never proposes a cluster replacement
- [ ] **INFRA-05**: Pulumi state is stored in a GCS backend bucket (one bucket per environment, not local state)
- [ ] **INFRA-06**: All three environments (dev, staging, prod) have identical namespace layout: `vici`, `temporal`, `observability`, `cert-manager`, `external-secrets`
- [ ] **INFRA-07**: Artifact Registry repository exists in us-central1 and the CI service account has push access

### Database (DB)

- [ ] **DB-01**: Each environment has a dedicated Cloud SQL PostgreSQL 16 instance for the Vici app with private IP in the same VPC as the GKE cluster
- [ ] **DB-02**: Each environment has a separate dedicated Cloud SQL PostgreSQL 16 instance for Temporal (databases: `temporal`, `temporal_visibility`)
- [ ] **DB-03**: Cloud SQL Auth Proxy native sidecar annotation is configured on the `vici` app ServiceAccount; app pods connect to Cloud SQL via Unix socket (`/cloudsql/PROJECT:REGION:INSTANCE`)
- [ ] **DB-04**: Alembic migration runs as a Kubernetes Job before the app Deployment is applied in every environment; Job must complete successfully before the app Deployment proceeds
- [ ] **DB-05**: `DATABASE_URL` secret uses the Cloud SQL Auth Proxy socket format (`postgresql+asyncpg:///vici?host=/cloudsql/PROJECT:REGION:INSTANCE`)

### Secrets (SECRETS)

- [ ] **SECRETS-01**: All external secrets (TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID, TWILIO_FROM_NUMBER, OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_HOST, BRAINTRUST_API_KEY, DATABASE_URL, TEMPORAL_HOST, OTEL_EXPORTER_OTLP_ENDPOINT, WEBHOOK_BASE_URL) are stored in GCP Secret Manager with environment-scoped names (e.g., `dev/twilio-auth-token`)
- [ ] **SECRETS-02**: External Secrets Operator is installed via Helm in the `external-secrets` namespace before any `ExternalSecret` CR is applied (enforced via Pulumi `depends_on`)
- [ ] **SECRETS-03**: Each namespace (`vici`, `temporal`, `observability`) has its own namespace-scoped `SecretStore` pointing at GCP Secret Manager
- [ ] **SECRETS-04**: `ExternalSecret` CRs are defined for every secret in each namespace; after `pulumi up`, all `ExternalSecret` resources show `Ready=True`
- [ ] **SECRETS-05**: GCP service accounts for each workload have only the minimum required IAM roles: `roles/secretmanager.secretAccessor` and `roles/cloudsql.client`

### Temporal (TEMPORAL)

- [ ] **TEMPORAL-01**: Temporal Server is deployed via the official `temporaltech/temporal` Helm chart in the `temporal` namespace, connected to the dedicated Cloud SQL instance
- [ ] **TEMPORAL-02**: Temporal uses OpenSearch (shared with Jaeger) for workflow visibility search; the Helm chart has bundled Elasticsearch disabled
- [ ] **TEMPORAL-03**: OpenSearch is deployed and its readiness probe is satisfied before Temporal's Helm release is applied (enforced via Pulumi `depends_on`)
- [ ] **TEMPORAL-04**: Temporal schema migration Jobs complete successfully before the Temporal server Deployment starts
- [ ] **TEMPORAL-05**: The `TEMPORAL_HOST` secret is set to `temporal-frontend.temporal.svc.cluster.local:7233` in all environments
- [ ] **TEMPORAL-06**: Temporal UI is accessible within the cluster (ClusterIP service); optionally exposed via Ingress for dev/staging

### Observability (OBS)

- [ ] **OBS-01**: OpenSearch is deployed in the `observability` namespace with `number_of_replicas: 0` on index templates (single-node safe)
- [ ] **OBS-02**: Jaeger v2 is deployed in the `observability` namespace connected to the in-cluster OpenSearch instance
- [ ] **OBS-03**: `kube-prometheus-stack` is deployed in the `observability` namespace; Prometheus scrapes the FastAPI `/metrics` endpoint via ServiceMonitor
- [ ] **OBS-04**: Grafana is provisioned with the existing FastAPI and Temporal dashboards (ported from `grafana/provisioning/` in docker-compose)
- [ ] **OBS-05**: `OTEL_EXPORTER_OTLP_ENDPOINT` secret points to the in-cluster Jaeger collector (`http://jaeger-collector.observability.svc.cluster.local:4317`)

### Application Workloads (APP)

- [ ] **APP-01**: FastAPI app Deployment runs in the `vici` namespace with Cloud SQL Auth Proxy native sidecar annotation and all secrets injected from `ExternalSecret`-generated Kubernetes Secrets
- [ ] **APP-02**: Temporal worker runs in the same pod as the FastAPI app (as a lifespan background task) and connects to in-cluster Temporal server
- [ ] **APP-03**: HPA is configured for the FastAPI Deployment (min 1, max 3 replicas; CPU target 70%)
- [ ] **APP-04**: GKE Ingress exposes the FastAPI app on an environment-specific public hostname with TLS terminated by cert-manager + Let's Encrypt
- [ ] **APP-05**: `GET /health` returns HTTP 200 from the GKE Ingress public hostname in all three environments
- [ ] **APP-06**: `WEBHOOK_BASE_URL` secret is set to the GKE Ingress public hostname (used by Twilio signature validation)

### CI/CD Pipeline (CD)

- [ ] **CD-01**: GitHub Actions CD job builds the Docker image, pushes to Artifact Registry, and runs `pulumi up --stack dev` on every push to `main`
- [ ] **CD-02**: GitHub Actions CD job runs `pulumi preview --stack staging` on every PR (no `pulumi up`); `pulumi up --stack staging` runs on explicit workflow dispatch
- [ ] **CD-03**: `pulumi up --stack prod` requires manual workflow dispatch with environment approval gate
- [ ] **CD-04**: Pulumi state access uses Workload Identity (GitHub Actions OIDC → GCP) — no static GCP service account key stored in GitHub secrets
- [ ] **CD-05**: CI test job is unchanged: `pytest` with SQLite, no GCP dependency


---

## Future Requirements (Post v1.0)

- Multi-region failover (secondary GKE cluster in us-east1)
- Temporal Cloud evaluation (replace self-hosted Temporal)
- GitOps with ArgoCD (replace direct `pulumi up` in CI)
- VPC Service Controls for stricter Cloud SQL network isolation
- GKE Gateway API (replace GKE Ingress for advanced routing)
- Separate OpenSearch instances for Jaeger and Temporal (better blast-radius isolation)

---

## Out of Scope

- Application code changes (`src/` is untouched)
- Dockerfile changes (image is already production-ready)
- CI test pipeline changes (tests remain SQLite-based)
- Multi-region or multi-cluster active-active setup
- GPU or specialty node configuration
- Payment processing or user auth (application feature, not infrastructure)

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Pending |
| INFRA-05 | Phase 1 | Pending |
| INFRA-06 | Phase 1 | Pending |
| INFRA-07 | Phase 1 | Pending |
| DB-01 | Phase 2 | Pending |
| DB-02 | Phase 2 | Pending |
| DB-03 | Phase 2 | Pending |
| DB-04 | Phase 2 | Pending |
| DB-05 | Phase 2 | Pending |
| SECRETS-01 | Phase 2 | Pending |
| SECRETS-02 | Phase 2 | Pending |
| SECRETS-03 | Phase 2 | Pending |
| SECRETS-04 | Phase 2 | Pending |
| SECRETS-05 | Phase 2 | Pending |
| TEMPORAL-01 | Phase 3 | Pending |
| TEMPORAL-02 | Phase 3 | Pending |
| TEMPORAL-03 | Phase 3 | Pending |
| TEMPORAL-04 | Phase 3 | Pending |
| TEMPORAL-05 | Phase 3 | Pending |
| TEMPORAL-06 | Phase 3 | Pending |
| OBS-01 | Phase 4 | Pending |
| OBS-02 | Phase 4 | Pending |
| OBS-03 | Phase 4 | Pending |
| OBS-04 | Phase 4 | Pending |
| OBS-05 | Phase 4 | Pending |
| APP-01 | Phase 5 | Pending |
| APP-02 | Phase 5 | Pending |
| APP-03 | Phase 5 | Pending |
| APP-04 | Phase 5 | Pending |
| APP-05 | Phase 5 | Pending |
| APP-06 | Phase 5 | Pending |
| CD-01 | Phase 5 | Pending |
| CD-02 | Phase 5 | Pending |
| CD-03 | Phase 5 | Pending |
| CD-04 | Phase 5 | Pending |
| CD-05 | Phase 5 | Pending |
