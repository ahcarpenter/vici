---
phase: 05-application-deployment-and-ci-cd
plan: 01
subsystem: infra
tags: [kubernetes, deployment, hpa, pulumi, gke, cloud-sql-proxy]
dependency_graph:
  requires:
    - infra/components/migration.py
    - infra/components/secrets.py
    - infra/components/registry.py
    - infra/components/iam.py
    - infra/components/namespaces.py
    - infra/components/database.py
  provides:
    - infra/components/app.py (app_deployment, app_service, app_hpa)
    - infra/config.py (APP_HOSTNAME, GITHUB_ORG)
  affects:
    - infra/__main__.py (must import app.py)
    - infra/components/ingress.py (Plan 02 consumes APP_HOSTNAME)
    - infra/components/cd.py (Plan 03 consumes GITHUB_ORG)
tech_stack:
  added:
    - k8s.apps.v1.Deployment (FastAPI app with Cloud SQL Auth Proxy native sidecar)
    - k8s.autoscaling.v2.HorizontalPodAutoscaler (CPU-based auto-scaling)
    - k8s.core.v1.Service (ClusterIP, port 8000)
  patterns:
    - Native sidecar via init_containers with restart_policy="Always" (K8s 1.28+)
    - envFrom list comprehension over 11 ExternalSecret-generated K8s Secrets
    - Module-level constants for all magic numbers
key_files:
  created:
    - infra/components/app.py
  modified:
    - infra/Pulumi.dev.yaml
    - infra/Pulumi.staging.yaml
    - infra/Pulumi.prod.yaml
    - infra/config.py
decisions:
  - "Auth Proxy sidecar replicates migration.py pattern verbatim — same image, UID 65532, unix socket, restart_policy=Always"
  - "autoscaling/v2 HPA used (v1 is deprecated); CPU target 70%, 1-3 replicas"
  - "GKE Autopilot requires explicit resource requests on ALL containers including sidecars — added to Auth Proxy"
  - "app:vici label used on Deployment, pod template, Service metadata and selector — matches existing fastapi_service_monitor"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-05"
  tasks_completed: 2
  files_created: 1
  files_modified: 4
---

# Phase 05 Plan 01: FastAPI App Deployment + Service + HPA Summary

**One-liner:** FastAPI Deployment with Cloud SQL Auth Proxy native sidecar, 11 envFrom secrets, readiness/liveness probes, ClusterIP Service (app:vici selector), and autoscaling/v2 HPA (CPU 70%, 1-3 replicas) as Pulumi components.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create infra/components/app.py | 51f8fc0 | infra/components/app.py (created) |
| 2 | Add app_hostname and github_org to stack configs | 8042ec1 | Pulumi.dev.yaml, Pulumi.staging.yaml, Pulumi.prod.yaml, config.py |

## What Was Built

### Task 1: infra/components/app.py

Created the core application Pulumi component with three Kubernetes resources:

**Deployment (`vici-app`):**
- Cloud SQL Auth Proxy native sidecar via `init_containers` with `restart_policy="Always"` (K8s 1.28+ pattern, reused from `migration.py`)
- 11 `envFrom` entries — one per ExternalSecret-generated K8s Secret (list comprehension over `_ENV_FROM_SOURCES`)
- Readiness probe: HTTP GET `/readyz`, initial_delay=15s, period=10s, failure_threshold=3
- Liveness probe: HTTP GET `/health`, initial_delay=30s, period=30s, failure_threshold=3
- App container resources: 250m/512Mi request, 500m/1Gi limit
- Auth Proxy resources: 100m/256Mi request, 200m/512Mi limit (GKE Autopilot requires explicit limits on all containers)
- `service_account_name="vici-app"` matching the KSA provisioned in `iam.py`
- `depends_on`: app_db_instance, migration_job, vici_app_ksa, namespaces["vici"], all 11 external_secrets

**Service (`vici-app`):**
- Type: ClusterIP
- Selector: `{"app": "vici"}` — matches existing `fastapi_service_monitor` from Phase 4
- Port: 8000 named "http"
- `depends_on`: app_deployment

**HPA (`vici-app`):**
- `k8s.autoscaling.v2.HorizontalPodAutoscaler` (v1 is deprecated)
- Target: Deployment `vici-app`, `apps/v1`
- min_replicas=1, max_replicas=3
- CPU Utilization target: 70%
- `depends_on`: app_deployment

### Task 2: Stack configs + config.py

Added `app_hostname` and `github_org` to all three Pulumi stack files:
- `Pulumi.dev.yaml`: `dev.usevici.com`, `ahcarpenter`
- `Pulumi.staging.yaml`: `staging.usevici.com`, `ahcarpenter`
- `Pulumi.prod.yaml`: `usevici.com`, `ahcarpenter`

Extended `infra/config.py` with:
- `APP_HOSTNAME: str = cfg.require("app_hostname")` — consumed by ingress.py (Plan 02)
- `GITHUB_ORG: str = cfg.require("github_org")` — consumed by cd.py (Plan 03)

## Deviations from Plan

None — plan executed exactly as written.

## Threat Mitigation Coverage

All five threats from the plan's STRIDE register are addressed:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-05-01 | `service_account_name="vici-app"` — Workload Identity bound KSA | Implemented |
| T-05-02 | Image pulled from private Artifact Registry via `registry_url` | Implemented |
| T-05-03 | All secrets via `envFrom` from ESO-generated K8s Secrets — nothing in spec args | Implemented |
| T-05-04 | HPA min=1/max=3 at CPU 70%; resource limits enforced | Implemented |
| T-05-05 | Auth Proxy runs as UID 65532, `run_as_non_root=True`; IAM-only auth | Implemented |

## Known Stubs

None — all data is wired from actual Pulumi outputs (registry_url, app_db_instance.connection_name, ENV).

## Threat Flags

None — no new security surface introduced beyond what the plan's threat model covers.

## Self-Check: PASSED

- [x] `infra/components/app.py` exists
- [x] Commits 51f8fc0 and 8042ec1 verified in git log
- [x] ruff check passes (0 errors)
- [x] Python syntax OK
- [x] All 11 secret slugs present in `_ENV_FROM_SOURCES`
- [x] `"app": "vici"` label appears 5 times (Deployment meta, pod template, Service meta, Service selector, Deployment matchLabels)
- [x] All three Pulumi stack configs have `app_hostname` and `github_org`
- [x] `APP_HOSTNAME` and `GITHUB_ORG` in `config.py`
