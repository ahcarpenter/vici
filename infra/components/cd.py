import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions

from components.cluster import (
    cluster,  # noqa: F401 — ensures cluster exists before WIF pool
)
from components.identity import ci_push_sa
from config import ENV, GITHUB_ORG, PROJECT_ID

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_WIF_POOL_ID = f"github-actions-{ENV}"
_WIF_PROVIDER_ID = "github"
_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

# ---------------------------------------------------------------------------
# Workload Identity Federation Pool
# ---------------------------------------------------------------------------
# Enables GitHub Actions OIDC tokens to be exchanged for short-lived GCP
# credentials. No static SA keys are required or created.

wif_pool = gcp.iam.WorkloadIdentityPool(
    "github-wif-pool",
    project=PROJECT_ID,
    workload_identity_pool_id=_WIF_POOL_ID,
    display_name=f"GitHub Actions ({ENV})",
)

# ---------------------------------------------------------------------------
# WIF OIDC Provider
# ---------------------------------------------------------------------------
# Maps GitHub OIDC token claims to Google subject attributes.
# attribute_condition scopes trust to this org only (T-05-10).

wif_provider = gcp.iam.WorkloadIdentityPoolProvider(
    "github-wif-provider",
    project=PROJECT_ID,
    workload_identity_pool_id=wif_pool.workload_identity_pool_id,
    workload_identity_pool_provider_id=_WIF_PROVIDER_ID,
    oidc=gcp.iam.WorkloadIdentityPoolProviderOidcArgs(
        issuer_uri=_GITHUB_OIDC_ISSUER,
    ),
    attribute_mapping={
        "google.subject": "assertion.sub",
        "attribute.actor": "assertion.actor",
        "attribute.repository": "assertion.repository",
        "attribute.repository_owner": "assertion.repository_owner",
    },
    attribute_condition=f"assertion.repository_owner == '{GITHUB_ORG}'",
    opts=ResourceOptions(depends_on=[wif_pool]),
)

# ---------------------------------------------------------------------------
# CI SA WIF IAM Binding
# ---------------------------------------------------------------------------
# Grants tokens from any repo in GITHUB_ORG/vici the ability to impersonate
# ci_push_sa. Scoped to a single repo path to minimize blast radius.

ci_wif_binding = gcp.serviceaccount.IAMBinding(
    "ci-wif-iam-binding",
    service_account_id=ci_push_sa.name,
    role="roles/iam.workloadIdentityUser",
    members=[
        pulumi.Output.concat(
            "principalSet://iam.googleapis.com/",
            wif_pool.name,
            "/attribute.repository/",
            GITHUB_ORG,
            "/vici",
        )
    ],
    opts=ResourceOptions(depends_on=[wif_pool]),
)

# ---------------------------------------------------------------------------
# CI SA additional IAM roles
# ---------------------------------------------------------------------------
# Minimum roles required for Pulumi CD:
#   roles/storage.objectAdmin  — read/write Pulumi GCS state backend
#   roles/container.developer  — deploy to GKE cluster (T-05-12)
#   roles/compute.viewer       — read Compute Engine resources (regions,
#                                InstanceGroupManagers, networks) that the
#                                pulumi-gcp provider needs for cluster refresh
#                                and drift detection on GKE node pools. GKE
#                                Autopilot surfaces are not fully covered by
#                                container.developer alone.
#
# roles/artifactregistry.writer is bound in registry.py alongside the registry.

ci_state_bucket_access = gcp.projects.IAMMember(
    "ci-sa-storage-admin",
    project=PROJECT_ID,
    role="roles/storage.objectAdmin",
    member=ci_push_sa.email.apply(lambda e: f"serviceAccount:{e}"),
)

ci_gke_access = gcp.projects.IAMMember(
    "ci-sa-container-developer",
    project=PROJECT_ID,
    role="roles/container.developer",
    member=ci_push_sa.email.apply(lambda e: f"serviceAccount:{e}"),
)

ci_compute_viewer = gcp.projects.IAMMember(
    "ci-sa-compute-viewer",
    project=PROJECT_ID,
    role="roles/compute.viewer",
    member=ci_push_sa.email.apply(lambda e: f"serviceAccount:{e}"),
)

# ---------------------------------------------------------------------------
# Stack outputs
# ---------------------------------------------------------------------------

pulumi.export("wif_pool_id", wif_pool.workload_identity_pool_id)
pulumi.export("wif_provider_name", wif_provider.name)
pulumi.export("ci_push_sa_email", ci_push_sa.email)
