import pulumi_kubernetes as k8s
from pulumi import Output, ResourceOptions

from components.cluster import cluster

# Five namespaces required by INFRA-06.
# These names are canonical K8s ecosystem namespaces — do not alter.
REQUIRED_NAMESPACES: list[str] = [
    "vici",
    "temporal",
    "observability",
    "cert-manager",
    "external-secrets",
]


def _make_kubeconfig(cluster_resource: object) -> Output:
    """
    Constructs a kubeconfig dict from GKE cluster output values.

    Uses gke-gcloud-auth-plugin for authentication (required for GKE 1.26+).
    The plugin must be installed on any machine running this Pulumi program:
      gcloud components install gke-gcloud-auth-plugin
    """
    return Output.all(
        cluster_resource.name,
        cluster_resource.endpoint,
        cluster_resource.master_auth,
        cluster_resource.location,
    ).apply(
        lambda args: {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": args[2]["cluster_ca_certificate"],
                        "server": f"https://{args[1]}",
                    },
                    "name": args[0],
                }
            ],
            "contexts": [
                {
                    "context": {
                        "cluster": args[0],
                        "user": args[0],
                    },
                    "name": args[0],
                }
            ],
            "current-context": args[0],
            "kind": "Config",
            "users": [
                {
                    "name": args[0],
                    "user": {
                        "exec": {
                            "apiVersion": "client.authentication.k8s.io/v1beta1",
                            "command": "gke-gcloud-auth-plugin",
                            "installHint": (
                                "Install gke-gcloud-auth-plugin: "
                                "gcloud components install gke-gcloud-auth-plugin"
                            ),
                            "provideClusterInfo": True,
                        }
                    },
                }
            ],
        }
    )


k8s_provider = k8s.Provider(
    "k8s-provider",
    kubeconfig=_make_kubeconfig(cluster),
    opts=ResourceOptions(depends_on=[cluster]),
)

# Create each required namespace with the shared provider.
# depends_on=[cluster] on each namespace ensures the cluster API server
# is reachable before Pulumi attempts to create the namespace resource.
namespaces: dict[str, k8s.core.v1.Namespace] = {
    name: k8s.core.v1.Namespace(
        f"ns-{name}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name=name),
        opts=ResourceOptions(
            provider=k8s_provider,
            depends_on=[cluster],
        ),
    )
    for name in REQUIRED_NAMESPACES
}
