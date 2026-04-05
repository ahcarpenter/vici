# Phase 4: Observability Stack - Research

**Researched:** 2026-04-05
**Domain:** Kubernetes observability — Jaeger v2, kube-prometheus-stack, Grafana, ServiceMonitor
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Deploy Jaeger v2 as raw K8s Deployments via Pulumi (collector + query), NOT via the Jaeger Helm chart. The Jaeger v2 unified binary uses OTel-native config that the v1 Helm chart doesn't support well.
- **D-02:** Port existing `jaeger/collector-config.yaml` and `jaeger/query-config.yaml` as ConfigMaps, updating OpenSearch URLs to point at the in-cluster instance (`opensearch-cluster-master.observability.svc.cluster.local:9200`)
- **D-03:** Deploy both collector and query as separate Deployments in the `observability` namespace. Collector receives OTLP on ports 4317 (gRPC) and 4318 (HTTP); query serves the Jaeger UI.
- **D-04:** Deploy full `kube-prometheus-stack` Helm chart in the `observability` namespace (OBS-03). This bundles Prometheus, Grafana, kube-state-metrics, and ServiceMonitor CRDs.
- **D-05:** Disable node-exporter in Helm values — GKE Autopilot has no node-level access.
- **D-06:** Use ServiceMonitor CRD for scrape target discovery. A ServiceMonitor targeting the FastAPI `/metrics` endpoint will be created in this phase (wired when the app Deployment exists in Phase 5, but the CRD and Prometheus config are ready now).
- **D-07:** Port existing `grafana/provisioning/dashboards/fastapi.json` as a ConfigMap with the sidecar label for `kube-prometheus-stack`'s Grafana sidecar provisioner. Dashboard auto-loads on Grafana startup.
- **D-08:** Add Jaeger (OpenSearch) as a second Grafana datasource via Helm values. Prometheus datasource comes bundled with `kube-prometheus-stack`.
- **D-09:** `kube-prometheus-stack`'s bundled Grafana replaces any need for a standalone Grafana deployment.
- **D-10:** All observability UIs (Grafana, Jaeger query) deployed as ClusterIP-only services. Operators use `kubectl port-forward` for dev access. All Ingress work deferred to Phase 5.

### Claude's Discretion

- `kube-prometheus-stack` Helm chart version to pin (verify latest stable at deploy time)
- Jaeger v2 image tag to pin (currently `2.16.0` in docker-compose — verify latest)
- Resource requests/limits for Jaeger collector and query on GKE Autopilot
- Prometheus retention period and storage size
- Whether to include alertmanager in the `kube-prometheus-stack` deployment or disable it for v1

### Deferred Ideas (OUT OF SCOPE)

- OTel Collector as vendor-neutral trace ingestion layer
- Grafana Loki, Alloy, and Tempo integration
- Grafana/Jaeger Ingress exposure — Phase 5
- Alertmanager configuration and alert rules — post-v1.0
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-01 | OpenSearch is deployed in the `observability` namespace with `number_of_replicas: 0` on index templates (single-node safe) | Already satisfied by Phase 3; `opensearch_release` and `opensearch_index_template_job` exist in `infra/components/opensearch.py` |
| OBS-02 | Jaeger v2 is deployed in the `observability` namespace connected to the in-cluster OpenSearch instance | Covered by D-01/D-02/D-03; raw Deployment pattern researched |
| OBS-03 | `kube-prometheus-stack` is deployed in the `observability` namespace; Prometheus scrapes the FastAPI `/metrics` endpoint via ServiceMonitor | Helm chart 69.x confirmed; GKE Autopilot disabled-components list confirmed; ServiceMonitor selector label requirement confirmed |
| OBS-04 | Grafana is provisioned with the existing FastAPI and Temporal dashboards | Sidecar ConfigMap label `grafana_dashboard: "1"` confirmed; Jaeger datasource via Helm values confirmed |
| OBS-05 | `OTEL_EXPORTER_OTLP_ENDPOINT` secret points to the in-cluster Jaeger collector (`http://jaeger-collector.observability.svc.cluster.local:4317`) | ExternalSecret pattern already established; secret name and value defined |
</phase_requirements>

