import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces
from components.opensearch import OPENSEARCH_SERVICE_HOST, opensearch_index_template_job

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_JAEGER_IMAGE_TAG = "2.16.0"

_JAEGER_COLLECTOR_CPU_REQUEST = "250m"
_JAEGER_COLLECTOR_CPU_LIMIT = "500m"
_JAEGER_COLLECTOR_MEMORY_REQUEST = "256Mi"
_JAEGER_COLLECTOR_MEMORY_LIMIT = "512Mi"

_JAEGER_QUERY_CPU_REQUEST = "250m"
_JAEGER_QUERY_CPU_LIMIT = "500m"
_JAEGER_QUERY_MEMORY_REQUEST = "256Mi"
_JAEGER_QUERY_MEMORY_LIMIT = "512Mi"

_JAEGER_NAMESPACE = "observability"
_JAEGER_HEALTH_PORT = 13133
_JAEGER_HEALTH_PATH = "/status"
_JAEGER_OTLP_GRPC_PORT = 4317
_JAEGER_OTLP_HTTP_PORT = 4318
_JAEGER_QUERY_PORT = 16686
_JAEGER_LIVENESS_INITIAL_DELAY = 15
_JAEGER_LIVENESS_PERIOD = 10
_JAEGER_READINESS_INITIAL_DELAY = 5
_JAEGER_READINESS_PERIOD = 10

# ---------------------------------------------------------------------------
# Jaeger collector config (ported from jaeger/collector-config.yaml)
# ---------------------------------------------------------------------------

_JAEGER_COLLECTOR_CONFIG = f"""\
# Source: https://github.com/jaegertracing/jaeger/blob/main/cmd/jaeger/config-opensearch.yaml
service:
  extensions: [jaeger_storage, healthcheckv2]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    resource:
      service.name: jaeger-collector
    logs:
      level: info

extensions:
  healthcheckv2:
    use_v2: true
    http:
      endpoint: "0.0.0.0:13133"

  jaeger_storage:
    backends:
      main_storage:
        opensearch:
          server_urls:
            - http://{OPENSEARCH_SERVICE_HOST}:9200
          indices:
            index_prefix: "jaeger-main"
            spans:
              date_layout: "2006-01-02"
              rollover_frequency: "day"
              shards: 1
              replicas: 0

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"
      http:
        endpoint: "0.0.0.0:4318"

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage: main_storage
"""

# ---------------------------------------------------------------------------
# Jaeger query config (ported from jaeger/query-config.yaml)
# ---------------------------------------------------------------------------

_JAEGER_QUERY_CONFIG = f"""\
# Source: https://github.com/jaegertracing/jaeger/blob/main/cmd/jaeger/config-query.yaml
service:
  extensions: [jaeger_storage, jaeger_query, healthcheckv2]
  pipelines:
    traces:
      receivers: [nop]
      processors: [batch]
      exporters: [nop]
  telemetry:
    resource:
      service.name: jaeger-query
    logs:
      level: info

extensions:
  healthcheckv2:
    use_v2: true
    http:
      endpoint: "0.0.0.0:13133"

  jaeger_query:
    storage:
      traces: main_storage

  jaeger_storage:
    backends:
      main_storage:
        opensearch:
          server_urls:
            - http://{OPENSEARCH_SERVICE_HOST}:9200
          indices:
            index_prefix: "jaeger-main"
            spans:
              date_layout: "2006-01-02"
              rollover_frequency: "day"
              shards: 1
              replicas: 0

receivers:
  nop:

processors:
  batch:

exporters:
  nop:
"""

# ---------------------------------------------------------------------------
# ConfigMaps
# ---------------------------------------------------------------------------

jaeger_collector_configmap = k8s.core.v1.ConfigMap(
    "jaeger-collector-config",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-collector-config",
        namespace=_JAEGER_NAMESPACE,
    ),
    data={
        "config.yaml": _JAEGER_COLLECTOR_CONFIG,
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces[_JAEGER_NAMESPACE]],
    ),
)

jaeger_query_configmap = k8s.core.v1.ConfigMap(
    "jaeger-query-config",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-query-config",
        namespace=_JAEGER_NAMESPACE,
    ),
    data={
        "config.yaml": _JAEGER_QUERY_CONFIG,
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces[_JAEGER_NAMESPACE]],
    ),
)

# ---------------------------------------------------------------------------
# Jaeger collector Deployment
# ---------------------------------------------------------------------------

