import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_CERTMANAGER_CHART_VERSION = "v1.20.0"
_CERTMANAGER_REPO = "https://charts.jetstack.io"

# ---------------------------------------------------------------------------
# cert-manager Helm release (D-12)
# Installs cert-manager in the cert-manager namespace with CRDs enabled.
# CRDs are required before Issuer/Certificate resources can be created.
# ---------------------------------------------------------------------------

certmanager_release = k8s.helm.v3.Release(
    "cert-manager",
    k8s.helm.v3.ReleaseArgs(
        chart="cert-manager",
        version=_CERTMANAGER_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_CERTMANAGER_REPO),
        namespace="cert-manager",
        create_namespace=False,
        values={
            "crds": {"enabled": True},
            "global": {
                "leaderElection": {
                    "namespace": "cert-manager",
                },
            },
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["cert-manager"]],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("certmanager_chart_version", _CERTMANAGER_CHART_VERSION)
