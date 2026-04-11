import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions

from components.cluster import cluster
from config import PROJECT_ID

# GCP Service Account for the Vici FastAPI application.
# Pods annotated with this SA's email can call GCP APIs without key files.
# The K8s ServiceAccount annotation (iam.gke.io/gcp-service-account) is
# applied in Phase 2 during namespace/workload setup.
app_gsa = gcp.serviceaccount.Account(
    "app-gsa",
    project=PROJECT_ID,
    account_id="vici-app",
    display_name="Vici FastAPI application — GCP service account",
)

# GCP Service Account for CI image pushes.
# Used by GitHub Actions (via Workload Identity Federation) to push
# Docker images to Artifact Registry. IAM binding to the registry
# is created in components/registry.py alongside the registry resource.
ci_push_sa = gcp.serviceaccount.Account(
    "ci-push-sa",
    project=PROJECT_ID,
    account_id="vici-ci-push",
    display_name="Vici CI — Artifact Registry push",
)

# Workload Identity IAM binding: Kubernetes SA -> GCP SA.
# Allows pods running as the "vici-app" KSA in the "vici" namespace
# to impersonate app_gsa without mounting a key file.
#
# Member format: "serviceAccount:<project>.svc.id.goog[<namespace>/<ksa-name>]"
# The KSA "vici-app" in namespace "vici" must be annotated in Phase 2.
wi_binding = gcp.serviceaccount.IAMBinding(
    "app-wi-binding",
    service_account_id=app_gsa.name,
    role="roles/iam.workloadIdentityUser",
    members=[
        pulumi.Output.concat(
            "serviceAccount:",
            PROJECT_ID,
            ".svc.id.goog[vici/vici-app]",
        )
    ],
    # WIF pool (<project>.svc.id.goog) is created by GKE during cluster provisioning.
    # Must depend on cluster to avoid "Identity Pool does not exist" errors.
    opts=ResourceOptions(depends_on=[cluster]),
)

# Export service account emails for downstream reference
pulumi.export("app_gsa_email", app_gsa.email)
pulumi.export("ci_push_sa_email", ci_push_sa.email)
