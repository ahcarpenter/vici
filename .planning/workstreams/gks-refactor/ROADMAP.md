# Roadmap: Vici GKE Migration

## Overview

Migrate Vici from Render.com to GKE Autopilot across dev, staging, and prod environments. The roadmap follows the infrastructure dependency chain: cluster first, then database and secrets, then Temporal, then observability, then application workloads and CI/CD. Each phase delivers a verifiable capability that unblocks the next.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: GKE Cluster and Networking Baseline** - Provision GKE Autopilot clusters with Workload Identity, Pulumi state backend, and Artifact Registry
- [ ] **Phase 2: Database and Secrets Infrastructure** - Cloud SQL instances, ESO, Secret Manager integration, and Alembic migration Job
- [ ] **Phase 3: Temporal In-Cluster** - Temporal Server on dedicated Cloud SQL with OpenSearch visibility
- [ ] **Phase 4: Observability Stack** - Jaeger, Prometheus, Grafana deployed and configured for application monitoring
- [x] **Phase 5: Application Deployment** - FastAPI app, Ingress with TLS, HPA, cert-manager, and full stack verification
- [ ] **Phase 5.1: GitHub Actions CI/CD** *(INSERTED)* - WIF pool, reusable CD workflows, per-environment deploy triggers

## Phase Details

### Phase 1: GKE Cluster and Networking Baseline
**Goal**: Operator can provision a complete, Workload-Identity-enabled GKE Autopilot cluster from a single Pulumi command, with state stored remotely and container registry ready
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, INFRA-07
**Success Criteria** (what must be TRUE):
  1. `pulumi up --stack dev` provisions a GKE Autopilot cluster in us-central1 with no manual steps
  2. The same Pulumi codebase with different stack configs produces identical infrastructure for dev, staging, and prod
  3. `pulumi up` run a second time proposes zero changes (idempotent; `ignore_changes` guards prevent cluster replacement)
  4. Namespaces `vici`, `temporal`, `observability`, `cert-manager`, and `external-secrets` exist in the cluster
  5. Artifact Registry repository exists and a test image can be pushed from CI credentials
**Plans**: TBD

Plans:
- [ ] 01-01: TBD

### Phase 2: Database and Secrets Infrastructure
**Goal**: Application secrets are synced from GCP Secret Manager to Kubernetes Secrets via ESO, Cloud SQL instances are reachable from pods via Auth Proxy, and Alembic migrations run successfully
**Depends on**: Phase 1
**Requirements**: DB-01, DB-02, DB-03, DB-04, DB-05, SECRETS-01, SECRETS-02, SECRETS-03, SECRETS-04, SECRETS-05
**Success Criteria** (what must be TRUE):
  1. A test pod in the `vici` namespace can connect to Cloud SQL (app instance) through the Auth Proxy sidecar using the socket-format `DATABASE_URL`
  2. A test pod in the `temporal` namespace can connect to the dedicated Temporal Cloud SQL instance
  3. `kubectl get externalsecret -A` shows all ExternalSecret resources in `Ready=True` state after `pulumi up`
  4. Each namespace (`vici`, `temporal`, `observability`) has its own namespace-scoped SecretStore pointing at GCP Secret Manager
  5. Alembic migration Job completes successfully and the app database schema is current
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: Temporal In-Cluster
**Goal**: Temporal Server runs in-cluster with OpenSearch-backed visibility, schema migrations complete, and workers can connect via the cluster-internal endpoint
**Depends on**: Phase 2
**Requirements**: TEMPORAL-01, TEMPORAL-02, TEMPORAL-03, TEMPORAL-04, TEMPORAL-05, TEMPORAL-06
**Success Criteria** (what must be TRUE):
  1. Temporal Server pods are Running in the `temporal` namespace, connected to the dedicated Cloud SQL instance
  2. Temporal UI is accessible within the cluster and shows registered namespaces
  3. A test workflow can be started and completed via `temporal-frontend.temporal.svc.cluster.local:7233`
  4. OpenSearch is healthy and Temporal workflow visibility search returns results
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — Deploy OpenSearch single-node in observability namespace
- [ ] 03-02-PLAN.md — Create Temporal schema migration Job and Temporal Helm release
- [ ] 03-03-PLAN.md — Wire components into Pulumi entry point and verify deployment

### Phase 4: Observability Stack
**Goal**: All application and infrastructure metrics, traces, and dashboards are operational so the first real request through the app generates observable telemetry
**Depends on**: Phase 3
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04, OBS-05
**Success Criteria** (what must be TRUE):
  1. Jaeger UI shows traces from the OTel collector endpoint (`jaeger-collector.observability.svc.cluster.local:4317`)
  2. Prometheus is scraping the FastAPI `/metrics` endpoint via ServiceMonitor
  3. Grafana is accessible and the existing FastAPI and Temporal dashboards are pre-provisioned
  4. `OTEL_EXPORTER_OTLP_ENDPOINT` secret resolves to the in-cluster Jaeger collector
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Deploy Jaeger v2 collector and query as raw K8s Deployments
- [x] 04-02-PLAN.md — Deploy kube-prometheus-stack with Grafana dashboards and ServiceMonitor
- [x] 04-03-PLAN.md — Wire observability into Pulumi entry point and create OTEL ExternalSecret

### Phase 5: Application Deployment
**Goal**: FastAPI app serves traffic on the public hostname with TLS, auto-scales under load, and all infrastructure components deploy cleanly via `pulumi up`
**Depends on**: Phase 4
**Requirements**: APP-01, APP-02, APP-03, APP-04, APP-05, APP-06
**Success Criteria** (what must be TRUE):
  1. `GET /health` returns HTTP 200 from the public GKE Ingress hostname with valid TLS certificate
  2. Temporal worker is connected to the in-cluster Temporal Server and appears in Temporal UI
  3. HPA scales the FastAPI Deployment between 1 and 3 replicas based on CPU
  4. `pulumi up --stack dev` completes with zero errors and all pods are Running
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — FastAPI Deployment + Service + HPA with Auth Proxy sidecar and stack config updates
- [x] 05-02-PLAN.md — cert-manager Helm release and GKE Ingress with TLS Issuers

### Phase 5.1: GitHub Actions CI/CD *(INSERTED)*
**Goal**: Pushing to `main` triggers automated build, push, and deploy to dev; staging and prod have appropriate gating
**Depends on**: Phase 5
**Requirements**: CD-01, CD-02, CD-03, CD-04, CD-05
**Success Criteria** (what must be TRUE):
  1. Pushing to `main` triggers a GitHub Actions job that builds, pushes to Artifact Registry, and runs `pulumi up --stack dev` with no static GCP credentials
  2. PRs to `main` run `pulumi preview --stack staging` automatically
  3. `pulumi up --stack prod` requires manual workflow dispatch with GitHub environment approval gate
  4. No static GCP service account keys exist; all auth uses WIF OIDC tokens
**Plans**: 1 plan

Plans:
- [ ] 05.1-01-PLAN.md — WIF pool + CI/CD workflows + wire CD components into __main__.py

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. GKE Cluster and Networking Baseline | 0/? | Not started | - |
| 2. Database and Secrets Infrastructure | 0/? | Not started | - |
| 3. Temporal In-Cluster | 0/3 | Planned | - |
| 4. Observability Stack | 3/3 | Validated | 2026-04-05 |
| 5. Application Deployment | 2/2 | Complete | 2026-04-09 |
| 5.1 GitHub Actions CI/CD *(INSERTED)* | 0/1 | Not started | - |
