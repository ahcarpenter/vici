"""Static assertions for Phase 6 infra best-practice audit and edge-case hardening.

These tests parse the Pulumi Python source files directly to verify that
infrastructure definitions satisfy all 5 Phase 6 success criteria without
requiring a live cluster or Pulumi runtime.

SC-1: protect=True on all stateful resources
SC-2: Default-deny NetworkPolicy in all 5 namespaces
SC-3: Temporal credentials via ESO (existingSecret)
SC-4: PodDisruptionBudgets for staging/prod
SC-5: OPERATIONS.md runbook with required sections
"""

import pathlib
import re

import pytest

INFRA_DIR = pathlib.Path(__file__).resolve().parents[2] / "infra" / "components"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_source(filename: str) -> str:
    path = INFRA_DIR / filename
    assert path.exists(), f"Expected {path} to exist"
    return path.read_text()


# ---------------------------------------------------------------------------
# SC-1: protect=True on all stateful resources
# ---------------------------------------------------------------------------


class TestProtect:
    """Verify protect=True is set on cluster, both Cloud SQL instances,
    Artifact Registry, and GCS state bucket.
    """

    def test_cluster_has_protect_true(self) -> None:
        """cluster.py must include protect=True in its ResourceOptions."""
        source = _read_source("cluster.py")
        assert "protect=True" in source, (
            "cluster.py must set protect=True in the cluster ResourceOptions"
        )

    def test_app_db_has_protect_true(self) -> None:
        """database.py must include protect=True at least twice (app + temporal)."""
        source = _read_source("database.py")
        count = source.count("protect=True")
        assert count >= 2, (
            f"database.py must set protect=True on both Cloud SQL instances "
            f"(expected >= 2, found {count})"
        )

    def test_temporal_db_has_protect_true(self) -> None:
        """database.py protect=True count covers the temporal instance."""
        source = _read_source("database.py")
        count = source.count("protect=True")
        assert count >= 2, (
            f"database.py must set protect=True on the temporal instance "
            f"(expected >= 2 total, found {count})"
        )

    def test_registry_has_protect_true(self) -> None:
        """registry.py must include protect=True in its ResourceOptions."""
        source = _read_source("registry.py")
        assert "protect=True" in source, (
            "registry.py must set protect=True in the Artifact Registry ResourceOptions"
        )

    def test_state_bucket_has_protect_true(self) -> None:
        """state_bucket.py must exist and include protect=True."""
        source = _read_source("state_bucket.py")
        assert "protect=True" in source, (
            "state_bucket.py must set protect=True in ResourceOptions"
        )

    def test_state_bucket_has_retain_on_delete(self) -> None:
        """state_bucket.py must include retain_on_delete=True as a safety net."""
        source = _read_source("state_bucket.py")
        assert "retain_on_delete=True" in source, (
            "state_bucket.py must set retain_on_delete=True in ResourceOptions"
        )


# ---------------------------------------------------------------------------
# SC-2: Default-deny NetworkPolicy for all 5 namespaces
# ---------------------------------------------------------------------------


class TestNetworkPolicy:
    """Verify network_policy.py defines default-deny-all + DNS egress allow
    for all 5 namespaces (vici, temporal, observability, cert-manager, external-secrets).
    """

    def test_network_policy_module_exists(self) -> None:
        """network_policy.py must exist in the components directory."""
        path = INFRA_DIR / "network_policy.py"
        assert path.exists(), f"Expected {path} to exist"

    def test_default_deny_all_five_namespaces(self) -> None:
        """All 5 namespaces must appear in network_policy.py, each with a default-deny-all policy."""
        source = _read_source("network_policy.py")
        for ns in ("vici", "temporal", "observability", "cert-manager", "external-secrets"):
            assert ns in source, (
                f"Namespace '{ns}' must appear in network_policy.py"
            )
        deny_count = source.count("default-deny-all")
        assert deny_count >= 5, (
            f"Expected at least 5 default-deny-all policies (one per namespace), "
            f"found {deny_count}"
        )

    def test_dns_egress_allowed(self) -> None:
        """All 5 namespaces must have an allow-dns-egress policy on port 53/UDP."""
        source = _read_source("network_policy.py")
        allow_dns_count = source.count("allow-dns-egress")
        assert allow_dns_count >= 5, (
            f"Expected at least 5 allow-dns-egress policies, found {allow_dns_count}"
        )
        assert "53" in source, "Port 53 must be specified in DNS egress allow rule"
        assert "UDP" in source, "Protocol UDP must be specified in DNS egress allow rule"

    def test_policy_types_include_ingress_and_egress(self) -> None:
        """Default-deny policies must block both Ingress and Egress directions."""
        source = _read_source("network_policy.py")
        assert "Ingress" in source, (
            "network_policy.py must include Ingress in policy_types"
        )
        assert "Egress" in source, (
            "network_policy.py must include Egress in policy_types"
        )


