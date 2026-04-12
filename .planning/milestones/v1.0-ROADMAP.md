# Roadmap: Vici GKE Migration

## Overview

Migrate Vici from Render.com to GKE Autopilot across dev, staging, and prod environments. The roadmap follows the infrastructure dependency chain: cluster first, then database and secrets, then Temporal, then observability, then application workloads and CI/CD. Each phase delivers a verifiable capability that unblocks the next.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: GKE Cluster and Networking Baseline** - Provision GKE Autopilot clusters with Workload Identity, Pulumi state backend, and Artifact Registry
- [x] **Phase 2: Database and Secrets Infrastructure** - Cloud SQL instances, ESO, Secret Manager integration, and Alembic migration Job
- [x] **Phase 3: Temporal In-Cluster** - Temporal Server on dedicated Cloud SQL with OpenSearch visibility
- [x] **Phase 4: Observability Stack** - Jaeger, Prometheus, Grafana deployed and configured for application monitoring
- [x] **Phase 5: Application Deployment and CI/CD** - FastAPI app, Ingress with TLS, HPA, and GitHub Actions CD pipeline
- [ ] **Phase 5.1: GitHub Actions CI/CD Hardening** (INSERTED) - Rewrite CD workflows to match locked decisions: two-job base, Docker cache, SHA tagging, staging dispatch-only, prod approval gate
- [ ] **Phase 6: Infra Best-Practice Audit and Edge-Case Hardening** - Pulumi resource protection, network policies, PDBs, Temporal credential migration to ESO, and operational runbook

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
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md
- [x] 01-02-PLAN.md
- [x] 01-03-PLAN.md
- [x] 01-04-PLAN.md

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
**Plans**: Executed inline (verified)

Plans:
- [x] Completed (see 02-VERIFICATION.md)

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
- [x] 03-01-PLAN.md — Deploy OpenSearch single-node in observability namespace
- [x] 03-02-PLAN.md — Create Temporal schema migration Job and Temporal Helm release
- [x] 03-03-PLAN.md — Wire components into Pulumi entry point and verify deployment

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
- [x] 05-03-PLAN.md — WIF pool + CI/CD workflows + wire all Phase 5 components into __main__.py

### Phase 5.1: GitHub Actions CI/CD Hardening (INSERTED)
**Goal**: CD workflow files fully match locked decisions — two-job reusable base, Docker GHA layer cache, SHA-only tagging with Pulumi config-map passthrough, staging dispatch-only, prod environment approval gate, and post-deploy health check
**Depends on**: Phase 5
**Requirements**: CD-01, CD-02, CD-03, CD-04, CD-05
**Success Criteria** (what must be TRUE):
  1. `cd-base.yml` has two jobs (`build` and `deploy`) with WIF auth, Docker GHA cache, and SHA-only image tagging
  2. `cd-dev.yml` triggers on push to `main` and calls `cd-base.yml` with `command=up` and `stack=dev`
  3. `cd-staging.yml` triggers only on `workflow_dispatch` (no `pull_request` trigger)
  4. `cd-prod.yml` triggers on `workflow_dispatch` with `environment: prod` approval gate
  5. `config.py` exports `IMAGE_TAG` from `cfg.get("imageTag")` with `ENV` fallback; `app.py` uses `IMAGE_TAG`
  6. Static test suite validates all CD contracts via YAML and AST parsing
**Plans**: 2 plans

Plans:
- [x] 05.1-01-PLAN.md — Test scaffold and IMAGE_TAG config key for Pulumi
- [x] 05.1-02-PLAN.md — Rewrite all four CD workflow files to match locked decisions

### Phase 6: Infra Best-Practice Audit and Edge-Case Hardening
**Goal**: All stateful infrastructure is protected from accidental deletion, namespaces enforce least-privilege network access, Temporal credentials follow the ESO pattern, and operators have a runbook for edge-case scenarios
**Depends on**: Phase 5
**Requirements**: None (hardening phase — success criteria below)
**Success Criteria** (what must be TRUE):
  1. `pulumi preview` shows `protect: true` on Cloud SQL instances, GKE cluster, Artifact Registry, and GCS state bucket across all environments
  2. Each of the 5 namespaces (vici, temporal, observability, cert-manager, external-secrets) has a default-deny NetworkPolicy and explicit allow rules matching actual traffic patterns
  3. Temporal DB credentials are sourced from GCP Secret Manager via ESO (not Pulumi stack secrets) and the Temporal Helm release uses `existingSecret`
  4. PDBs exist for vici-app, temporal-frontend, and temporal-history in staging and prod (not dev)
  5. `infra/OPERATIONS.md` documents cold-start ordering, secret rotation, and cluster upgrade procedures
**Plans**: 4 plans

Plans:
- [x] 06-01-PLAN.md — Test scaffold and protect=True on stateful resources
- [x] 06-02-PLAN.md — NetworkPolicies for all 5 namespaces
- [x] 06-03-PLAN.md — Temporal DB credential migration to ESO
- [x] 06-04-PLAN.md — PDBs, resource limits, OPERATIONS.md, and __main__.py wiring

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 5.1 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. GKE Cluster and Networking Baseline | 4/4 | Complete | 2026-04-04 |
| 2. Database and Secrets Infrastructure | -/- | Verified | 2026-04-04 |
| 3. Temporal In-Cluster | 3/3 | Complete | 2026-04-05 |
| 4. Observability Stack | 3/3 | Validated | 2026-04-05 |
| 5. Application Deployment and CI/CD | 3/3 | Validated | 2026-04-06 |
| 5.1 GitHub Actions CI/CD Hardening | 0/2 | Planned | - |
| 6. Infra Best-Practice Audit | 0/4 | Planned | - |