---

## Summary

Phase 4 deploys three components into the existing `observability` namespace: Jaeger v2 (raw Kubernetes Deployments), the `kube-prometheus-stack` Helm chart (Prometheus + Grafana + CRDs), and supporting Kubernetes resources (ConfigMaps, Services, ServiceMonitor, ExternalSecret). All configuration is either ported directly from existing docker-compose files or follows Pulumi patterns already established in Phases 2–3.

The Jaeger v2 unified binary (`jaegertracing/jaeger:2.16.0`) takes a single `--config /path/to/config.yaml` argument. The existing `jaeger/collector-config.yaml` and `jaeger/query-config.yaml` files are nearly production-ready; only the `server_urls` value needs updating from `http://opensearch:9200` to `http://opensearch-cluster-master.observability.svc.cluster.local:9200`. Both files become Kubernetes ConfigMaps mounted into their respective Deployments.

The `kube-prometheus-stack` chart (latest stable: `69.x`) requires disabling several control-plane monitoring components that are inaccessible on GKE Autopilot: `nodeExporter`, `kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, `kubeProxy`, and optionally `coreDns`/`kubeDns`. The Grafana sidecar provisioner pattern requires dashboard ConfigMaps to carry label `grafana_dashboard: "1"` and is enabled by default in the chart.

**Primary recommendation:** Implement as one Pulumi component file (`infra/components/observability.py`) following the `temporal.py` pattern — module-level constants, Helm release with `depends_on`, then raw Deployments for Jaeger collector/query.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `jaegertracing/jaeger` | `2.16.0` | Unified Jaeger v2 binary (collector + query) | Locked (D-01); matches existing docker-compose; OTel-native config [VERIFIED: hub.docker.com] |
| `kube-prometheus-stack` | `69.x` (pin at deploy time) | Prometheus + Grafana + AlertManager + CRDs | Locked (D-04); industry standard for K8s observability [VERIFIED: artifacthub.io] |

> **Version note:** `kube-prometheus-stack` `82.18.0` appears in search results but this reflects the Artifact Hub listing at time of search. The chart releases very frequently. At planning time the current stable is in the `69.x–82.x` range — **pin the exact version at deploy time** by running `helm search repo prometheus-community/kube-prometheus-stack` against the live index. [VERIFIED: artifacthub.io search result]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `prometheus-community` Helm repo | — | Source for `kube-prometheus-stack` | Required for Helm release |
| `curlimages/curl` | `8.7.1` | Health-check Jobs (already in use) | Match existing `opensearch.py` pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw K8s Deployments for Jaeger | Jaeger Operator / OTel Operator | Operator is recommended by upstream for Jaeger v2 but adds CRD/cert-manager dependency; decision locked as D-01 |
| kube-prometheus-stack | Standalone Prometheus + Grafana Helm charts | More components to manage; kube-prometheus-stack bundles CRDs and wires everything automatically |

**Installation (Helm repo, run once in CI or locally):**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm search repo prometheus-community/kube-prometheus-stack  # note current version
```

---

## Architecture Patterns

### Recommended Project Structure

```
infra/
├── components/
│   ├── observability.py      # New: Jaeger Deployments + kube-prometheus-stack Helm release
│   ├── opensearch.py         # Already exists (OBS-01 satisfied)
│   └── ...
└── __main__.py               # Add: from components.observability import ...
```

### Pattern 1: Jaeger v2 Raw Deployment (ConfigMap + Deployment + Service)

**What:** Create ConfigMap from existing YAML, mount into Deployment via volume, expose via ClusterIP Service.

**When to use:** Both jaeger-collector and jaeger-query follow this exact pattern.

**Config change required:** Replace `http://opensearch:9200` with `http://opensearch-cluster-master.observability.svc.cluster.local:9200` in both ConfigMaps.

