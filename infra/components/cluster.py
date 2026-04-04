import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions

from config import CLUSTER_NAME, ENV, PROJECT_ID, REGION

# GKE release channel per environment.
# REGULAR provides 1-2 version lag behind RAPID; suitable for non-prod.
# STABLE provides broader validation; required for prod.
_RELEASE_CHANNEL_BY_ENV = {
    "dev": "REGULAR",
    "staging": "REGULAR",
    "prod": "STABLE",
}
RELEASE_CHANNEL: str = _RELEASE_CHANNEL_BY_ENV.get(ENV, "REGULAR")

# Autopilot-managed fields that GCP mutates post-creation.
# Pulumi detects these as drift and proposes cluster replacement without this guard.
# Source: github.com/pulumi/pulumi-gcp/issues/1170
#
# NOTE: dns_config is NOT in this list. Set it explicitly below instead.
# Adding dns_config to ignore_changes would prevent intentional DNS changes
# from being applied in the future.
AUTOPILOT_VOLATILE_FIELDS: list[str] = [
    "vertical_pod_autoscaling",
    "node_config",
    "node_pool",
    "initial_node_count",
]

cluster = gcp.container.Cluster(
    "vici-cluster",
    name=CLUSTER_NAME,
    # Regional location is required for Autopilot.
    # Do NOT use a zonal location (e.g., "us-central1-a") — Autopilot is region-scoped.
    location=REGION,
    project=PROJECT_ID,
    enable_autopilot=True,

    # Required for Autopilot: GKE allocates pod and service CIDRs automatically.
    # Empty args object is sufficient; GKE fills in the CIDR ranges.
    ip_allocation_policy=gcp.container.ClusterIpAllocationPolicyArgs(),

    # Set dns_config explicitly to prevent GCP defaults from causing drift.
    # If this field is omitted, GCP silently applies CLOUD_DNS + CLUSTER_SCOPE +
    # cluster.local. Pulumi then sees the absence as a requested removal and
    # proposes cluster replacement. Setting it explicitly here keeps Pulumi in sync.
    dns_config=gcp.container.ClusterDnsConfigArgs(
        cluster_dns="CLOUD_DNS",
        cluster_dns_scope="CLUSTER_SCOPE",
        cluster_dns_domain="cluster.local",
    ),

    # Workload Identity enables pods to authenticate to GCP APIs using K8s
    # ServiceAccount annotations instead of static key files.
    # Format: "<project_id>.svc.id.goog"
    workload_identity_config=gcp.container.ClusterWorkloadIdentityConfigArgs(
        workload_pool=f"{PROJECT_ID}.svc.id.goog",
    ),

    release_channel=gcp.container.ClusterReleaseChannelArgs(
        channel=RELEASE_CHANNEL,
    ),

    # Prevent accidental cluster deletion via Pulumi destroy.
    # To intentionally destroy: set deletion_protection=False, run pulumi up,
    # then run pulumi destroy.
    deletion_protection=True,

    opts=ResourceOptions(
        ignore_changes=AUTOPILOT_VOLATILE_FIELDS,
    ),
)

# Export cluster outputs for consumption by other components
pulumi.export("cluster_name", cluster.name)
pulumi.export("cluster_endpoint", cluster.endpoint)
pulumi.export("cluster_location", cluster.location)
