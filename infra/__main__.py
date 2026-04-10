# infra/__main__.py
# Entry point for the vici-infra Pulumi program.
# Imports trigger resource registration. Exports surface values for CI and downstream stacks.

import pulumi

# Component imports — each module registers its resources on import.
# Order matters for readability but not for Pulumi dependency resolution
# (Pulumi builds its own DAG from ResourceOptions.depends_on).
from components.cluster import cluster  # noqa: F401 — registers cluster resource
from components.identity import app_gsa, ci_push_sa, wi_binding  # noqa: F401
from components.registry import registry, registry_url  # noqa: F401
from components.namespaces import namespaces  # noqa: F401
from components.database import app_db_instance, temporal_db_instance  # noqa: F401
from components.iam import temporal_gsa, vici_app_ksa, temporal_app_ksa  # noqa: F401
from components.secrets import eso_release, secret_stores, external_secrets  # noqa: F401
from components.migration import migration_job  # noqa: F401
from components.opensearch import opensearch_release  # noqa: F401
from components.temporal import temporal_schema_job, temporal_release  # noqa: F401
from components.jaeger import jaeger_collector_deployment, jaeger_query_deployment  # noqa: F401
from components.prometheus import kube_prometheus_release, fastapi_service_monitor  # noqa: F401
from components.app import app_deployment, app_service, app_hpa  # noqa: F401
from components.certmanager import certmanager_release  # noqa: F401
from components.ingress import vici_ingress, webhook_base_url_version  # noqa: F401

# All pulumi.export() calls are in their respective component files.
# Add cross-component exports here if needed in the future.