# ---------------------------------------------------------------------------
# SC-3: Temporal credentials via ESO (existingSecret)
# ---------------------------------------------------------------------------


class TestTemporalESO:
    """Verify Temporal DB credentials are sourced from ESO (not Pulumi stack secrets)
    and that the Helm chart uses existingSecret.
    """

    def test_temporal_py_no_require_secret_user(self) -> None:
        """temporal.py must NOT use cfg.require_secret for temporal_db_user."""
        source = _read_source("temporal.py")
        assert 'cfg.require_secret("temporal_db_user")' not in source, (
            "temporal.py must not read temporal_db_user from Pulumi stack secrets"
        )

    def test_temporal_py_no_require_secret_password(self) -> None:
        """temporal.py must NOT use cfg.require_secret for temporal_db_password."""
        source = _read_source("temporal.py")
        assert 'cfg.require_secret("temporal_db_password")' not in source, (
            "temporal.py must not read temporal_db_password from Pulumi stack secrets"
        )

    def test_temporal_py_uses_existing_secret(self) -> None:
        """temporal.py Helm values must reference existingSecret for DB credentials."""
        source = _read_source("temporal.py")
        assert "existingSecret" in source, (
            "temporal.py must use existingSecret in Helm values for Temporal DB credentials"
        )

    def test_secrets_py_has_temporal_db_password(self) -> None:
        """secrets.py must define the temporal-db-password secret."""
        source = _read_source("secrets.py")
        assert "temporal-db-password" in source, (
            "secrets.py must include temporal-db-password in secret definitions"
        )


# ---------------------------------------------------------------------------
# SC-4: PodDisruptionBudgets (staging + prod, 3 workloads)
# ---------------------------------------------------------------------------


class TestPDB:
    """Verify pdb.py exists, is env-conditional, and covers the 3 target workloads."""

    def test_pdb_module_exists(self) -> None:
        """pdb.py must exist in the components directory."""
        path = INFRA_DIR / "pdb.py"
        assert path.exists(), f"Expected {path} to exist"

    def test_pdb_env_conditional(self) -> None:
        """pdb.py must import ENV and conditionally apply PDBs for staging and prod."""
        source = _read_source("pdb.py")
        assert "ENV" in source, "pdb.py must import ENV from config"
        assert "staging" in source, "pdb.py must reference 'staging' in env conditional"
        assert "prod" in source, "pdb.py must reference 'prod' in env conditional"

    def test_pdb_three_workloads(self) -> None:
        """pdb.py must define PDBs for vici-app, temporal-frontend, and temporal-history."""
        source = _read_source("pdb.py")
        assert "vici-app" in source, (
            "pdb.py must include a PDB for vici-app"
        )
        assert "temporal-frontend" in source, (
            "pdb.py must include a PDB for temporal-frontend"
        )
        assert "temporal-history" in source, (
            "pdb.py must include a PDB for temporal-history"
        )

    def test_pdb_uses_min_available(self) -> None:
        """PDBs must use min_available (not max_unavailable)."""
        source = _read_source("pdb.py")
        assert "min_available" in source, (
            "pdb.py must use min_available in PodDisruptionBudgetSpec"
        )


# ---------------------------------------------------------------------------
# SC-5: OPERATIONS.md runbook with required sections
# ---------------------------------------------------------------------------


class TestOperationsDoc:
    """Verify infra/OPERATIONS.md exists and contains required operational runbook sections."""

    _OPS_DOC = pathlib.Path(__file__).resolve().parents[2] / "infra" / "OPERATIONS.md"

    def test_operations_md_exists(self) -> None:
        """infra/OPERATIONS.md must exist."""
        assert self._OPS_DOC.exists(), (
            f"Expected infra/OPERATIONS.md to exist at {self._OPS_DOC}"
        )

    def test_operations_md_has_cold_start(self) -> None:
        """OPERATIONS.md must include a cold-start ordering section."""
        content = self._OPS_DOC.read_text()
        assert re.search(r"cold.start", content, re.IGNORECASE), (
            "OPERATIONS.md must contain a cold-start section"
        )

    def test_operations_md_has_secret_rotation(self) -> None:
        """OPERATIONS.md must include a secret rotation section."""
        content = self._OPS_DOC.read_text()
        assert re.search(r"secret.rotation", content, re.IGNORECASE), (
            "OPERATIONS.md must contain a secret rotation section"
        )

    def test_operations_md_has_cluster_upgrade(self) -> None:
        """OPERATIONS.md must include a cluster upgrade section."""
        content = self._OPS_DOC.read_text()
        assert re.search(r"cluster.upgrade", content, re.IGNORECASE), (
            "OPERATIONS.md must contain a cluster upgrade section"
        )