**Key ports:**
- Collector: `4317` (OTLP gRPC), `4318` (OTLP HTTP), `13133` (healthcheck via `healthcheckv2` extension)
- Query (UI): `16686` (HTTP UI + `/api/*`), `13133` (healthcheck)

**Container args pattern:** [VERIFIED: jaegertracing.io/docs/2.16/deployment]
```python
# Source: https://www.jaegertracing.io/docs/2.16/deployment/
args=["--config", "/etc/jaeger/config.yaml"]
```

**Volume mount pattern (Pulumi):**
```python
# Source: established pattern from opensearch.py + temporal.py
volume_mounts=[k8s.core.v1.VolumeMountArgs(
    name="jaeger-config",
    mount_path="/etc/jaeger",
)],
volumes=[k8s.core.v1.VolumeArgs(
    name="jaeger-config",
    config_map=k8s.core.v1.ConfigMapVolumeSourceArgs(
        name="jaeger-collector-config",  # or jaeger-query-config
    ),
)],
```

**ConfigMap key:** The YAML files should be keyed as `config.yaml` in the ConfigMap data so the mount path resolves to `/etc/jaeger/config.yaml`.

### Pattern 2: kube-prometheus-stack Helm Release with GKE Autopilot Values

**What:** Deploy the full Prometheus + Grafana bundle; disable components incompatible with GKE Autopilot.

**GKE Autopilot disabled components:** [VERIFIED: github.com/prometheus-community/helm-charts/issues/4833]
```python
# Source: https://github.com/prometheus-community/helm-charts/issues/4833
values={
    "nodeExporter": {"enabled": False},          # No node-level access on Autopilot
    "kubeControllerManager": {"enabled": False}, # Autopilot manages control plane
    "kubeScheduler": {"enabled": False},
    "kubeEtcd": {"enabled": False},
    "kubeProxy": {"enabled": False},
    "coreDns": {"enabled": False},
    "kubeDns": {"enabled": False},
    ...
}
```

**Grafana sidecar provisioner** is enabled by default in kube-prometheus-stack. Dashboard ConfigMaps must carry label: [VERIFIED: github.com/prometheus-community/helm-charts/issues/336]
```python
labels={"grafana_dashboard": "1"}
```

**Grafana additional datasource** for Jaeger via Helm values (D-08): [ASSUMED — pattern derived from chart docs; exact key structure should be verified against chart values.yaml at pin time]
```python
"grafana": {
    "additionalDataSources": [
        {
            "name": "Jaeger",
            "type": "jaeger",
            "uid": "jaeger",
            "url": "http://jaeger-query.observability.svc.cluster.local:16686",
            "access": "proxy",
            "editable": False,
        }
    ]
}
```

### Pattern 3: ServiceMonitor for FastAPI Metrics (OBS-03 / D-06)

**What:** Create a ServiceMonitor that targets the FastAPI Service's metrics port. The Service and Deployment exist in Phase 5, but the ServiceMonitor can be created now so Prometheus is already configured to scrape when Phase 5 lands.

**Critical selector requirement:** By default kube-prometheus-stack's Prometheus only discovers ServiceMonitors with label `release: <helm-release-name>`. To avoid this constraint, set `prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues: false` in Helm values — this makes Prometheus pick up ALL ServiceMonitors in the cluster. [VERIFIED: github.com/prometheus-community/helm-charts search result]

**ServiceMonitor pattern (Pulumi):** [ASSUMED — standard CRD structure, not verified against exact CRD version at pin time]
```python
k8s.apiextensions.CustomResource(
    "fastapi-service-monitor",
    api_version="monitoring.coreos.com/v1",
    kind="ServiceMonitor",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="fastapi-metrics",
        namespace="vici",
        labels={"release": "kube-prometheus-stack"},  # OR use selectorNilUsesHelmValues=false
    ),
    spec={
        "selector": {"matchLabels": {"app": "vici"}},
        "namespaceSelector": {"matchNames": ["vici"]},
        "endpoints": [{"port": "http", "path": "/metrics", "interval": "30s"}],
    },
    opts=ResourceOptions(provider=k8s_provider, depends_on=[kube_prometheus_release]),
)
```

