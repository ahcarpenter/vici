# Vici — GKE Migration

## What This Is

A full infrastructure migration of the Vici SMS matching service from Render.com to Google Kubernetes Engine (GKE) Autopilot, managed via Pulumi (Python). All application behavior is unchanged — this workstream is purely infrastructure and deployment.

## Core Value

All three environments (dev, staging, prod) run on 1:1 mirrored GKE infrastructure managed by a single Pulumi program, with GKE-native capabilities (Workload Identity, Secret Manager, Cloud SQL) replacing Render.com primitives.

## Current Milestone: v1.0 GKE Migration

**Goal:** Replace Render.com with GKE Autopilot across dev/staging/prod, managed via Pulumi, with Workload Identity, Secret Manager, Cloud SQL, and a GitHub Actions CD pipeline.

**Target features:**
- Pulumi (Python) IaC — three mirrored stacks: `dev`, `staging`, `prod`
- GKE Autopilot cluster per environment
- Cloud SQL (Postgres 16) per environment with Cloud SQL Auth Proxy sidecar
- Workload Identity Federation for all GCP-touching pods
- Secret Manager for all external secrets (Twilio, OpenAI, Pinecone, Braintrust, Temporal), synced via External Secrets Operator
- Kubernetes workloads: FastAPI app, Temporal worker, Temporal server, Jaeger, Prometheus, Grafana
- Alembic migration Kubernetes Job as pre-deploy step
- HPA for FastAPI deployment
- Ingress + TLS per environment (env-specific hostnames)
- GitHub Actions CD: build → Artifact Registry → `pulumi up` per environment
- Observability (OTel → Jaeger, Prometheus → Grafana) per environment

## Requirements

### Active

- [ ] Pulumi Python program provisions identical GKE Autopilot infrastructure for dev, staging, and prod
- [ ] Each environment has its own Cloud SQL Postgres 16 instance, GKE cluster, and Secret Manager namespace
- [ ] Workload Identity bindings eliminate static GCP credentials from all pods
- [ ] All external secrets (Twilio, OpenAI, Pinecone, Braintrust) stored in Secret Manager and synced to K8s Secrets via External Secrets Operator
- [ ] All six workloads deploy to each environment: FastAPI app, Temporal worker, Temporal server, Jaeger, Prometheus, Grafana
- [ ] Cloud SQL Auth Proxy sidecar present on FastAPI app and Temporal worker pods
- [ ] Alembic migrations run as a Kubernetes Job before app rollout in each environment
- [ ] HPA configured for FastAPI deployment in all environments
- [ ] Ingress and TLS configured per environment with environment-specific hostnames
- [ ] GitHub Actions CD pipeline deploys to GKE via Pulumi (dev on push to main; staging/prod on explicit trigger)
- [ ] Prometheus scrapes all pods; Grafana provisioned with existing dashboards
- [ ] OTel collector routes traces to Jaeger per environment
- [ ] `render.yaml` retired; `docker-compose.yml` preserved for local dev

### Out of Scope

- Application code changes — no src/ modifications
- Dockerfile changes — image is already production-ready
- CI test pipeline changes — tests remain SQLite-based on GitHub Actions
- Multi-region or multi-cluster setups — single region per environment
- GitOps tooling (ArgoCD, Flux) — direct `pulumi up` in CI is sufficient for v1

## Architecture

### Deployment Model

```
GitHub Actions (CI/CD)
  └── CI job: pytest (unchanged, SQLite)
  └── CD job: docker build → push to Artifact Registry → pulumi up --stack <env>

Pulumi Python program (.pulumi/ or infra/)
  ├── stack: dev    → GKE Autopilot (dev)    + Cloud SQL (dev)    + Secret Manager (dev)
  ├── stack: staging → GKE Autopilot (staging) + Cloud SQL (staging) + Secret Manager (staging)
  └── stack: prod   → GKE Autopilot (prod)   + Cloud SQL (prod)   + Secret Manager (prod)

Per-environment GKE cluster (Autopilot)
  ├── Namespace: vici
  │   ├── Deployment: vici-app (FastAPI + Cloud SQL Auth Proxy sidecar)
  │   ├── Deployment: vici-temporal-worker (+ Cloud SQL Auth Proxy sidecar)
  │   ├── Job: vici-migrate (Alembic, runs before rollout)
  │   ├── HPA: vici-app
  │   └── Ingress: vici (env hostname, TLS)
  ├── Namespace: temporal
  │   └── StatefulSet/Deployment: temporal-server
  └── Namespace: observability
      ├── Deployment: jaeger
      ├── Deployment: otel-collector
      ├── Deployment: prometheus
      └── Deployment: grafana

External Secrets Operator (cluster-wide)
  └── SecretStore → GCP Secret Manager
        └── ExternalSecret → K8s Secret (per namespace)

Workload Identity
  └── K8s ServiceAccount → GCP ServiceAccount (per workload)
        └── Bound to: Cloud SQL Client, Secret Manager Accessor
```

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| GKE Autopilot | No node management; right-sized pods automatically |
| Pulumi Python | Consistent with existing Python codebase; typed, testable IaC |
| Three mirrored stacks | 1:1 infrastructure parity; env differences are config only |
| Cloud SQL over self-hosted Postgres | Managed backups, HA, IAM integration; no ops burden |
| External Secrets Operator | Decouples secret lifecycle from app deployment |
| Workload Identity | No static credentials; GCP-native RBAC |
| Cloud SQL Auth Proxy sidecar | Secure, IAM-authed DB connections without VPC peering complexity |

## Constraints

- **IaC**: Pulumi Python — no Terraform, no CDK
- **Cluster mode**: GKE Autopilot only — no Standard node pools
- **Identity**: Workload Identity Federation — no static service account keys in pods
- **Secrets**: GCP Secret Manager + External Secrets Operator — no hardcoded env vars in manifests
- **Environments**: dev, staging, prod — identical infrastructure, environment-scoped names
- **Local dev**: `docker-compose.yml` unchanged — GKE is production path only

## Current State

**v1.0 GKE Migration — SHIPPED 2026-04-12**

7 phases, 19 plans, ~4400 LOC Python (Pulumi IaC + tests), 295 LOC YAML (GitHub Actions).

Infrastructure: GKE Autopilot cluster, Cloud SQL (app + Temporal), Artifact Registry, ESO, cert-manager, Ingress with TLS, Temporal Server with OpenSearch visibility, full observability stack (Prometheus, Grafana, Jaeger), GitHub Actions CI/CD with WIF auth, NetworkPolicies, PDBs, resource protection, and operational runbook.

Known tech debt:
- Phases 1 and 3 lack formal VERIFICATION.md (functionally complete per SUMMARY.md and live deployment)
- Grafana Temporal dashboard downloaded at `pulumi up` time with placeholder fallback
- Requirement checkboxes in REQUIREMENTS.md were not maintained (all 40 requirements traced in traceability table)

---
*Last updated: 2026-04-12 after v1.0 milestone — all 7 phases complete, all 40 requirements traced, live UAT passed for Phase 6.*
