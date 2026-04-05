import json
import os
import urllib.request

import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_KUBE_PROMETHEUS_CHART_VERSION = "69.8.2"
_KUBE_PROMETHEUS_REPO = "https://prometheus-community.github.io/helm-charts"
_PROMETHEUS_RETENTION = "15d"
_PROMETHEUS_STORAGE_SIZE = "10Gi"
_JAEGER_QUERY_URL = "http://jaeger-query.observability.svc.cluster.local:16686"
_TEMPORAL_DASHBOARD_ID = 17900  # Grafana.com dashboard ID for Temporal Server SDK metrics

# ---------------------------------------------------------------------------
# Dashboard JSON paths
# ---------------------------------------------------------------------------

_INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FASTAPI_DASHBOARD_PATH = os.path.join(
    _INFRA_DIR, "..", "grafana", "provisioning", "dashboards", "fastapi.json"
)
_TEMPORAL_DASHBOARD_DIR = os.path.join(_INFRA_DIR, "..", "grafana", "provisioning", "dashboards")
_TEMPORAL_DASHBOARD_FILE = os.path.join(_TEMPORAL_DASHBOARD_DIR, "temporal.json")
_TEMPORAL_DASHBOARD_URL = (
    f"https://grafana.com/api/dashboards/{_TEMPORAL_DASHBOARD_ID}/revisions/latest/download"
)

# ---------------------------------------------------------------------------
# Load FastAPI dashboard JSON at module load time
# ---------------------------------------------------------------------------

with open(_FASTAPI_DASHBOARD_PATH) as f:
    _FASTAPI_DASHBOARD_JSON = f.read()

# ---------------------------------------------------------------------------
# Load (or download+cache) Temporal dashboard JSON at module load time
# ---------------------------------------------------------------------------

if not os.path.exists(_TEMPORAL_DASHBOARD_FILE):
    try:
        with urllib.request.urlopen(_TEMPORAL_DASHBOARD_URL) as resp:
            _temporal_raw = resp.read().decode()
        # Validate JSON before caching
        json.loads(_temporal_raw)
        os.makedirs(_TEMPORAL_DASHBOARD_DIR, exist_ok=True)
        with open(_TEMPORAL_DASHBOARD_FILE, "w") as _f:
            _f.write(_temporal_raw)
        _TEMPORAL_DASHBOARD_JSON = _temporal_raw
    except Exception as _exc:
        import pulumi as _pulumi  # already imported above; re-imported for clarity in except block

        _pulumi.warn(
            f"Could not download Temporal dashboard (ID={_TEMPORAL_DASHBOARD_ID}): {_exc}. "
            "Using placeholder dashboard. Replace grafana/provisioning/dashboards/temporal.json "
            "with the real dashboard JSON when network access is available."
        )
        _TEMPORAL_DASHBOARD_JSON = json.dumps(
            {
                "uid": "temporal-workflows",
                "title": "Temporal Workflows",
                "schemaVersion": 38,
                "panels": [
                    {
                        "type": "text",
                        "title": "TODO",
                        "options": {
                            "content": (
                                "Placeholder dashboard. Replace this file with the real "
                                f"Temporal SDK dashboard from "
                                f"https://grafana.com/grafana/dashboards/{_TEMPORAL_DASHBOARD_ID}"
                            )
                        },
                    }
                ],
            }
        )
        os.makedirs(_TEMPORAL_DASHBOARD_DIR, exist_ok=True)
        with open(_TEMPORAL_DASHBOARD_FILE, "w") as _f:
            _f.write(_TEMPORAL_DASHBOARD_JSON)
else:
    with open(_TEMPORAL_DASHBOARD_FILE) as f:
        _TEMPORAL_DASHBOARD_JSON = f.read()

# ---------------------------------------------------------------------------
# kube-prometheus-stack Helm release (OBS-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10)
# ---------------------------------------------------------------------------

