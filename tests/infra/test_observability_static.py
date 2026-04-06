"""Static assertions for Phase 4 observability infrastructure.

These tests parse the Pulumi Python source files directly (via AST) to verify
that infrastructure definitions satisfy OBS-04 and OBS-05 requirements without
requiring a live cluster or Pulumi runtime.
"""

import ast
import pathlib

import pytest

INFRA_DIR = pathlib.Path(__file__).resolve().parents[2] / "infra" / "components"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_source(filename: str) -> str:
    path = INFRA_DIR / filename
    assert path.exists(), f"Expected {path} to exist"
    return path.read_text()


def _find_dict_literals(source: str) -> list[ast.Dict]:
    """Return all dict literal nodes in *source*."""
    tree = ast.parse(source)
    return [node for node in ast.walk(tree) if isinstance(node, ast.Dict)]


# ---------------------------------------------------------------------------
# OBS-04: Dashboard ConfigMaps must carry grafana_dashboard="1" label
# ---------------------------------------------------------------------------


class TestOBS04DashboardConfigMapLabels:
    """Verify both FastAPI and Temporal dashboard ConfigMaps include the
    ``grafana_dashboard: "1"`` label so the Grafana sidecar picks them up.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source("prometheus.py")

    def test_fastapi_configmap_has_grafana_dashboard_label(self) -> None:
        assert (
            '"grafana_dashboard": "1"' in self.source
            or "'grafana_dashboard': '1'" in self.source
        ), "FastAPI dashboard ConfigMap must include labels={'grafana_dashboard': '1'}"

    def test_temporal_configmap_has_grafana_dashboard_label(self) -> None:
        # Both ConfigMaps use the same label dict; count occurrences to ensure
        # *two* ConfigMaps carry the label (FastAPI + Temporal).
        count = self.source.count('"grafana_dashboard"') + self.source.count(
            "'grafana_dashboard'"
        )
        assert count >= 2, (
            "Expected at least 2 ConfigMaps with "
            f"grafana_dashboard label, found {count}"
        )

    def test_grafana_sidecar_label_matches_configmap_label(self) -> None:
        """The Helm values sidecar label must match the ConfigMap labels."""
        assert (
            '"label": "grafana_dashboard"' in self.source
            or "'label': 'grafana_dashboard'" in self.source
        ), "Grafana sidecar config must reference 'grafana_dashboard' as the label key"
        assert (
            '"labelValue": "1"' in self.source or "'labelValue': '1'" in self.source
        ), "Grafana sidecar labelValue must be '1'"

    def test_configmaps_target_observability_namespace(self) -> None:
        """Both dashboard ConfigMaps must be in the observability namespace."""
        # The namespace appears in ObjectMetaArgs for each ConfigMap
        lines = self.source.splitlines()
        ns_hits = [
            i
            for i, line in enumerate(lines)
            if "namespace" in line and "observability" in line
        ]
        # At minimum: Helm release + 2 ConfigMaps = 3 observability namespace refs
        assert len(ns_hits) >= 3, (
            f"Expected ≥3 observability namespace references, found {len(ns_hits)}"
        )


# ---------------------------------------------------------------------------
# OBS-05: OTEL_EXPORTER_OTLP_ENDPOINT ExternalSecret targets vici namespace
# ---------------------------------------------------------------------------


class TestOBS05OtelExternalSecret:
    """Verify the OTEL endpoint ExternalSecret is defined and targets the
    ``vici`` namespace so the app pods can mount it.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source("secrets.py")

    def test_otel_secret_defined_in_secret_definitions(self) -> None:
        assert "otel-exporter-otlp-endpoint" in self.source, (
            "otel-exporter-otlp-endpoint must appear in _SECRET_DEFINITIONS"
        )

    def test_otel_secret_targets_vici_namespace(self) -> None:
        """The otel-exporter-otlp-endpoint tuple must target the vici namespace."""
        tree = ast.parse(self.source)
        for node in ast.walk(tree):
            # _SECRET_DEFINITIONS uses a type annotation (AnnAssign), not plain Assign
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = (
                    node.targets[0] if isinstance(node, ast.Assign) else node.target
                )
                if isinstance(target, ast.Name) and target.id == "_SECRET_DEFINITIONS":
                    value = node.value
                    assert isinstance(value, ast.List)
                    for elt in value.elts:
                        if not isinstance(elt, ast.Tuple):
                            continue
                        values = [
                            c.value for c in elt.elts if isinstance(c, ast.Constant)
                        ]
                        if "otel-exporter-otlp-endpoint" in values:
                            # Tuple format: (slug, namespace, k8s-secret-name)
                            assert values[1] == "vici", (
                                "otel-exporter-otlp-endpoint "
                                "namespace must be 'vici', "
                                f"got '{values[1]}'"
                            )
                            return
        pytest.fail("Could not find otel-exporter-otlp-endpoint in _SECRET_DEFINITIONS")

    def test_vici_namespace_has_secretstore(self) -> None:
        """The vici namespace must be in the SecretStore namespace list."""
        assert '"vici"' in self.source or "'vici'" in self.source
        tree = ast.parse(self.source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = (
                    node.targets[0] if isinstance(node, ast.Assign) else node.target
                )
                if (
                    isinstance(target, ast.Name)
                    and target.id == "_SECRETSTORE_NAMESPACES"
                ):
                    assert isinstance(node.value, ast.List)
                    ns_values = [
                        c.value for c in node.value.elts if isinstance(c, ast.Constant)
                    ]
                    assert "vici" in ns_values, (
                        f"vici must be in _SECRETSTORE_NAMESPACES, found {ns_values}"
                    )
                    return
        pytest.fail("Could not find _SECRETSTORE_NAMESPACES assignment")


# ---------------------------------------------------------------------------
# OBS-01: Jaeger collector and query Deployments, ports, probes, and services
# ---------------------------------------------------------------------------


class TestOBS01JaegerDeployments:
    """Verify jaeger.py defines both collector and query Deployment resources
    with correct OTLP ports, health probes, resource limits, and ClusterIP services.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source("jaeger.py")

    def test_collector_and_query_deployments_defined(self) -> None:
        """Both collector and query must be defined as k8s.apps.v1.Deployment calls."""
        tree = ast.parse(self.source)
        deployment_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match k8s.apps.v1.Deployment(...)
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "Deployment"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "v1"
                ):
                    # Collect the resource name (first positional arg)
                    if node.args and isinstance(node.args[0], ast.Constant):
                        deployment_calls.append(node.args[0].value)
        assert "jaeger-collector" in deployment_calls, (
            f"Expected jaeger-collector Deployment, found: {deployment_calls}"
        )
        assert "jaeger-query" in deployment_calls, (
            f"Expected jaeger-query Deployment, found: {deployment_calls}"
        )

    def test_collector_exposes_otlp_grpc_port_4317(self) -> None:
        """Collector must declare OTLP gRPC port 4317."""
        assert (
            "_JAEGER_OTLP_GRPC_PORT = 4317" in self.source
            or "container_port=4317" in self.source
        ), "Collector must expose OTLP gRPC port 4317"
        # The constant must resolve to 4317
        assert "4317" in self.source

    def test_collector_exposes_otlp_http_port_4318(self) -> None:
        """Collector must declare OTLP HTTP port 4318."""
        assert (
            "_JAEGER_OTLP_HTTP_PORT = 4318" in self.source
            or "container_port=4318" in self.source
        ), "Collector must expose OTLP HTTP port 4318"
        assert "4318" in self.source

    def test_query_exposes_port_16686(self) -> None:
        """Query must declare UI port 16686."""
        assert (
            "_JAEGER_QUERY_PORT = 16686" in self.source
            or "container_port=16686" in self.source
        ), "Query Deployment must expose port 16686"
        assert "16686" in self.source

    def test_both_deployments_have_health_probes_on_port_13133_path_status(
        self,
    ) -> None:
        """Both collector and query must reference health
        port 13133 and path /status."""
        assert "13133" in self.source, "Health port 13133 must be referenced"
        assert '"/status"' in self.source or "'/status'" in self.source, (
            "Health probe path /status must be referenced"
        )
        # The constant should appear in probe definitions; count usages
        # Both deployments define liveness + readiness probes
        # referencing the same health port
        health_port_count = self.source.count("13133")
        assert health_port_count >= 2, (
            "Expected health port 13133 to appear in both "
            f"deployments (>=2 uses), found {health_port_count}"
        )

    def test_both_deployments_have_resource_limits(self) -> None:
        """Both collector and query must have resource limits configured."""
        assert "_JAEGER_COLLECTOR_CPU_LIMIT" in self.source, (
            "Collector CPU limit constant must be defined"
        )
        assert "_JAEGER_COLLECTOR_MEMORY_LIMIT" in self.source, (
            "Collector memory limit constant must be defined"
        )
        assert "_JAEGER_QUERY_CPU_LIMIT" in self.source, (
            "Query CPU limit constant must be defined"
        )
        assert "_JAEGER_QUERY_MEMORY_LIMIT" in self.source, (
            "Query memory limit constant must be defined"
        )
        # Both deployments reference the limits dict key
        assert (
            self.source.count('"limits"')
            + self.source.count("'limits'")
            + self.source.count("limits=")
            >= 2
        ), "Expected resource limits defined in both collector and query Deployments"

    def test_both_services_are_clusterip_type(self) -> None:
        """Both Jaeger services must be ClusterIP (no external exposure)."""
        clusterip_count = self.source.count('type="ClusterIP"') + self.source.count(
            "type='ClusterIP'"
        )
        assert clusterip_count >= 2, (
            "Expected 2 ClusterIP services "
            f"(collector + query), found {clusterip_count}"
        )


# ---------------------------------------------------------------------------
# OBS-02: Prometheus ServiceMonitor scrapes /metrics from vici namespace
# ---------------------------------------------------------------------------


class TestOBS02ServiceMonitor:
    """Verify prometheus.py defines a ServiceMonitor CustomResource targeting the
    vici namespace, scraping /metrics on port http with selector app=vici.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source("prometheus.py")

    def test_servicemonitor_custom_resource_defined(self) -> None:
        """A CustomResource with kind='ServiceMonitor' must be defined."""
        assert (
            'kind="ServiceMonitor"' in self.source
            or "kind='ServiceMonitor'" in self.source
        ), "prometheus.py must define a ServiceMonitor CustomResource"
        assert (
            'api_version="monitoring.coreos.com/v1"' in self.source
            or "api_version='monitoring.coreos.com/v1'" in self.source
        ), "ServiceMonitor must use api_version monitoring.coreos.com/v1"

    def test_servicemonitor_targets_vici_namespace(self) -> None:
        """ServiceMonitor must be created in the vici namespace."""
        assert 'namespace="vici"' in self.source or "namespace='vici'" in self.source, (
            "ServiceMonitor must target the vici namespace"
        )

    def test_servicemonitor_scrapes_metrics_path(self) -> None:
        """ServiceMonitor endpoint must specify path /metrics."""
        assert (
            '"path": "/metrics"' in self.source or "'path': '/metrics'" in self.source
        ), "ServiceMonitor endpoint must scrape /metrics path"

    def test_servicemonitor_uses_http_port(self) -> None:
        """ServiceMonitor endpoint must target port named 'http'."""
        assert '"port": "http"' in self.source or "'port': 'http'" in self.source, (
            "ServiceMonitor endpoint must target port 'http'"
        )

    def test_servicemonitor_selector_matches_app_vici(self) -> None:
        """ServiceMonitor selector must match label app=vici."""
        assert '"app": "vici"' in self.source or "'app': 'vici'" in self.source, (
            "ServiceMonitor matchLabels must include app=vici"
        )


# ---------------------------------------------------------------------------
# OBS-03: kube-prometheus-stack Helm release with Grafana dashboards and Jaeger
# ---------------------------------------------------------------------------


class TestOBS03GrafanaStack:
    """Verify prometheus.py defines the kube-prometheus-stack Helm release with
    Grafana sidecar dashboards enabled, Jaeger as an additional datasource, and
    all GKE Autopilot incompatible components disabled.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source("prometheus.py")

    def test_kube_prometheus_stack_helm_release_defined(self) -> None:
        """A Helm Release for kube-prometheus-stack must be defined."""
        assert (
            'chart="kube-prometheus-stack"' in self.source
            or "chart='kube-prometheus-stack'" in self.source
        ), "prometheus.py must define a kube-prometheus-stack Helm Release"
        tree = ast.parse(self.source)
        release_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "Release":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        release_calls.append(node.args[0].value)
        assert "kube-prometheus-stack" in release_calls, (
            f"Expected kube-prometheus-stack Helm Release, found: {release_calls}"
        )

    def test_grafana_sidecar_dashboards_enabled(self) -> None:
        """Grafana sidecar dashboard provisioner must be enabled in Helm values."""
        assert '"enabled": True' in self.source or "'enabled': True" in self.source, (
            "Grafana sidecar dashboards must be enabled (enabled: True)"
        )
        assert '"dashboards"' in self.source or "'dashboards'" in self.source, (
            "Grafana sidecar dashboards key must be present in Helm values"
        )

    def test_jaeger_datasource_configured_in_additional_datasources(self) -> None:
        """Jaeger must appear as an additionalDataSources entry in Grafana values."""
        assert (
            '"additionalDataSources"' in self.source
            or "'additionalDataSources'" in self.source
        ), "additionalDataSources must be configured in Grafana Helm values"
        assert '"type": "jaeger"' in self.source or "'type': 'jaeger'" in self.source, (
            "Jaeger datasource must have type 'jaeger'"
        )

    def test_gke_autopilot_node_exporter_disabled(self) -> None:
        """nodeExporter must be disabled for GKE Autopilot compatibility."""
        assert (
            '"nodeExporter": {"enabled": False}' in self.source
            or "'nodeExporter': {'enabled': False}" in self.source
        ), "nodeExporter must be disabled for GKE Autopilot"

    def test_gke_autopilot_kube_controller_manager_disabled(self) -> None:
        """kubeControllerManager must be disabled for GKE Autopilot compatibility."""
        assert (
            '"kubeControllerManager": {"enabled": False}' in self.source
            or "'kubeControllerManager': {'enabled': False}" in self.source
        ), "kubeControllerManager must be disabled for GKE Autopilot"

    def test_gke_autopilot_kube_scheduler_disabled(self) -> None:
        """kubeScheduler must be disabled for GKE Autopilot compatibility."""
        assert (
            '"kubeScheduler": {"enabled": False}' in self.source
            or "'kubeScheduler': {'enabled': False}" in self.source
        ), "kubeScheduler must be disabled for GKE Autopilot"

    def test_gke_autopilot_kube_etcd_disabled(self) -> None:
        """kubeEtcd must be disabled for GKE Autopilot compatibility."""
        assert (
            '"kubeEtcd": {"enabled": False}' in self.source
            or "'kubeEtcd': {'enabled': False}" in self.source
        ), "kubeEtcd must be disabled for GKE Autopilot"

    def test_gke_autopilot_kube_proxy_disabled(self) -> None:
        """kubeProxy must be disabled for GKE Autopilot compatibility."""
        assert (
            '"kubeProxy": {"enabled": False}' in self.source
            or "'kubeProxy': {'enabled': False}" in self.source
        ), "kubeProxy must be disabled for GKE Autopilot"

    def test_gke_autopilot_core_dns_disabled(self) -> None:
        """coreDns must be disabled for GKE Autopilot compatibility."""
        assert (
            '"coreDns": {"enabled": False}' in self.source
            or "'coreDns': {'enabled': False}" in self.source
        ), "coreDns must be disabled for GKE Autopilot"

    def test_gke_autopilot_kube_dns_disabled(self) -> None:
        """kubeDns must be disabled for GKE Autopilot compatibility."""
        assert (
            '"kubeDns": {"enabled": False}' in self.source
            or "'kubeDns': {'enabled': False}" in self.source
        ), "kubeDns must be disabled for GKE Autopilot"
