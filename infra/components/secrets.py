import pulumi
import pulumi_gcp as gcp
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces
from config import CLUSTER_NAME, ENV, PROJECT_ID, REGION

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ESO_CHART_VERSION = "1.3.2"
_ESO_REPO = "https://charts.external-secrets.io"
_REFRESH_INTERVAL = "1h"

# SECRETS-01: All secrets that must exist in GCP Secret Manager per env.
# Format: (slug, target-namespace, k8s-secret-name)
_SECRET_DEFINITIONS: list[tuple[str, str, str]] = [
    ("twilio-auth-token", "vici", "twilio-auth-token"),
    ("twilio-account-sid", "vici", "twilio-account-sid"),
    ("twilio-from-number", "vici", "twilio-from-number"),
    ("openai-api-key", "vici", "openai-api-key"),
    ("pinecone-api-key", "vici", "pinecone-api-key"),
    ("pinecone-index-host", "vici", "pinecone-index-host"),
    ("braintrust-api-key", "vici", "braintrust-api-key"),
    ("database-url", "vici", "database-url"),
    ("temporal-address", "vici", "temporal-address"),
    ("otel-exporter-otlp-endpoint", "vici", "otel-exporter-otlp-endpoint"),
    ("webhook-base-url", "vici", "webhook-base-url"),
]

# Namespaces that need a SecretStore (SECRETS-03)
_SECRETSTORE_NAMESPACES = ["vici", "temporal", "observability"]

# KSA name per namespace for SecretStore WIF auth
_KSA_BY_NAMESPACE: dict[str, str] = {
    "vici": "vici-app",
    "temporal": "temporal-app",
    "observability": "observability-app",
}

# ---------------------------------------------------------------------------
# GCP Secret Manager resources (D-06, SECRETS-01)
# ---------------------------------------------------------------------------

sm_secrets: dict[str, gcp.secretmanager.Secret] = {}
for _slug, _ns, _ in _SECRET_DEFINITIONS:
    _secret_id = f"{ENV}-{_slug}"
    sm_secrets[_slug] = gcp.secretmanager.Secret(
        f"sm-{_slug}",
        project=PROJECT_ID,
        secret_id=_secret_id,
        replication=gcp.secretmanager.SecretReplicationArgs(
            auto=gcp.secretmanager.SecretReplicationAutoArgs(),
        ),
    )

# ---------------------------------------------------------------------------
# ESO Helm release (SECRETS-02)
# ---------------------------------------------------------------------------

eso_release = k8s.helm.v3.Release(
    "external-secrets",
    k8s.helm.v3.ReleaseArgs(
        chart="external-secrets",
        version=_ESO_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_ESO_REPO),
        namespace="external-secrets",
        create_namespace=False,
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["external-secrets"]],
    ),
)

# ---------------------------------------------------------------------------
# Observability namespace KSA (needed for SecretStore WIF serviceAccountRef)
# ---------------------------------------------------------------------------

observability_ksa = k8s.core.v1.ServiceAccount(
    "observability-app-ksa",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="observability-app",
        namespace="observability",
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["observability"]],
    ),
)

# ---------------------------------------------------------------------------
# Namespace-scoped SecretStores (SECRETS-03)
# ---------------------------------------------------------------------------

secret_stores: dict[str, k8s.apiextensions.CustomResource] = {}
for _ns in _SECRETSTORE_NAMESPACES:
    secret_stores[_ns] = k8s.apiextensions.CustomResource(
        f"secret-store-{_ns}",
        api_version="external-secrets.io/v1",
        kind="SecretStore",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="gcp-secret-manager",
            namespace=_ns,
        ),
        spec={
            "provider": {
                "gcpsm": {
                    "projectID": PROJECT_ID,
                    "auth": {
                        "workloadIdentity": {
                            "clusterLocation": REGION,
                            "clusterName": CLUSTER_NAME,
                            "serviceAccountRef": {
                                "name": _KSA_BY_NAMESPACE[_ns],
                            },
                        }
                    },
                }
            }
        },
        opts=ResourceOptions(
            provider=k8s_provider,
            depends_on=[eso_release, namespaces[_ns]],
            delete_before_replace=True,
        ),
    )

# ---------------------------------------------------------------------------
# ExternalSecret CRs (SECRETS-04)
# ---------------------------------------------------------------------------

external_secrets: dict[str, k8s.apiextensions.CustomResource] = {}
for _slug, _ns, _k8s_name in _SECRET_DEFINITIONS:
    external_secrets[_slug] = k8s.apiextensions.CustomResource(
        f"ext-secret-{_slug}",
        api_version="external-secrets.io/v1",
        kind="ExternalSecret",
        metadata=k8s.meta.v1.ObjectMetaArgs(name=_k8s_name, namespace=_ns),
        spec={
            "refreshInterval": _REFRESH_INTERVAL,
            "secretStoreRef": {"name": "gcp-secret-manager", "kind": "SecretStore"},
            "target": {"name": _k8s_name, "creationPolicy": "Owner"},
            "data": [
                {
                    "secretKey": _slug.upper().replace("-", "_"),
                    "remoteRef": {"key": f"{ENV}-{_slug}"},
                }
            ],
        },
        opts=ResourceOptions(
            provider=k8s_provider,
            depends_on=[secret_stores[_ns], sm_secrets[_slug]],
        ),
    )

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("eso_release_status", eso_release.status)