kube_prometheus_release = k8s.helm.v3.Release(
    "kube-prometheus-stack",
    k8s.helm.v3.ReleaseArgs(
        chart="kube-prometheus-stack",
        version=_KUBE_PROMETHEUS_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_KUBE_PROMETHEUS_REPO),
        namespace="observability",
        create_namespace=False,
        values={
            # GKE Autopilot: disable components requiring node-level access (D-05)
            "nodeExporter": {"enabled": False},
            "kubeControllerManager": {"enabled": False},
            "kubeScheduler": {"enabled": False},
            "kubeEtcd": {"enabled": False},
            "kubeProxy": {"enabled": False},
            "coreDns": {"enabled": False},
            "kubeDns": {"enabled": False},
            # Alertmanager: disabled for v1 (deferred per CONTEXT.md)
            "alertmanager": {"enabled": False},
            # Prometheus config (D-06)
            "prometheus": {
                "prometheusSpec": {
                    # Discover all ServiceMonitors regardless of Helm labels (D-06)
                    "serviceMonitorSelectorNilUsesHelmValues": False,
                    "retention": _PROMETHEUS_RETENTION,
                    "storageSpec": {
                        "volumeClaimTemplate": {
                            "spec": {
                                "accessModes": ["ReadWriteOnce"],
                                "resources": {
                                    "requests": {"storage": _PROMETHEUS_STORAGE_SIZE}
                                },
                            }
                        }
                    },
                }
            },
            # Grafana: sidecar provisioner + Jaeger datasource (D-07, D-08, D-09)
            "grafana": {
                "sidecar": {
                    "dashboards": {
                        "enabled": True,
                        "label": "grafana_dashboard",
                        "labelValue": "1",
                    },
                },
                "additionalDataSources": [
                    {
                        "name": "Jaeger",
                        "type": "jaeger",
                        "uid": "jaeger",
                        "url": _JAEGER_QUERY_URL,
                        "access": "proxy",
                        "editable": False,
                    }
                ],
            },
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["observability"]],
    ),
)

# ---------------------------------------------------------------------------
# FastAPI dashboard ConfigMap — sidecar-provisioned into Grafana (D-07)
# ---------------------------------------------------------------------------

fastapi_dashboard_configmap = k8s.core.v1.ConfigMap(
    "grafana-dashboard-fastapi",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="grafana-dashboard-fastapi",
        namespace="observability",
        labels={"grafana_dashboard": "1"},
    ),
    data={"fastapi.json": _FASTAPI_DASHBOARD_JSON},
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[kube_prometheus_release],
    ),
)

# ---------------------------------------------------------------------------
# Temporal dashboard ConfigMap — sidecar-provisioned into Grafana (D-07)
# ---------------------------------------------------------------------------

temporal_dashboard_configmap = k8s.core.v1.ConfigMap(
    "grafana-dashboard-temporal",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="grafana-dashboard-temporal",
        namespace="observability",
        labels={"grafana_dashboard": "1"},
    ),
    data={"temporal.json": _TEMPORAL_DASHBOARD_JSON},
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[kube_prometheus_release],
    ),
)

# ---------------------------------------------------------------------------
# FastAPI ServiceMonitor — targets vici namespace /metrics endpoint (D-06, OBS-04)
# ServiceMonitor CRD is installed by kube-prometheus-stack above.
# App Deployment does not exist yet (Phase 5), but the scrape config is ready.
# ---------------------------------------------------------------------------

fastapi_service_monitor = k8s.apiextensions.CustomResource(
    "fastapi-service-monitor",
    api_version="monitoring.coreos.com/v1",
    kind="ServiceMonitor",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="fastapi-metrics",
        namespace="vici",
    ),
    spec={
        "selector": {"matchLabels": {"app": "vici"}},
        "namespaceSelector": {"matchNames": ["vici"]},
        "endpoints": [{"port": "http", "path": "/metrics", "interval": "30s"}],
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[kube_prometheus_release],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("grafana_service", "kube-prometheus-stack-grafana.observability.svc.cluster.local")
pulumi.export(
    "prometheus_service",
    "kube-prometheus-stack-prometheus.observability.svc.cluster.local",
)