jaeger_collector_deployment = k8s.apps.v1.Deployment(
    "jaeger-collector",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-collector",
        namespace=_JAEGER_NAMESPACE,
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels={"app": "jaeger-collector"},
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels={"app": "jaeger-collector"},
            ),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="jaeger-collector",
                        image=f"jaegertracing/jaeger:{_JAEGER_IMAGE_TAG}",
                        args=["--config", "/etc/jaeger/config.yaml"],
                        ports=[
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_JAEGER_OTLP_GRPC_PORT,
                                name="otlp-grpc",
                            ),
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_JAEGER_OTLP_HTTP_PORT,
                                name="otlp-http",
                            ),
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_JAEGER_HEALTH_PORT,
                                name="health",
                            ),
                        ],
                        liveness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path=_JAEGER_HEALTH_PATH,
                                port=_JAEGER_HEALTH_PORT,
                            ),
                            initial_delay_seconds=_JAEGER_LIVENESS_INITIAL_DELAY,
                            period_seconds=_JAEGER_LIVENESS_PERIOD,
                        ),
                        readiness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path=_JAEGER_HEALTH_PATH,
                                port=_JAEGER_HEALTH_PORT,
                            ),
                            initial_delay_seconds=_JAEGER_READINESS_INITIAL_DELAY,
                            period_seconds=_JAEGER_READINESS_PERIOD,
                        ),
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={
                                "cpu": _JAEGER_COLLECTOR_CPU_REQUEST,
                                "memory": _JAEGER_COLLECTOR_MEMORY_REQUEST,
                            },
                            limits={
                                "cpu": _JAEGER_COLLECTOR_CPU_LIMIT,
                                "memory": _JAEGER_COLLECTOR_MEMORY_LIMIT,
                            },
                        ),
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name="jaeger-config",
                                mount_path="/etc/jaeger",
                            ),
                        ],
                    ),
                ],
                volumes=[
                    k8s.core.v1.VolumeArgs(
                        name="jaeger-config",
                        config_map=k8s.core.v1.ConfigMapVolumeSourceArgs(
                            name="jaeger-collector-config",
                        ),
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[jaeger_collector_configmap, opensearch_index_template_job],
    ),
)

# ---------------------------------------------------------------------------
# Jaeger query Deployment
# ---------------------------------------------------------------------------

jaeger_query_deployment = k8s.apps.v1.Deployment(
    "jaeger-query",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-query",
        namespace=_JAEGER_NAMESPACE,
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels={"app": "jaeger-query"},
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels={"app": "jaeger-query"},
            ),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="jaeger-query",
                        image=f"jaegertracing/jaeger:{_JAEGER_IMAGE_TAG}",
                        args=["--config", "/etc/jaeger/config.yaml"],
                        ports=[
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_JAEGER_QUERY_PORT,
                                name="http-query",
                            ),
                            k8s.core.v1.ContainerPortArgs(
                                container_port=_JAEGER_HEALTH_PORT,
                                name="health",
                            ),
                        ],
                        liveness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path=_JAEGER_HEALTH_PATH,
                                port=_JAEGER_HEALTH_PORT,
                            ),
                            initial_delay_seconds=_JAEGER_LIVENESS_INITIAL_DELAY,
                            period_seconds=_JAEGER_LIVENESS_PERIOD,
                        ),
                        readiness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path=_JAEGER_HEALTH_PATH,
                                port=_JAEGER_HEALTH_PORT,
                            ),
                            initial_delay_seconds=_JAEGER_READINESS_INITIAL_DELAY,
                            period_seconds=_JAEGER_READINESS_PERIOD,
                        ),
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={
                                "cpu": _JAEGER_QUERY_CPU_REQUEST,
                                "memory": _JAEGER_QUERY_MEMORY_REQUEST,
                            },
                            limits={
                                "cpu": _JAEGER_QUERY_CPU_LIMIT,
                                "memory": _JAEGER_QUERY_MEMORY_LIMIT,
                            },
                        ),
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name="jaeger-config",
                                mount_path="/etc/jaeger",
                            ),
                        ],
                    ),
                ],
                volumes=[
                    k8s.core.v1.VolumeArgs(
                        name="jaeger-config",
                        config_map=k8s.core.v1.ConfigMapVolumeSourceArgs(
                            name="jaeger-query-config",
                        ),
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[jaeger_query_configmap, opensearch_index_template_job],
    ),
)

# ---------------------------------------------------------------------------
# Jaeger collector Service (ClusterIP)
# ---------------------------------------------------------------------------

jaeger_collector_service = k8s.core.v1.Service(
    "jaeger-collector-svc",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-collector",
        namespace=_JAEGER_NAMESPACE,
    ),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="ClusterIP",
        selector={"app": "jaeger-collector"},
        ports=[
            k8s.core.v1.ServicePortArgs(
                name="otlp-grpc",
                port=_JAEGER_OTLP_GRPC_PORT,
                target_port=_JAEGER_OTLP_GRPC_PORT,
            ),
            k8s.core.v1.ServicePortArgs(
                name="otlp-http",
                port=_JAEGER_OTLP_HTTP_PORT,
                target_port=_JAEGER_OTLP_HTTP_PORT,
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[jaeger_collector_deployment],
    ),
)

# ---------------------------------------------------------------------------
# Jaeger query Service (ClusterIP)
# ---------------------------------------------------------------------------

jaeger_query_service = k8s.core.v1.Service(
    "jaeger-query-svc",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="jaeger-query",
        namespace=_JAEGER_NAMESPACE,
    ),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="ClusterIP",
        selector={"app": "jaeger-query"},
        ports=[
            k8s.core.v1.ServicePortArgs(
                name="http-query",
                port=_JAEGER_QUERY_PORT,
                target_port=_JAEGER_QUERY_PORT,
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[jaeger_query_deployment],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("jaeger_collector_service", "jaeger-collector.observability.svc.cluster.local")
pulumi.export("jaeger_query_service", "jaeger-query.observability.svc.cluster.local")