### Pattern 4: ExternalSecret for OTEL_EXPORTER_OTLP_ENDPOINT (OBS-05)

**What:** Create an ExternalSecret in the `vici` namespace that syncs `OTEL_EXPORTER_OTLP_ENDPOINT` from GCP Secret Manager. The value is `http://jaeger-collector.observability.svc.cluster.local:4317`.

**Note:** The secret must be pre-populated in GCP Secret Manager (done in Phase 2 setup, or as a one-time operator step). The ExternalSecret CR follows the exact same pattern as existing secrets in `infra/components/secrets.py`.

**Also required:** The `OTEL_EXPORTER_OTLP_ENDPOINT` entry in the `observability` namespace SecretStore scope (SECRETS-03 covers this, but the actual GCP Secret Manager value for this key is set in this phase).

### Anti-Patterns to Avoid

- **Using the v1 Jaeger Helm chart for v2:** The old chart doesn't support the unified binary's OTel config format — use raw Deployments as decided (D-01).
- **Forgetting GKE Autopilot disabled components:** Leaving `nodeExporter`, `kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, `kubeProxy` enabled will cause Prometheus pods to fail to start or generate persistent alerts for unreachable scrape targets.
- **Wrong ServiceMonitor selector:** If `serviceMonitorSelectorNilUsesHelmValues` is not set and the ServiceMonitor lacks the `release:` label matching the Helm release name, Prometheus will silently ignore it.
- **ConfigMap key mismatch:** If the ConfigMap data key is not `config.yaml`, the `--config /etc/jaeger/config.yaml` arg will fail to find the file at startup.
- **Missing `depends_on` for Jaeger on opensearch_release:** Jaeger collector will crash-loop if OpenSearch is not ready; the `depends_on` chain must include `opensearch_release` from `opensearch.py`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prometheus metrics scrape discovery | Static scrape config in prometheus.yml | ServiceMonitor CRD | Static config requires Prometheus restart; ServiceMonitor is live-updated by the operator |
| Grafana dashboard deployment | Grafana HTTP API calls in a Job | Sidecar ConfigMap label provisioner | The sidecar watches ConfigMaps and hot-reloads dashboards; no manual API calls needed |
| Grafana datasource configuration | Datasource ConfigMap in `grafana/provisioning/datasources/` | `grafana.additionalDataSources` in Helm values | Helm values are version-controlled and idempotent; filesystem provisioning would conflict with the bundled Grafana |
| Prometheus + Grafana wiring | Separate Helm releases manually linked | `kube-prometheus-stack` single chart | The bundle pre-wires Prometheus as the default Grafana datasource, sets up recording rules, and installs CRDs atomically |

---

## Common Pitfalls

### Pitfall 1: GKE Autopilot Rejects node-exporter DaemonSet

**What goes wrong:** node-exporter requires `hostPID: true` and hostPath volumes — both are forbidden by GKE Autopilot's security policy. The DaemonSet fails to schedule and Prometheus raises persistent alerts.

**Why it happens:** kube-prometheus-stack enables node-exporter by default; GKE Autopilot enforces a restricted pod security standard.

**How to avoid:** Set `nodeExporter.enabled: false` in Helm values (D-05). Also disable `kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, `kubeProxy`, `coreDns`, `kubeDns` — all require access to the managed control plane which is unavailable on Autopilot. [VERIFIED: github.com/prometheus-community/helm-charts/issues/4833]

**Warning signs:** DaemonSet pods stuck in `Pending` with events mentioning `forbidden: unable to validate against any security policy`.

### Pitfall 2: Prometheus Silently Ignores ServiceMonitor

**What goes wrong:** ServiceMonitor is applied, but Prometheus never starts scraping; no error is shown.

