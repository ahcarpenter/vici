# Phase 4: Observability Stack - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy Jaeger v2, kube-prometheus-stack (Prometheus + Grafana), and ServiceMonitor into the GKE cluster so that application traces, metrics, and dashboards are operational. OpenSearch is already deployed (Phase 3) — this phase consumes it for Jaeger trace storage. All services are ClusterIP-only; Ingress exposure is deferred to Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Jaeger v2 Deployment
- **D-01:** Deploy Jaeger v2 as raw K8s Deployments via Pulumi (collector + query), NOT via the Jaeger Helm chart. The Jaeger v2 unified binary uses OTel-native config that the v1 Helm chart doesn't support well.
- **D-02:** Port existing `jaeger/collector-config.yaml` and `jaeger/query-config.yaml` as ConfigMaps, updating OpenSearch URLs to point at the in-cluster instance (`opensearch-cluster-master.observability.svc.cluster.local:9200`)
- **D-03:** Deploy both collector and query as separate Deployments in the `observability` namespace. Collector receives OTLP on ports 4317 (gRPC) and 4318 (HTTP); query serves the Jaeger UI.

### Prometheus Stack
- **D-04:** Deploy full `kube-prometheus-stack` Helm chart in the `observability` namespace (OBS-03). This bundles Prometheus, Grafana, kube-state-metrics, and ServiceMonitor CRDs.
- **D-05:** Disable node-exporter in Helm values — GKE Autopilot has no node-level access.
- **D-06:** Use ServiceMonitor CRD for scrape target discovery. A ServiceMonitor targeting the FastAPI `/metrics` endpoint will be created in this phase (wired when the app Deployment exists in Phase 5, but the CRD and Prometheus config are ready now).

### Grafana Dashboard Provisioning
- **D-07:** Port existing `grafana/provisioning/dashboards/fastapi.json` as a ConfigMap with the sidecar label for `kube-prometheus-stack`'s Grafana sidecar provisioner. Dashboard auto-loads on Grafana startup.
- **D-08:** Add Jaeger (OpenSearch) as a second Grafana datasource via Helm values. Prometheus datasource comes bundled with `kube-prometheus-stack`.
- **D-09:** `kube-prometheus-stack`'s bundled Grafana replaces any need for a standalone Grafana deployment.

### Access and Exposure
- **D-10:** All observability UIs (Grafana, Jaeger query) deployed as ClusterIP-only services. Operators use `kubectl port-forward` for dev access. All Ingress work deferred to Phase 5.

### Claude's Discretion
- `kube-prometheus-stack` Helm chart version to pin (verify latest stable at deploy time)
- Jaeger v2 image tag to pin (currently `2.16.0` in docker-compose — verify latest)
- Resource requests/limits for Jaeger collector and query on GKE Autopilot
- Prometheus retention period and storage size
- Whether to include alertmanager in the `kube-prometheus-stack` deployment or disable it for v1

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` §OBS — OBS-01 through OBS-05 define all observability requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` §OBS-01 — OpenSearch `number_of_replicas: 0` (already satisfied by Phase 3)

### Existing configs to port
- `jaeger/collector-config.yaml` — Jaeger v2 collector config (OTLP receiver → OpenSearch exporter). Port as ConfigMap, update `server_urls` to in-cluster OpenSearch.
- `jaeger/query-config.yaml` — Jaeger v2 query config (OpenSearch backend). Port as ConfigMap, update `server_urls`.
- `grafana/provisioning/dashboards/fastapi.json` — FastAPI dashboard JSON. Port as ConfigMap for sidecar provisioner.
- `grafana/provisioning/datasources/prometheus.yml` — Prometheus datasource config (reference only — `kube-prometheus-stack` bundles this automatically)
- `prometheus/prometheus.yml` — Current Prometheus scrape config (reference only — ServiceMonitor replaces static config in GKE)

### Existing Pulumi components (patterns to follow)
- `infra/components/opensearch.py` — OpenSearch already deployed; `OPENSEARCH_SERVICE_HOST` constant importable for Jaeger configs
- `infra/components/temporal.py` — Helm release pattern with `depends_on` chains
- `infra/components/namespaces.py` — `observability` namespace already exists; `k8s_provider` importable
- `infra/__main__.py` — Entry point; new component imports registered here

### Prior phase context
- `.planning/workstreams/gks-refactor/phases/03-temporal-in-cluster/03-CONTEXT.md` — OpenSearch deployment decisions, shared instance pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `infra/components/opensearch.py` — `OPENSEARCH_SERVICE_HOST` constant (`opensearch-cluster-master.observability.svc.cluster.local`) for Jaeger config URLs
- `infra/components/opensearch.py` — `opensearch_release` resource for `depends_on` chains
- `jaeger/collector-config.yaml` + `jaeger/query-config.yaml` — Working Jaeger v2 configs, need only URL updates for in-cluster use
- `grafana/provisioning/dashboards/fastapi.json` — Production-ready FastAPI dashboard

### Established Patterns
- **Helm release via Pulumi**: `k8s.helm.v3.Release` with `repository_opts`, pinned `chart_version`, `create_namespace=False`, `ResourceOptions(provider=k8s_provider, depends_on=[...])` — see `opensearch.py`, `temporal.py`, `secrets.py`
- **Module-level constants**: All image tags, chart versions, port numbers as `_CONST_NAME` at module top
- **Component registration**: New file in `infra/components/`, imported in `infra/__main__.py`
- **Job pattern**: `backoff_limit=0`, `ttl_seconds_after_finished` — see `opensearch.py` index template Job

### Integration Points
- Jaeger collector ← FastAPI app's `OTEL_EXPORTER_OTLP_ENDPOINT` (Phase 5 sets this secret to `http://jaeger-collector.observability.svc.cluster.local:4317`)
- Jaeger collector/query → OpenSearch (already deployed, Phase 3)
- Prometheus ← FastAPI `/metrics` endpoint via ServiceMonitor (app Deployment created in Phase 5)
- Grafana → Prometheus datasource (bundled) + Jaeger/OpenSearch datasource (added via Helm values)

</code_context>

<specifics>
## Specific Ideas

- Jaeger v2 configs are nearly identical to docker-compose — the main change is updating `server_urls` from `http://opensearch:9200` to the in-cluster `http://opensearch-cluster-master.observability.svc.cluster.local:9200`
- `kube-prometheus-stack` is the industry-standard Helm chart for Kubernetes observability — it replaces the standalone Prometheus + standalone Grafana pattern from docker-compose

</specifics>

<deferred>
## Deferred Ideas

- OTel Collector as vendor-neutral trace ingestion layer (captured as todo: `2026-04-05-ensure-otel-collector-is-leveraged.md`)
- Grafana Loki, Alloy, and Tempo integration (captured as todo: `2026-04-03-integrate-grafana-loki-alloy-and-tempo-for-observability.md`)
- Grafana/Jaeger Ingress exposure — Phase 5
- Alertmanager configuration and alert rules — post-v1.0

</deferred>

---

*Phase: 04-observability-stack*
*Context gathered: 2026-04-05*
