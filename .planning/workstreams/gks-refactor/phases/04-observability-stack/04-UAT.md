---
status: complete
phase: 04-observability-stack
source: 04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md
started: 2026-04-05T12:00:00Z
updated: 2026-04-05T12:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Jaeger Collector and Query Resources in Pulumi Preview
expected: Running `pulumi preview` (or inspecting infra/components/jaeger.py) shows 8 Jaeger resources: 2 ConfigMaps, 2 Deployments, 2 Services (collector on 4317/4318, query on 16686), and 2 Pulumi exports. All target the observability namespace.
result: pass

### 2. kube-prometheus-stack Helm Release
expected: Pulumi preview shows a kube-prometheus-stack Helm release in the observability namespace with GKE Autopilot incompatible components disabled (nodeExporter, kubeControllerManager, kubeScheduler, kubeEtcd, kubeProxy, coreDns, kubeDns) and alertmanager disabled.
result: pass

### 3. Grafana Dashboard Provisioning
expected: Two ConfigMaps provision Grafana dashboards via sidecar labels: FastAPI dashboard from local JSON file, and Temporal dashboard downloaded/cached from grafana.com (ID 17900). Both have `grafana_dashboard: "1"` label.
result: pass

### 4. FastAPI ServiceMonitor CRD
expected: A ServiceMonitor CustomResource is created in the vici namespace targeting pods with label `app=vici` on port `http` at path `/metrics` with 30s scrape interval. Prometheus discovers it via `serviceMonitorSelectorNilUsesHelmValues: false`.
result: pass

### 5. Observability Components Registered in __main__.py
expected: infra/__main__.py contains import lines for both jaeger (jaeger_collector_deployment, jaeger_query_deployment) and prometheus (kube_prometheus_release, fastapi_service_monitor) components, ensuring all resources are included in `pulumi up`.
result: pass

### 6. OTEL ExternalSecret Targets vici Namespace
expected: infra/components/secrets.py defines the otel-exporter-otlp-endpoint ExternalSecret targeting the `vici` namespace (not `observability`), so app pods can mount the OTLP endpoint secret directly.
result: pass

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