**Why it happens:** By default, kube-prometheus-stack's Prometheus applies a `serviceMonitorSelector` that requires the label `release: <helm-release-name>` on every ServiceMonitor. ServiceMonitors without this label are ignored. [VERIFIED: github.com/prometheus-community/helm-charts/issues/336]

**How to avoid:** Either (a) add `labels: {release: "kube-prometheus-stack"}` to every ServiceMonitor, or (b) set `prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues: false` in Helm values to disable the filter globally (simpler for a single-tenant cluster).

**Warning signs:** ServiceMonitor exists but `kubectl get servicemonitor -n vici` shows it, yet Prometheus targets page shows no `vici` targets.

### Pitfall 3: Jaeger Crash-Loops Because OpenSearch Not Ready

**What goes wrong:** Jaeger collector starts and immediately fails because OpenSearch isn't accepting connections yet.

**Why it happens:** OpenSearch startup can take 60–120 seconds; Jaeger has no built-in wait mechanism.

**How to avoid:** Add an `initContainer` that polls `http://opensearch-cluster-master:9200/_cluster/health` with curl before the main Jaeger container starts, OR rely on Kubernetes restart backoff (since `healthcheckv2` will fail until OpenSearch is ready). Use `depends_on=[opensearch_index_template_job]` in Pulumi so Pulumi won't even apply the Jaeger resources until OpenSearch is confirmed healthy from the template Job.

**Warning signs:** Jaeger pods in `CrashLoopBackOff`; logs show `connection refused` to OpenSearch.

### Pitfall 4: Dashboard ConfigMap Not Picked Up by Grafana Sidecar

**What goes wrong:** ConfigMap containing dashboard JSON exists in the cluster, but Grafana's dashboard panel remains empty or shows an error.

**Why it happens:** The Grafana sidecar watches only ConfigMaps with label `grafana_dashboard: "1"` (exact string) in the same namespace as the Grafana pod.

**How to avoid:** The dashboard ConfigMap must be in the `observability` namespace (same as Grafana) and must carry exactly `labels: {"grafana_dashboard": "1"}`. [VERIFIED: github.com/prometheus-community/helm-charts community forum]

**Warning signs:** ConfigMap exists; `kubectl logs <grafana-sidecar-pod> -c grafana-sc-dashboard` shows no files being written.

### Pitfall 5: Jaeger Query Port Confusion

**What goes wrong:** Port-forwarding to the wrong port; UI is inaccessible.

**Why it happens:** Jaeger v2 query uses port `16686` for HTTP/UI (same as v1), but also exposes `13133` for health checks via `healthcheckv2`. Liveness/readiness probes must target `13133`, not `16686`.

**How to avoid:** Set `livenessProbe` and `readinessProbe` to `httpGet: path: /status, port: 13133`. [VERIFIED: jaegertracing.io/docs/2.16/deployment]

---

## Code Examples

### Jaeger Collector ConfigMap (Pulumi)

```python
# Source: jaeger/collector-config.yaml (ported) + D-02 URL update
_JAEGER_COLLECTOR_CONFIG = """\
service:
  extensions: [jaeger_storage, healthcheckv2]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    resource:
      service.name: jaeger-collector
    logs:
      level: info

extensions:
  healthcheckv2:
    use_v2: true
    http:

  jaeger_storage:
    backends:
      main_storage:
        opensearch:
          server_urls:
            - http://opensearch-cluster-master.observability.svc.cluster.local:9200
          indices:
            index_prefix: "jaeger-main"
            spans:
              date_layout: "2006-01-02"
              rollover_frequency: "day"
              shards: 1
              replicas: 0

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"
      http:
        endpoint: "0.0.0.0:4318"

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage: main_storage
"""

jaeger_collector_configmap = k8s.core.v1.ConfigMap(
    "jaeger-collector-config",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-collector-config",
        namespace="observability",
    ),
    data={"config.yaml": _JAEGER_COLLECTOR_CONFIG},
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["observability"]]),
)
```

### Jaeger Collector Deployment (Pulumi, key excerpt)

