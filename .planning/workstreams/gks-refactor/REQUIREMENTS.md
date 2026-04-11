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

Status legend:
- `Code-Verified`: phase verification (automated + manual code review) passed; live-cluster behavior still pending.
- `Human-Needed`: code-level verification passed; live-cluster / live-DNS / GitHub-dashboard confirmation pending.
- `Complete`: both code-level and runtime-observable verification passed.
- `Pending`: phase has not executed yet.

| REQ-ID | Phase | Status | Notes |
|--------|-------|--------|-------|
| INFRA-01 | Phase 1 | Code-Verified | 4 SUMMARY.md artifacts; live dev cluster provisioned during 01-04. No formal VERIFICATION.md (documentation debt per v1.0-MILESTONE-AUDIT.md). |
| INFRA-02 | Phase 1 | Code-Verified | Single Pulumi program, three stack configs. |
| INFRA-03 | Phase 1 | Code-Verified | Workload Identity enabled at cluster creation per 01-02. |
| INFRA-04 | Phase 1 | Code-Verified | ignore_changes guards on dns_config and node_version per 01-02. |
| INFRA-05 | Phase 1 | Code-Verified | GCS state backend, per-env buckets. |
| INFRA-06 | Phase 1 | Code-Verified | All five namespaces (vici, temporal, observability, cert-manager, external-secrets) declared in 01-03. |
| INFRA-07 | Phase 1 | Code-Verified | vici-images Artifact Registry repo in us-central1; CI push SA bound to artifactregistry.writer. |
| DB-01 | Phase 2 | Human-Needed | Code-verified; live cluster reachability via Auth Proxy socket pending. |
| DB-02 | Phase 2 | Human-Needed | Dedicated Temporal Cloud SQL instance per env; runtime validation pending. |
| DB-03 | Phase 2 | Human-Needed | Cloud SQL Auth Proxy native sidecar annotation; live behavior pending. |
| DB-04 | Phase 2 | Human-Needed | Alembic migration Job; runtime completion pending. |
| DB-05 | Phase 2 | Human-Needed | DATABASE_URL Auth Proxy socket format; runtime connectivity pending. |
| SECRETS-01 | Phase 2 | Human-Needed | All 11 external secrets declared in GCP Secret Manager. |
| SECRETS-02 | Phase 2 | Human-Needed | ESO Helm release with depends_on ordering. |
| SECRETS-03 | Phase 2 | Human-Needed | Namespace-scoped SecretStore per namespace. |
| SECRETS-04 | Phase 2 | Human-Needed | ExternalSecret CRs for every secret; Ready=True confirmation pending live cluster. |
| SECRETS-05 | Phase 2 | Human-Needed | Minimum IAM roles (secretmanager.secretAccessor, cloudsql.client). |
| OBS-01 | Phase 3 | Code-Verified | **Moved from Phase 4 to Phase 3** (mapping error identified in v1.0-MILESTONE-AUDIT.md). OpenSearch is deployed by Phase 3 opensearch.py, not Phase 4. number_of_replicas: 0 for single-node safety confirmed in code. |
| TEMPORAL-01 | Phase 3 | Code-Verified | temporaltech/temporal chart 0.74.0; live deployment confirmed in 03-03 SUMMARY. |
| TEMPORAL-02 | Phase 3 | Code-Verified | OpenSearch for visibility; bundled Elasticsearch disabled. |
| TEMPORAL-03 | Phase 3 | Code-Verified | opensearch readiness guard via depends_on. |
| TEMPORAL-04 | Phase 3 | Code-Verified | Temporal schema Job runs before server Deployment. |
| TEMPORAL-05 | Phase 3 | Code-Verified | TEMPORAL_HOST secret pins to temporal-frontend.temporal.svc.cluster.local:7233. |
| TEMPORAL-06 | Phase 3 | Code-Verified | ClusterIP UI service; no formal VERIFICATION.md (documentation debt). |
| OBS-02 | Phase 4 | Human-Needed | Jaeger v2 deployed; live trace collection pending Phase 5 app deploy. |
| OBS-03 | Phase 4 | Human-Needed | kube-prometheus-stack + ServiceMonitor; scrape success pending live app. |
| OBS-04 | Phase 4 | Human-Needed | Grafana dashboard provisioning; Temporal dashboard downloaded at pulumi up time with placeholder fallback (tech debt). |
| OBS-05 | Phase 4 | Human-Needed | OTEL_EXPORTER_OTLP_ENDPOINT ExternalSecret sync pending live cluster. |
| APP-01 | Phase 5 | Code-Verified | FastAPI Deployment in vici namespace; Auth Proxy sidecar annotation + envFrom ExternalSecret wiring verified. |
| APP-02 | Phase 5 | Human-Needed | Temporal worker lifespan wiring verified in code; live connectivity to in-cluster Temporal pending. |
| APP-03 | Phase 5 | Code-Verified | HPA min 1 max 3 CPU 70% per 05-01. |
| APP-04 | Phase 5 | Code-Verified | GKE Ingress + cert-manager + Let's Encrypt wiring per 05-02; live cert issuance pending DNS cutover. |
| APP-05 | Phase 5 | Human-Needed | GET /health returns 200 from public hostname — requires live DNS + TLS cert. |
| APP-06 | Phase 5 | Code-Verified | WEBHOOK_BASE_URL secret derived from APP_HOSTNAME. |
| CD-01 | Phase 5.1 | Code-Verified + Runtime-Validated | Re-delivered by Phase 5.1. Runtime-validated 4× on `main` in the 05.1 deploy cycle (final success: run 24291614628). |
| CD-02 | Phase 5.1 | Code-Verified | Re-delivered by Phase 5.1. Staging is dispatch-only per locked D-05; PR preview is intentionally deferred. |
| CD-03 | Phase 5.1 | Human-Needed | Re-delivered by Phase 5.1. cd-prod.yml passes `environment: prod`; GitHub Environment `prod` created via gh api with `ahcarpenter` as required reviewer (2026-04-11). Runtime gate validation pending (UAT item 4). |
| CD-04 | Phase 5.1 | Code-Verified + Runtime-Validated | Re-delivered by Phase 5.1. WIF auth confirmed on build and deploy jobs; no static keys. |
| CD-05 | Phase 5.1 | Code-Verified | Re-delivered by Phase 5.1. ci.yml unchanged from Phase 5; static test pins the no-GCP invariant. |
