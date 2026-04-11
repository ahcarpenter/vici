import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Pinned to 2.x — OpenSearch 3.x breaks Temporal ES client (D-08)
_OPENSEARCH_CHART_VERSION = "2.37.0"
_OPENSEARCH_REPO = "https://opensearch-project.github.io/helm-charts/"
_OPENSEARCH_JAVA_OPTS = "-Xmx512m -Xms512m"
_OPENSEARCH_MEMORY_REQUEST = "1Gi"
_OPENSEARCH_MEMORY_LIMIT = "2Gi"
_OPENSEARCH_CPU_REQUEST = "500m"
_OPENSEARCH_CPU_LIMIT = "1"
_OPENSEARCH_STORAGE_SIZE = "10Gi"

_INDEX_TEMPLATE_JOB_BACKOFF_LIMIT = 0
_INDEX_TEMPLATE_JOB_TTL_SECONDS = 300
_CURL_IMAGE = "curlimages/curl:8.7.1"

# ---------------------------------------------------------------------------
# Importable service host constant (used by temporal.py and other components)
# ---------------------------------------------------------------------------

OPENSEARCH_SERVICE_HOST = "opensearch-cluster-master.observability.svc.cluster.local"

# ---------------------------------------------------------------------------
# OpenSearch Helm release (OBS-01, D-07, D-08)
# ---------------------------------------------------------------------------

opensearch_release = k8s.helm.v3.Release(
    "opensearch",
    k8s.helm.v3.ReleaseArgs(
        chart="opensearch",
        version=_OPENSEARCH_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_OPENSEARCH_REPO),
        namespace="observability",
        create_namespace=False,
        values={
            "singleNode": True,
            "replicas": 1,
            "opensearchJavaOpts": _OPENSEARCH_JAVA_OPTS,
            "resources": {
                "requests": {
                    "cpu": _OPENSEARCH_CPU_REQUEST,
                    "memory": _OPENSEARCH_MEMORY_REQUEST,
                },
                "limits": {
                    "cpu": _OPENSEARCH_CPU_LIMIT,
                    "memory": _OPENSEARCH_MEMORY_LIMIT,
                },
            },
            "persistence": {
                "enabled": True,
                "size": _OPENSEARCH_STORAGE_SIZE,
            },
            "config": {
                "opensearch.yml": "plugins.security.disabled: true\n",
            },
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["observability"]],
    ),
)

# ---------------------------------------------------------------------------
# Index template Job — sets number_of_replicas: 0 for single-node safety (D-07/OBS-01)
# ---------------------------------------------------------------------------

_OPENSEARCH_HEALTH_URL = "http://opensearch-cluster-master:9200/_cluster/health"
_OPENSEARCH_TEMPLATE_URL = (
    "http://opensearch-cluster-master:9200/_index_template/single_node_defaults"
)
_OPENSEARCH_TEMPLATE_BODY = (
    '{"index_patterns":["*"],'
    '"template":{"settings":{"number_of_replicas":0}},'
    '"priority":1}'
)
_INDEX_TEMPLATE_ARGS = (
    f"until curl -sf {_OPENSEARCH_HEALTH_URL}; do sleep 5; done && "
    f"curl -X PUT {_OPENSEARCH_TEMPLATE_URL} "
    "-H 'Content-Type: application/json' "
    f"-d '{_OPENSEARCH_TEMPLATE_BODY}'"
)

opensearch_index_template_job = k8s.batch.v1.Job(
    "opensearch-index-template",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="opensearch-index-template",
        namespace="observability",
    ),
    spec=k8s.batch.v1.JobSpecArgs(
        backoff_limit=_INDEX_TEMPLATE_JOB_BACKOFF_LIMIT,
        ttl_seconds_after_finished=_INDEX_TEMPLATE_JOB_TTL_SECONDS,
        template=k8s.core.v1.PodTemplateSpecArgs(
            spec=k8s.core.v1.PodSpecArgs(
                restart_policy="Never",
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="index-template",
                        image=_CURL_IMAGE,
                        command=["sh", "-c"],
                        args=[_INDEX_TEMPLATE_ARGS],
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={"cpu": "50m", "memory": "64Mi"},
                            limits={"cpu": "100m", "memory": "128Mi"},
                        ),
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[opensearch_release],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("opensearch_service", f"{OPENSEARCH_SERVICE_HOST}:9200")
