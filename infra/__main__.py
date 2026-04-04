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

# All pulumi.export() calls are in their respective component files.
# Add cross-component exports here if needed in the future.
