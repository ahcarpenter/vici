import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.database import app_db_instance
from components.iam import vici_app_ksa
from components.migration import migration_job
from components.namespaces import k8s_provider, namespaces
from components.registry import registry_url
from components.secrets import external_secrets
from config import ENV

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
_AUTH_PROXY_RUN_AS_USER = 65532
_SOCKET_MOUNT_PATH = "/cloudsql"
_VOLUME_NAME = "cloudsql-socket"
_APP_PORT = 8000
_APP_MIN_REPLICAS = 1
_APP_MAX_REPLICAS = 3
_CPU_TARGET_UTILIZATION = 70
_READINESS_INITIAL_DELAY = 15
_READINESS_PERIOD = 10
_READINESS_FAILURE_THRESHOLD = 3
_LIVENESS_INITIAL_DELAY = 30
_LIVENESS_PERIOD = 30
_LIVENESS_FAILURE_THRESHOLD = 3
_CPU_REQUEST = "250m"
_MEMORY_REQUEST = "512Mi"
_CPU_LIMIT = "500m"
_MEMORY_LIMIT = "1Gi"
_AUTH_PROXY_CPU_REQUEST = "100m"
_AUTH_PROXY_MEMORY_REQUEST = "256Mi"
_AUTH_PROXY_CPU_LIMIT = "200m"
_AUTH_PROXY_MEMORY_LIMIT = "512Mi"

# All 11 ExternalSecret-generated K8s Secrets available to the app container
_ENV_FROM_SOURCES = [
    "twilio-auth-token",
    "twilio-account-sid",
    "twilio-from-number",
    "openai-api-key",
    "pinecone-api-key",
    "pinecone-index-host",
    "braintrust-api-key",
    "database-url",
    "temporal-host",
    "otel-exporter-otlp-endpoint",
    "webhook-base-url",
]

# ---------------------------------------------------------------------------
# FastAPI Deployment with Cloud SQL Auth Proxy native sidecar (D-17, APP-01)
# ---------------------------------------------------------------------------

app_deployment = k8s.apps.v1.Deployment(
    "vici-app",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-app",
        namespace="vici",
        labels={"app": "vici"},
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels={"app": "vici"},
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels={"app": "vici"},
            ),
            spec=k8s.core.v1.PodSpecArgs(
                service_account_name="vici-app",
                volumes=[
                    k8s.core.v1.VolumeArgs(
                        name=_VOLUME_NAME,
                        empty_dir=k8s.core.v1.EmptyDirVolumeSourceArgs(),
                    ),
                ],
                init_containers=[
                    k8s.core.v1.ContainerArgs(
                        name="cloud-sql-proxy",
                        image=_AUTH_PROXY_IMAGE,
                        restart_policy="Always",  # Native sidecar (K8s 1.28+)
                        args=[
                            "--structured-logs",
                            "--private-ip",
                            pulumi.Output.concat(
                                "--unix-socket=",
                                _SOCKET_MOUNT_PATH,
                            ),
                            app_db_instance.connection_name,
                        ],
                        security_context=k8s.core.v1.SecurityContextArgs(
                            run_as_non_root=True,
                            run_as_user=_AUTH_PROXY_RUN_AS_USER,
                        ),
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={
                                "cpu": _AUTH_PROXY_CPU_REQUEST,
                                "memory": _AUTH_PROXY_MEMORY_REQUEST,
                            },
                            limits={
                                "cpu": _AUTH_PROXY_CPU_LIMIT,
                                "memory": _AUTH_PROXY_MEMORY_LIMIT,
                            },
                        ),
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name=_VOLUME_NAME,
                                mount_path=_SOCKET_MOUNT_PATH,
                            ),
                        ],
                    ),
                ],
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="vici-app",
                        image=pulumi.Output.concat(registry_url, "/vici:", ENV),
                        ports=[
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_APP_PORT,
                                name="http",
                            ),
                        ],
                        env_from=[
                            k8s.core.v1.EnvFromSourceArgs(
                                secret_ref=k8s.core.v1.SecretEnvSourceArgs(name=slug),
                            )
                            for slug in _ENV_FROM_SOURCES
                        ],
                        readiness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path="/readyz",
                                port=_APP_PORT,
                            ),
                            initial_delay_seconds=_READINESS_INITIAL_DELAY,
                            period_seconds=_READINESS_PERIOD,
                            failure_threshold=_READINESS_FAILURE_THRESHOLD,
                        ),
                        liveness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path="/health",
                                port=_APP_PORT,
                            ),
                            initial_delay_seconds=_LIVENESS_INITIAL_DELAY,
                            period_seconds=_LIVENESS_PERIOD,
                            failure_threshold=_LIVENESS_FAILURE_THRESHOLD,
                        ),
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={
                                "cpu": _CPU_REQUEST,
                                "memory": _MEMORY_REQUEST,
                            },
                            limits={
                                "cpu": _CPU_LIMIT,
                                "memory": _MEMORY_LIMIT,
                            },
                        ),
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name=_VOLUME_NAME,
                                mount_path=_SOCKET_MOUNT_PATH,
                            ),
                        ],
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            app_db_instance,
            migration_job,
            vici_app_ksa,
            namespaces["vici"],
            *[external_secrets[slug] for slug in _ENV_FROM_SOURCES],
        ],
    ),
)

# ---------------------------------------------------------------------------
# ClusterIP Service — exposes the app for GKE Ingress and Prometheus scraping
# Labels must match fastapi_service_monitor selector (app: vici) from Phase 4
# ---------------------------------------------------------------------------

app_service = k8s.core.v1.Service(
    "vici-app-service",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-app",
        namespace="vici",
        labels={"app": "vici"},
    ),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="ClusterIP",
        selector={"app": "vici"},
        ports=[
            k8s.core.v1.ServicePortArgs(
                name="http",
                port=_APP_PORT,
                target_port=_APP_PORT,
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[app_deployment],
    ),
)

# ---------------------------------------------------------------------------
# HPA — auto-scales vici-app between 1 and 3 replicas on CPU 70% (D-19, APP-03)
# Uses autoscaling/v2 (v1 is deprecated)
# ---------------------------------------------------------------------------

app_hpa = k8s.autoscaling.v2.HorizontalPodAutoscaler(
    "vici-app-hpa",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-app",
        namespace="vici",
    ),
    spec=k8s.autoscaling.v2.HorizontalPodAutoscalerSpecArgs(
        scale_target_ref=k8s.autoscaling.v2.CrossVersionObjectReferenceArgs(
            api_version="apps/v1",
            kind="Deployment",
            name="vici-app",
        ),
        min_replicas=_APP_MIN_REPLICAS,
        max_replicas=_APP_MAX_REPLICAS,
        metrics=[
            k8s.autoscaling.v2.MetricSpecArgs(
                type="Resource",
                resource=k8s.autoscaling.v2.ResourceMetricSourceArgs(
                    name="cpu",
                    target=k8s.autoscaling.v2.MetricTargetArgs(
                        type="Utilization",
                        average_utilization=_CPU_TARGET_UTILIZATION,
                    ),
                ),
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[app_deployment],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("app_deployment_name", app_deployment.metadata.apply(lambda m: m.name))
pulumi.export("app_service_name", app_service.metadata.apply(lambda m: m.name))
