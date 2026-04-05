---
phase: 04-observability-stack
plan: "02"
subsystem: infra/observability
tags: [pulumi, prometheus, grafana, servicemonitor, helm, gke-autopilot]
dependency_graph:
  requires:
    - 04-01 (observability namespace via namespaces.py)
  provides:
    - kube_prometheus_release
    - fastapi_service_monitor
  affects:
    - 04-03 (wires prometheus.py into __main__.py)
tech_stack:
  added:
    - kube-prometheus-stack Helm chart 69.8.2
    - Grafana sidecar dashboard provisioner
    - Prometheus ServiceMonitor CRD (monitoring.coreos.com/v1)
  patterns:
    - ConfigMap-based dashboard provisioning via Grafana sidecar
    - Module-load-time HTTP fetch with local cache for external JSON assets
key_files:
  created:
    - infra/components/prometheus.py
  modified: []
decisions:
  - GKE Autopilot: disabled 7 node-level components (nodeExporter, kubeControllerManager, kubeScheduler, kubeEtcd, kubeProxy, coreDns, kubeDns)
  - serviceMonitorSelectorNilUsesHelmValues=False so ServiceMonitor in vici namespace is discovered
  - alertmanager disabled for v1 per CONTEXT.md
  - Temporal dashboard downloaded from grafana.com at module load time, cached locally; fallback placeholder on download failure
metrics:
  duration: "10m"
  completed: "2026-04-05"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
requirements:
  - OBS-03
  - OBS-04
---

# Phase 04 Plan 02: kube-prometheus-stack with Dashboards and ServiceMonitor Summary

**One-liner:** kube-prometheus-stack Helm release (GKE Autopilot safe) with FastAPI and Temporal Grafana dashboard ConfigMaps, Jaeger datasource, and FastAPI ServiceMonitor CRD.

## What Was Built

`infra/components/prometheus.py` deploys the full Prometheus + Grafana observability stack to the `observability` namespace using the `kube-prometheus-stack` Helm chart. Key resources:

1. **`kube_prometheus_release`** — Helm release with 7 GKE Autopilot incompatible components disabled, alertmanager disabled, Prometheus PVC storage (15d retention, 10Gi), Grafana sidecar dashboard provisioner, and Jaeger as an additional datasource.

2. **`fastapi_dashboard_configmap`** — Reads `grafana/provisioning/dashboards/fastapi.json` at Pulumi module load time and provisions it via Grafana sidecar (`grafana_dashboard: "1"` label).

3. **`temporal_dashboard_configmap`** — Downloads Temporal Server SDK dashboard (ID 17900) from grafana.com at module load, caches to `grafana/provisioning/dashboards/temporal.json`; falls back to a placeholder JSON with a clear TODO message if network unavailable.

4. **`fastapi_service_monitor`** — `ServiceMonitor` CustomResource in the `vici` namespace targeting `app=vici` pods on port `http` at `/metrics` every 30 seconds. Ready for Phase 5 app deployment.

5. **Exports** — `grafana_service` and `prometheus_service` ClusterIP hostnames.

## Decisions Made

- All 7 GKE Autopilot-inaccessible components disabled per D-05 to prevent eviction/scheduling failures
- `serviceMonitorSelectorNilUsesHelmValues: false` so Prometheus discovers ServiceMonitors outside its own Helm release labels
- AlertManager disabled for v1 (per CONTEXT.md deferred list)
- Temporal dashboard cache pattern: download once to disk, subsequent `pulumi up` runs skip download — avoids flaky network dependency in CI

## Deviations from Plan

None - plan executed exactly as written. The fallback placeholder for Temporal dashboard download failure was specified in the plan and implemented accordingly.

## Known Stubs

None. No UI-rendering stubs introduced. Temporal dashboard placeholder is guarded by a try/except and only activates if grafana.com is unreachable at deploy time; the cached file on disk is the real dashboard after first successful run.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-04-04 mitigated | infra/components/prometheus.py | Grafana as ClusterIP only — no Ingress, no external access |
| T-04-05 mitigated | infra/components/prometheus.py | Prometheus as ClusterIP only — no public route |

## Self-Check: PASSED

- `infra/components/prometheus.py` exists and contains all required resources
- Python syntax verified: `ast.parse()` passes
- Commit `fd40b56` confirmed in git log