```python
# Source: D-01/D-03; ports from jaegertracing.io/docs/2.16
k8s.apps.v1.Deployment(
    "jaeger-collector",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="jaeger-collector", namespace="observability"),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        selector=k8s.meta.v1.LabelSelectorArgs(match_labels={"app": "jaeger-collector"}),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(labels={"app": "jaeger-collector"}),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[k8s.core.v1.ContainerArgs(
                    name="jaeger-collector",
                    image=f"jaegertracing/jaeger:{_JAEGER_IMAGE_TAG}",
                    args=["--config", "/etc/jaeger/config.yaml"],
                    ports=[
                        k8s.core.v1.ContainerPortArgs(container_port=4317, name="otlp-grpc"),
                        k8s.core.v1.ContainerPortArgs(container_port=4318, name="otlp-http"),
                        k8s.core.v1.ContainerPortArgs(container_port=13133, name="health"),
                    ],
                    liveness_probe=k8s.core.v1.ProbeArgs(
                        http_get=k8s.core.v1.HTTPGetActionArgs(path="/status", port=13133)
                    ),
                    readiness_probe=k8s.core.v1.ProbeArgs(
                        http_get=k8s.core.v1.HTTPGetActionArgs(path="/status", port=13133)
                    ),
                    volume_mounts=[k8s.core.v1.VolumeMountArgs(
                        name="jaeger-config", mount_path="/etc/jaeger"
                    )],
                )],
                volumes=[k8s.core.v1.VolumeArgs(
                    name="jaeger-config",
                    config_map=k8s.core.v1.ConfigMapVolumeSourceArgs(name="jaeger-collector-config"),
                )],
            ),
        ),
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[jaeger_collector_configmap, opensearch_index_template_job]),
)
```

### kube-prometheus-stack Helm Release (Pulumi, key values)

```python
# Source: D-04/D-05/D-08; GKE Autopilot disabled components from github.com/prometheus-community/helm-charts/issues/4833
kube_prometheus_release = k8s.helm.v3.Release(
    "kube-prometheus-stack",
    k8s.helm.v3.ReleaseArgs(
        chart="kube-prometheus-stack",
        version=_KUBE_PROMETHEUS_CHART_VERSION,  # pin at deploy time
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo="https://prometheus-community.github.io/helm-charts"
        ),
        namespace="observability",
        create_namespace=False,
        values={
            # GKE Autopilot: disable all control-plane and node-level scrapers
            "nodeExporter": {"enabled": False},
            "kubeControllerManager": {"enabled": False},
            "kubeScheduler": {"enabled": False},
            "kubeEtcd": {"enabled": False},
            "kubeProxy": {"enabled": False},
            "coreDns": {"enabled": False},
            "kubeDns": {"enabled": False},
            # Alertmanager: disable for v1 (post-v1.0 concern per CONTEXT.md deferred)
            "alertmanager": {"enabled": False},
            # Prometheus: pick up ALL ServiceMonitors (no label filter)
            "prometheus": {
                "prometheusSpec": {
                    "serviceMonitorSelectorNilUsesHelmValues": False,
                    "retention": "15d",
                    "storageSpec": {
                        "volumeClaimTemplate": {
                            "spec": {
                                "accessModes": ["ReadWriteOnce"],
                                "resources": {"requests": {"storage": "10Gi"}},
                            }
                        }
                    },
                }
            },
            # Grafana: enable sidecar, add Jaeger datasource (D-08)
            "grafana": {
                "sidecar": {
                    "dashboards": {"enabled": True, "label": "grafana_dashboard", "labelValue": "1"},
                },
                "additionalDataSources": [
                    {
                        "name": "Jaeger",
                        "type": "jaeger",
                        "uid": "jaeger",
                        "url": "http://jaeger-query.observability.svc.cluster.local:16686",
                        "access": "proxy",
                        "editable": False,
                    }
                ],
            },
        },
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["observability"]]),
)
```

### FastAPI Dashboard ConfigMap with Sidecar Label (Pulumi)

