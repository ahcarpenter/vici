import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.database import temporal_db_instance
from components.iam import temporal_app_ksa, temporal_gsa
from components.namespaces import k8s_provider, namespaces
from components.opensearch import OPENSEARCH_SERVICE_HOST, opensearch_release
from config import ENV

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
_AUTH_PROXY_RUN_AS_USER = 65532
# D-11: pin admin-tools to match Temporal server chart version
_ADMIN_TOOLS_IMAGE = "temporalio/admin-tools:1.27.2"
_SCHEMA_JOB_BACKOFF_LIMIT = 0  # D-12: fail fast, no retries
_SCHEMA_JOB_TTL_SECONDS = 300  # Clean up after 5 minutes

_TEMPORAL_CHART_VERSION = "0.74.0"
_TEMPORAL_REPO = "https://go.temporal.io/helm-charts"
# D-05: PERMANENT — numHistoryShards cannot change after first deploy
_TEMPORAL_HISTORY_SHARDS = 512

_OPENSEARCH_VISIBILITY_PORT = 9200

# ---------------------------------------------------------------------------
# Temporal schema migration Job (TCP mode Auth Proxy)
# ---------------------------------------------------------------------------
#
# Research Q1 resolution: temporal-sql-tool uses --ep for host and -p for port.
# Auth Proxy runs in TCP mode (--port=5432); tool connects to localhost:5432.
# No unix socket volume needed for TCP mode.

_SQL_TOOL = "temporal-sql-tool --plugin postgres12 --ep localhost -p 5432"
_SCHEMA_BASE = "/etc/temporal/schema/postgresql/v12"

_SCHEMA_COMMANDS = " && ".join(
    [
        f"{_SQL_TOOL} --db temporal create-database || true",
        f"{_SQL_TOOL} --db temporal setup-schema -v 0.0",
        (
            f"{_SQL_TOOL} --db temporal update-schema"
            f" -d {_SCHEMA_BASE}/temporal/versioned"
        ),
        f"{_SQL_TOOL} --db temporal_visibility create-database || true",
        f"{_SQL_TOOL} --db temporal_visibility setup-schema -v 0.0",
        (
            f"{_SQL_TOOL} --db temporal_visibility update-schema"
            f" -d {_SCHEMA_BASE}/visibility/versioned"
        ),
    ]
)

temporal_schema_job = k8s.batch.v1.Job(
    "temporal-schema-migration",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name=f"temporal-schema-migration-{ENV}",
        namespace="temporal",
    ),
    spec=k8s.batch.v1.JobSpecArgs(
        backoff_limit=_SCHEMA_JOB_BACKOFF_LIMIT,
        ttl_seconds_after_finished=_SCHEMA_JOB_TTL_SECONDS,
        template=k8s.core.v1.PodTemplateSpecArgs(
            spec=k8s.core.v1.PodSpecArgs(
                service_account_name="temporal-app",
                restart_policy="Never",
                init_containers=[
                    k8s.core.v1.ContainerArgs(
                        name="cloud-sql-proxy",
                        image=_AUTH_PROXY_IMAGE,
                        restart_policy="Always",  # Native sidecar (K8s 1.28+)
                        args=[
                            "--structured-logs",
                            "--port=5432",
                            temporal_db_instance.connection_name,
                        ],
                        security_context=k8s.core.v1.SecurityContextArgs(
                            run_as_non_root=True,
                            run_as_user=_AUTH_PROXY_RUN_AS_USER,
                        ),
                    ),
                ],
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="temporal-schema-migration",
                        image=_ADMIN_TOOLS_IMAGE,
                        command=["sh", "-c"],
                        args=[_SCHEMA_COMMANDS],
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            temporal_db_instance,
            temporal_app_ksa,
            namespaces["temporal"],
        ],
    ),
)

# ---------------------------------------------------------------------------
# Temporal Helm release
# ---------------------------------------------------------------------------
#
# Research Q2 resolution: server.sidecarContainers injects the Auth Proxy
# into all server component pods (frontend, history, matching, worker).
# Pulumi auto-resolves Output values embedded in the Helm values dict.

temporal_release = k8s.helm.v3.Release(
    "temporal",
    k8s.helm.v3.ReleaseArgs(
        chart="temporal",
        version=_TEMPORAL_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_TEMPORAL_REPO),
        namespace="temporal",
        create_namespace=False,
        values={
            # D-02: Disable all bundled sub-charts — we supply our own.
            "cassandra": {"enabled": False},
            "elasticsearch": {"enabled": False},
            "prometheus": {"enabled": False},
            "grafana": {"enabled": False},
            "server": {
                "config": {
                    "persistence": {
                        "numHistoryShards": _TEMPORAL_HISTORY_SHARDS,
                        "defaultStore": "default",
                        "visibilityStore": "visibility",
                        "datastores": {
                            "default": {
                                "sql": {
                                    "pluginName": "postgres12",  # D-03
                                    "driverName": "postgres12",
                                    "databaseName": "temporal",
                                    # Auth Proxy TCP mode
                                    "connectAddr": "127.0.0.1:5432",
                                    "connectProtocol": "tcp",
                                    # IAM DB user via Workload Identity
                                    "user": temporal_gsa.email.apply(
                                        lambda e: (
                                            e.split("@")[0]
                                            + "@"
                                            + e.split("@")[1].replace(
                                                ".iam.gserviceaccount.com",
                                                ".iam",
                                            )
                                        )
                                    ),
                                }
                            },
                            "visibility": {
                                "elasticsearch": {
                                    # OpenSearch 2.x exposes ES v7 compat API
                                    "version": "v7",
                                    "scheme": "http",
                                    "host": (
                                        f"{OPENSEARCH_SERVICE_HOST}"
                                        f":{_OPENSEARCH_VISIBILITY_PORT}"
                                    ),
                                    "logLevel": "error",
                                    "indices": {
                                        "visibility": "temporal_visibility_v1",
                                    },
                                }
                            },
                        },
                    },
                },
                # Inject Auth Proxy into all Temporal server component pods.
                "sidecarContainers": [
                    {
                        "name": "cloud-sql-proxy",
                        "image": _AUTH_PROXY_IMAGE,
                        "args": [
                            "--structured-logs",
                            "--port=5432",
                            temporal_db_instance.connection_name,
                        ],
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": _AUTH_PROXY_RUN_AS_USER,
                        },
                    },
                ],
            },
            # D-13/TEMPORAL-06: UI enabled as ClusterIP (no external Ingress yet)
            "web": {
                "enabled": True,
                "service": {"type": "ClusterIP"},
            },
            "admintools": {"enabled": True},
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            temporal_schema_job,
            opensearch_release,
            temporal_app_ksa,
            namespaces["temporal"],
        ],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export(
    "temporal_frontend_service",
    "temporal-frontend.temporal.svc.cluster.local:7233",
)
pulumi.export(
    "opensearch_visibility_host",
    f"{OPENSEARCH_SERVICE_HOST}:{_OPENSEARCH_VISIBILITY_PORT}",
)
