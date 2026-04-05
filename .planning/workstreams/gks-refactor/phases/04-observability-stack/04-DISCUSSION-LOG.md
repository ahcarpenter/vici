# Phase 4: Observability Stack - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 04-observability-stack
**Areas discussed:** Jaeger v2 deployment strategy, Prometheus stack scope, Grafana dashboard provisioning, Access and exposure

---

## Jaeger v2 Deployment Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Raw K8s manifests | Port existing collector + query configs as ConfigMaps, deploy as Pulumi K8s Deployments. Full control over Jaeger v2 config. | ✓ |
| Jaeger Helm chart | Community Helm chart designed for Jaeger v1 architecture (agent/collector/query). Doesn't natively support Jaeger v2 unified binary config. | |
| OTel Collector + Jaeger query | Deploy OTel Collector for ingestion, Jaeger query for UI. More cloud-native but adds complexity. | |

**User's choice:** Raw K8s manifests (option 1)
**Notes:** Jaeger v2 uses a unified binary with OTel-native config. The v1 Helm chart doesn't support this well. Existing docker-compose configs are portable.

---

## Prometheus Stack Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full kube-prometheus-stack | Includes Prometheus, Grafana, kube-state-metrics, alertmanager, ServiceMonitor CRDs. Industry standard for K8s. | ✓ |
| Standalone Prometheus Helm | Lighter, no CRDs, no bundled Grafana. Separate Grafana deployment needed. | |
| Raw K8s manifests | Port existing prometheus.yml as ConfigMap. No ServiceMonitor support. | |

**User's choice:** Full kube-prometheus-stack (option 1)
**Notes:** Matches OBS-03 requirement. Node-exporter disabled for Autopilot. ServiceMonitor CRD provides scrape target discovery.

---

## Grafana Dashboard Provisioning

| Option | Description | Selected |
|--------|-------------|----------|
| ConfigMap sidecar provisioning | Port fastapi.json as labeled ConfigMap for kube-prometheus-stack's Grafana sidecar. Add Jaeger/OpenSearch as second datasource via Helm values. | ✓ |
| Inline in Helm values | Embed dashboard JSON directly in kube-prometheus-stack values. Simpler for Pulumi but hard to maintain. | |
| Skip custom dashboards initially | Deploy with built-in K8s dashboards only, port custom dashboards later. | |

**User's choice:** ConfigMap sidecar provisioning (option 1)
**Notes:** Standard pattern for kube-prometheus-stack. Keeps dashboard JSON maintainable. OBS-04 requires existing FastAPI dashboard to be pre-provisioned.

---

## Access and Exposure

| Option | Description | Selected |
|--------|-------------|----------|
| ClusterIP-only (port-forward) | Consistent with Phase 3 approach. All Ingress work in Phase 5. | ✓ |
| Expose Grafana + Jaeger via Ingress | Useful for dev debugging but overlaps Phase 5 scope. | |
| Expose Grafana only via Ingress | Middle ground — Jaeger accessible via Grafana datasource. | |

**User's choice:** ClusterIP-only (option 1)
**Notes:** Keeps Phase 4 focused on deploying components. Phase 5 owns all Ingress/TLS work.

---

## Claude's Discretion

- Helm chart versions and image tags (pin latest stable at deploy time)
- Resource requests/limits for Jaeger and Prometheus on Autopilot
- Prometheus retention period and storage size
- Whether to include or disable alertmanager for v1

## Deferred Ideas

- OTel Collector as vendor-neutral ingestion layer (todo captured)
- Grafana Loki, Alloy, Tempo integration (todo captured)
- Grafana/Jaeger Ingress — Phase 5
- Alertmanager rules — post-v1.0