```python
# Source: D-07; sidecar label from github.com/prometheus-community/helm-charts
import json

with open("../grafana/provisioning/dashboards/fastapi.json") as f:
    fastapi_dashboard_json = f.read()

k8s.core.v1.ConfigMap(
    "grafana-dashboard-fastapi",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="grafana-dashboard-fastapi",
        namespace="observability",
        labels={"grafana_dashboard": "1"},
    ),
    data={"fastapi.json": fastapi_dashboard_json},
    opts=ResourceOptions(provider=k8s_provider, depends_on=[kube_prometheus_release]),
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Jaeger v1 (separate collector/query/agent binaries) | Jaeger v2 (single unified binary, OTel-native) | 2024 | Config format changed from CLI flags to YAML pipeline config |
| Static prometheus.yml scrape config | ServiceMonitor CRD | 2019+ | Live-updating, operator-managed scrape targets |
| Standalone Grafana + Prometheus Helm charts | `kube-prometheus-stack` bundle | 2019+ | Single chart, pre-wired, CRDs included |

**Deprecated/outdated:**
- `jaeger-agent` sidecar: Removed in Jaeger v2; the app sends directly to the collector via OTLP.
- Jaeger v1 Helm chart: Does not support v2 unified binary config format (reason for D-01).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Grafana `additionalDataSources` uses `type: "jaeger"` for Jaeger datasource | Code Examples (kube-prometheus-stack values) | Grafana datasource type string may differ; verify against chart values.yaml at pin time |
| A2 | Grafana sidecar default label value is `"1"` (string) | Architecture Patterns #2 | If default is different, dashboard ConfigMaps will not be loaded |
| A3 | `alertmanager.enabled: false` is the correct key to disable AlertManager in kube-prometheus-stack | Code Examples | Chart key may differ by version; verify against pinned chart values.yaml |
| A4 | ServiceMonitor placed in `vici` namespace will be discovered by Prometheus in `observability` namespace when `serviceMonitorSelectorNilUsesHelmValues: false` | Architecture Patterns #3 | Cross-namespace ServiceMonitor discovery may require additional `namespaceSelector` on PrometheusSpec |

---

## Open Questions

1. **kube-prometheus-stack exact version to pin**
   - What we know: Latest stable is in the `69.x–82.x` range as of 2026-04-05
   - What's unclear: Exact latest stable at plan execution time
   - Recommendation: Run `helm search repo prometheus-community/kube-prometheus-stack --versions | head -5` at Wave 0 and hardcode in the module constant

2. **Temporal dashboard for Grafana (OBS-04)**
   - What we know: OBS-04 requires "existing FastAPI and Temporal dashboards" are provisioned. `grafana/provisioning/dashboards/fastapi.json` exists. No `temporal.json` was found in the repo.
   - What's unclear: Does a Temporal Grafana dashboard exist in the repo? The CONTEXT.md says "ported from `grafana/provisioning/`" but only `fastapi.json` was found.
   - Recommendation: Check if `grafana/provisioning/dashboards/` has a temporal dashboard; if not, the planner should either skip it (treat OBS-04 as FastAPI-only for v1.0) or source a community Temporal dashboard JSON.

3. **Jaeger query port on Service vs. container**
   - What we know: Jaeger query HTTP/UI is on container port `16686`
   - What's unclear: Whether the Jaeger query config requires explicit `http_endpoint` or defaults to `:16686`
   - Recommendation: Test with existing query-config.yaml; the `jaeger_query` extension has no explicit port in the existing config, which implies it defaults to `16686`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Helm CLI | Pulumi Helm Release provider | [ASSUMED] ✓ | — | — |
| `kubectl` | Verification / port-forward | [ASSUMED] ✓ | — | — |
| GKE cluster (observability namespace) | All resources | ✓ (Phase 3 confirmed complete) | — | — |
| OpenSearch in-cluster | Jaeger collector/query | ✓ (Phase 3 delivered) | 2.x | — |
| GCP Secret Manager entry for `OTEL_EXPORTER_OTLP_ENDPOINT` | OBS-05 / ExternalSecret | Likely ✗ — needs to be populated | — | Operator populates manually pre-deploy |

**Missing dependencies with no fallback:**
- GCP Secret Manager must have the `OTEL_EXPORTER_OTLP_ENDPOINT` secret value pre-populated before the ExternalSecret can sync. This is a one-time manual step (or scripted via `gcloud secrets create`).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` or `pyproject.toml` (existing) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| OBS-01 | OpenSearch deployed with replicas:0 | Infrastructure (kubectl) | `kubectl get pod -n observability -l app.kubernetes.io/name=opensearch` | Phase 3 complete; verify as smoke test |
| OBS-02 | Jaeger UI accessible in cluster | Smoke (port-forward + curl) | `kubectl port-forward svc/jaeger-query 16686:16686 -n observability &; curl -s http://localhost:16686/` | Manual |
| OBS-03 | Prometheus scraping via ServiceMonitor | Smoke (port-forward + curl) | `kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n observability &; curl -s "http://localhost:9090/api/v1/targets"` | Manual |
| OBS-04 | Grafana shows provisioned dashboards | Smoke (port-forward + browser) | `kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n observability` | Manual |
| OBS-05 | ExternalSecret Ready=True | kubectl | `kubectl get externalsecret -n vici` | Automated check |

