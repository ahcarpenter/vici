"""PodDisruptionBudgets for critical workloads (D-08, D-09).

PDBs are env-conditional: staging and prod only. Dev runs single-replica
workloads where minAvailable=1 would block node upgrades entirely.
"""

import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from config import ENV
from components.namespaces import k8s_provider, namespaces

# PDB definitions: (pulumi_name, k8s_name, namespace, match_labels, min_available)
_PDB_DEFINITIONS: list[tuple[str, str, str, dict[str, str], int]] = [
    (
        "vici-app-pdb",
        "vici-app",
        "vici",
        {"app": "vici"},
        1,
    ),
    (
        "temporal-frontend-pdb",
        "temporal-frontend",
        "temporal",
        {
            "app.kubernetes.io/name": "temporal",
            "app.kubernetes.io/component": "frontend",
        },
        1,
    ),
    (
        "temporal-history-pdb",
        "temporal-history",
        "temporal",
        {
            "app.kubernetes.io/name": "temporal",
            "app.kubernetes.io/component": "history",
        },
        1,
    ),
]

pdbs: dict[str, k8s.policy.v1.PodDisruptionBudget] = {}

if ENV in ("staging", "prod"):
    for _pulumi_name, _k8s_name, _ns, _labels, _min_avail in _PDB_DEFINITIONS:
        pdbs[_k8s_name] = k8s.policy.v1.PodDisruptionBudget(
            _pulumi_name,
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=_k8s_name,
                namespace=_ns,
            ),
            spec=k8s.policy.v1.PodDisruptionBudgetSpecArgs(
                min_available=_min_avail,
                selector=k8s.meta.v1.LabelSelectorArgs(
                    match_labels=_labels,
                ),
            ),
            opts=ResourceOptions(
                provider=k8s_provider,
                depends_on=[namespaces[_ns]],
            ),
        )
