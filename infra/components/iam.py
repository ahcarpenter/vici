import pulumi
import pulumi_gcp as gcp
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.cluster import cluster
from components.database import app_db_instance, temporal_db_instance  # noqa: F401
from components.identity import app_gsa
from components.namespaces import k8s_provider, namespaces
from config import PROJECT_ID

# -- Temporal GSA (D-13) ------------------------------------------------------

temporal_gsa = gcp.serviceaccount.Account(
    "temporal-gsa",
    project=PROJECT_ID,
    account_id="temporal-app",
    display_name="Temporal Server — GCP service account",
)

# -- Temporal WIF binding (D-14) -----------------------------------------------
# Allows pods running as the "temporal-app" KSA in the "temporal" namespace
# to impersonate temporal_gsa without mounting a key file.

temporal_wi_binding = gcp.serviceaccount.IAMBinding(
    "temporal-wi-binding",
    service_account_id=temporal_gsa.name,
    role="roles/iam.workloadIdentityUser",
    members=[
        pulumi.Output.concat(
            "serviceAccount:",
            PROJECT_ID,
            ".svc.id.goog[temporal/temporal-app]",
        )
    ],
    # WIF pool is created by GKE; must depend on cluster to avoid
    # "Identity Pool does not exist".
    opts=ResourceOptions(depends_on=[cluster]),
)

# -- vici-app GSA IAM roles (D-16) --------------------------------------------

app_gsa_cloudsql_client = gcp.projects.IAMMember(
    "app-gsa-cloudsql-client",
    project=PROJECT_ID,
    role="roles/cloudsql.client",
    member=app_gsa.email.apply(lambda e: f"serviceAccount:{e}"),
)

app_gsa_secret_accessor = gcp.projects.IAMMember(
    "app-gsa-secret-accessor",
    project=PROJECT_ID,
    role="roles/secretmanager.secretAccessor",
    member=app_gsa.email.apply(lambda e: f"serviceAccount:{e}"),
)

# -- temporal-app GSA IAM role (D-17) -----------------------------------------

temporal_gsa_cloudsql_client = gcp.projects.IAMMember(
    "temporal-gsa-cloudsql-client",
    project=PROJECT_ID,
    role="roles/cloudsql.client",
    member=temporal_gsa.email.apply(lambda e: f"serviceAccount:{e}"),
)

# -- KSA annotations (DB-03) — vici-app KSA in vici namespace -----------------

vici_app_ksa = k8s.core.v1.ServiceAccount(
    "vici-app-ksa",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-app",
        namespace="vici",
        annotations={"iam.gke.io/gcp-service-account": app_gsa.email},
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
)

# -- KSA for temporal namespace (D-14) ----------------------------------------

temporal_app_ksa = k8s.core.v1.ServiceAccount(
    "temporal-app-ksa",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="temporal-app",
        namespace="temporal",
        annotations={"iam.gke.io/gcp-service-account": temporal_gsa.email},
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["temporal"]]),
)

# -- Exports ------------------------------------------------------------------

pulumi.export("temporal_gsa_email", temporal_gsa.email)
