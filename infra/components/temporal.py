import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.database import temporal_db_instance
from components.iam import temporal_app_ksa, temporal_gsa
from components.namespaces import k8s_provider, namespaces
from components.opensearch import OPENSEARCH_SERVICE_HOST, opensearch_release
from config import ENV, cfg

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
_AUTH_PROXY_RUN_AS_USER = 65532
# D-11: pin admin-tools to match Temporal server chart version (chart 0.74.0 = server 1.29.1)
_ADMIN_TOOLS_IMAGE = "temporalio/admin-tools:1.29.1-tctl-1.18"
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

_TEMPORAL_DB_USER = cfg.require_secret("temporal_db_user")
_TEMPORAL_DB_PASS = cfg.require_secret("temporal_db_password")

_SQL_TOOL_PREFIX = "temporal-sql-tool --plugin postgres12 --ep localhost -p 5432"
_SCHEMA_BASE = "/etc/temporal/schema/postgresql/v12"

_SCHEMA_COMMANDS = pulumi.Output.all(_TEMPORAL_DB_USER, _TEMPORAL_DB_PASS).apply(
    lambda creds: " && ".join(
        [
            f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal create-database || true",
            f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal setup-schema -v 0.0",
            (
                f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal update-schema"
                f" -d {_SCHEMA_BASE}/temporal/versioned"
            ),
            f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal_visibility create-database || true",
            f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal_visibility setup-schema -v 0.0",
            (
                f"{_SQL_TOOL_PREFIX} -u {creds[0]} --pw {creds[1]} --db temporal_visibility update-schema"
                f" -d {_SCHEMA_BASE}/visibility/versioned"
            ),
        ]
    )
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
                            "--private-ip",
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
            # Override chart release-hash prefix so services are named temporal-{component}
            "fullnameOverride": "temporal",
            # D-02: Disable bundled sub-charts — we supply our own dependencies.
            # cassandra.config.ports.db must be set even when disabled; chart references it.
            "cassandra": {"enabled": False, "config": {"ports": {"db": 9042}}},
            # OpenSearch exposes ES v7 compat API. Using elasticsearch.external=True
            # causes the chart to wire visibility through the top-level elasticsearch
            # block rather than needing a custom server.config.persistence.visibility.
            "elasticsearch": {
                "enabled": False,
                "external": True,
                "version": "v7",
                "scheme": "http",
                "host": OPENSEARCH_SERVICE_HOST,
                "port": _OPENSEARCH_VISIBILITY_PORT,
                "logLevel": "error",
                "visibilityIndex": "temporal_visibility_v1",
                "username": "",
                "password": "",
            },
            "prometheus": {"enabled": False},
            "grafana": {"enabled": False},
            "server": {
                "config": {
                    # numHistoryShards lives at config level, not under persistence.
                    # D-05: PERMANENT — cannot change after first deploy.
                    "numHistoryShards": _TEMPORAL_HISTORY_SHARDS,
                    "persistence": {
                        "defaultStore": "default",
                        "visibilityStore": "visibility",
                        # The chart's temporal.persistence.driver helper reads
                        # server.config.persistence.<store>.driver (not datastores).
                        # temporal.persistence.sql.driver reads sql.driver specifically.
                        "default": {
                            "driver": "sql",  # D-03
                            "sql": {
                                "driver": "postgres12",  # used by sql.driver helper
                                "database": "temporal",
                                "host": "127.0.0.1",  # Auth Proxy TCP mode
                                "port": 5432,
                                "user": _TEMPORAL_DB_USER,
                                "password": _TEMPORAL_DB_PASS,
                            },
                        },
                    },
                },
                # sprig configmap is rendered for Temporal server v1.30+.
                # setConfigFilePath sets TEMPORAL_SERVER_CONFIG_FILE_PATH env var which
                # maps to --config-file; the server loads the mounted sprig configmap
                # instead of the embedded config_template_embedded.yaml.
                "configMapsToMount": "sprig",
                "setConfigFilePath": True,
                # Cloud SQL Auth Proxy as native sidecar (K8s 1.29+, restartPolicy=Always).
                # Chart 0.74.0 does not support server.sidecarContainers — must use
                # additionalInitContainers with restartPolicy=Always instead.
                "additionalInitContainers": [
                    {
                        "name": "cloud-sql-proxy",
                        "image": _AUTH_PROXY_IMAGE,
                        "restartPolicy": "Always",
                        "args": [
                            "--structured-logs",
                            "--port=5432",
                            "--private-ip",
                            temporal_db_instance.connection_name,
                        ],
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": _AUTH_PROXY_RUN_AS_USER,
                        },
                    },
                ],
            },
            # D-14: chart uses top-level serviceAccount.name (not server.serviceAccountName).
            # create=False because we provision the KSA via temporal_app_ksa in iam.py.
            "serviceAccount": {
                "create": False,
                "name": "temporal-app",
            },
            # D-13/TEMPORAL-06: UI enabled as ClusterIP (no external Ingress yet)
            "web": {
                "enabled": True,
                "service": {"type": "ClusterIP"},
            },
            "admintools": {"enabled": True},
            # Disable chart's built-in schema jobs — we run our own.
            "schema": {
                "createDatabase": {"enabled": False},
                "setup": {"enabled": False},
                "update": {"enabled": False},
            },
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
