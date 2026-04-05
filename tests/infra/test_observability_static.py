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
        assert '"grafana_dashboard": "1"' in self.source or "'grafana_dashboard': '1'" in self.source, (
            "FastAPI dashboard ConfigMap must include labels={'grafana_dashboard': '1'}"
        )

    def test_temporal_configmap_has_grafana_dashboard_label(self) -> None:
        # Both ConfigMaps use the same label dict; count occurrences to ensure
        # *two* ConfigMaps carry the label (FastAPI + Temporal).
        count = self.source.count('"grafana_dashboard"') + self.source.count("'grafana_dashboard'")
        assert count >= 2, (
            f"Expected at least 2 ConfigMaps with grafana_dashboard label, found {count}"
        )

    def test_grafana_sidecar_label_matches_configmap_label(self) -> None:
        """The Helm values sidecar label must match the ConfigMap labels."""
        assert '"label": "grafana_dashboard"' in self.source or "'label': 'grafana_dashboard'" in self.source, (
            "Grafana sidecar config must reference 'grafana_dashboard' as the label key"
        )
        assert '"labelValue": "1"' in self.source or "'labelValue': '1'" in self.source, (
            "Grafana sidecar labelValue must be '1'"
        )

    def test_configmaps_target_observability_namespace(self) -> None:
        """Both dashboard ConfigMaps must be in the observability namespace."""
        # The namespace appears in ObjectMetaArgs for each ConfigMap
        lines = self.source.splitlines()
        ns_hits = [
            i for i, line in enumerate(lines)
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
                            c.value for c in elt.elts
                            if isinstance(c, ast.Constant)
                        ]
                        if "otel-exporter-otlp-endpoint" in values:
                            # Tuple format: (slug, namespace, k8s-secret-name)
                            assert values[1] == "vici", (
                                f"otel-exporter-otlp-endpoint namespace must be 'vici', got '{values[1]}'"
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
                if isinstance(target, ast.Name) and target.id == "_SECRETSTORE_NAMESPACES":
                    assert isinstance(node.value, ast.List)
                    ns_values = [
                        c.value for c in node.value.elts
                        if isinstance(c, ast.Constant)
                    ]
                    assert "vici" in ns_values, (
                        f"vici must be in _SECRETSTORE_NAMESPACES, found {ns_values}"
                    )
                    return
        pytest.fail("Could not find _SECRETSTORE_NAMESPACES assignment")
