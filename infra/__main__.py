# infra/__main__.py
# Entry point for the vici-infra Pulumi program.
# Imports trigger resource registration. Exports surface values for CI and downstream stacks.  # noqa: E501


# Component imports — each module registers its resources on import.
# Order matters for readability but not for Pulumi dependency resolution
# (Pulumi builds its own DAG from ResourceOptions.depends_on).
from components.app import app_deployment, app_hpa, app_service  # noqa: F401
from components.cd import wif_pool, wif_provider  # noqa: F401
from components.certmanager import certmanager_release  # noqa: F401
from components.cluster import cluster  # noqa: F401 — registers cluster resource
from components.database import app_db_instance, temporal_db_instance  # noqa: F401
from components.iam import temporal_app_ksa, temporal_gsa, vici_app_ksa  # noqa: F401
from components.identity import app_gsa, ci_push_sa, wi_binding  # noqa: F401
from components.ingress import (  # noqa: F401
    prod_issuer,
    staging_issuer,
    vici_ingress,
    webhook_base_url_version,
)
from components.jaeger import (  # noqa: F401
    jaeger_collector_deployment,
    jaeger_query_deployment,
)
from components.migration import migration_job  # noqa: F401
from components.namespaces import namespaces  # noqa: F401
from components.network_policy import default_deny_policies  # noqa: F401
from components.opensearch import opensearch_release  # noqa: F401
from components.pdb import pdbs  # noqa: F401
from components.prometheus import (  # noqa: F401
    fastapi_service_monitor,
    kube_prometheus_release,
)
from components.registry import registry, registry_url  # noqa: F401
from components.secrets import (  # noqa: F401
    eso_release,
    external_secrets,
    secret_stores,
)
from components.state_bucket import state_bucket  # noqa: F401
from components.temporal import temporal_release, temporal_schema_job  # noqa: F401

# All pulumi.export() calls are in their respective component files.
# Add cross-component exports here if needed in the future.