### Wave 0 Gaps

- No new test files required — observability components are infrastructure-only (no app code changes). Verification is via `kubectl` commands and `pulumi up` success.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | ClusterIP-only services; no public exposure (D-10) |
| V5 Input Validation | no | — |
| V6 Cryptography | no | In-cluster HTTP only; TLS deferred to Phase 5 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated Grafana access | Elevation of Privilege | ClusterIP + port-forward only (D-10); Grafana admin password auto-generated by chart |
| Unauthenticated Prometheus access | Information Disclosure | ClusterIP only; no public route |
| Jaeger trace data exposure | Information Disclosure | ClusterIP only; OpenSearch security disabled (existing, in-cluster only) |

---

## Sources

### Primary (HIGH confidence)
- [jaegertracing.io/docs/2.16/deployment](https://www.jaegertracing.io/docs/2.16/deployment/) — Jaeger v2 `--config` flag, healthcheck port 13133, UI port 16686
- [hub.docker.com/r/jaegertracing/jaeger](https://hub.docker.com/r/jaegertracing/jaeger) — Jaeger v2 image `2.16.0` confirmed current
- [artifacthub.io kube-prometheus-stack](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack) — Chart version range confirmed
- `infra/components/opensearch.py` — `OPENSEARCH_SERVICE_HOST` constant and `opensearch_index_template_job` export (codebase verified)
- `infra/components/temporal.py` — Pulumi Helm release pattern with `depends_on`, module constants (codebase verified)
- `jaeger/collector-config.yaml`, `jaeger/query-config.yaml` — Existing Jaeger v2 configs (codebase verified)

### Secondary (MEDIUM confidence)
- [github.com/prometheus-community/helm-charts/issues/4833](https://github.com/prometheus-community/helm-charts/issues/4833) — GKE Autopilot disabled component list verified via community issue
- [github.com/prometheus-community/helm-charts/issues/336](https://github.com/prometheus-community/helm-charts/issues/336) — ServiceMonitor label selector pattern confirmed

### Tertiary (LOW confidence)
- General web search for Grafana `additionalDataSources` Helm values key structure — not verified against pinned chart version; marked [ASSUMED] in Assumptions Log

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Jaeger image tag verified on Docker Hub; chart version verified on Artifact Hub
- Architecture: HIGH — Pulumi patterns directly confirmed from existing codebase; port numbers verified from official Jaeger docs
- Pitfalls: HIGH — GKE Autopilot constraints verified via official GitHub issues
- Grafana values structure: MEDIUM — derived from chart docs and community examples; exact key names should be verified at pin time

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (kube-prometheus-stack releases frequently; re-verify chart version before `pulumi up`)
