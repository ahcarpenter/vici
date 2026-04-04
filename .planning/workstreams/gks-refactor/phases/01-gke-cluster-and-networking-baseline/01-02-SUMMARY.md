# Plan 01-02 Summary — GKE Cluster and Service Accounts

## Status: Complete

## Files Created
- `infra/components/cluster.py` — GKE Autopilot cluster resource
- `infra/components/identity.py` — GCP service accounts and Workload Identity binding

## Key Decisions
- RELEASE_CHANNEL mapping: dev=REGULAR, staging=REGULAR, prod=STABLE
- `dns_config` is set explicitly with CLOUD_DNS/CLUSTER_SCOPE/cluster.local — NOT in ignore_changes
- `AUTOPILOT_VOLATILE_FIELDS` = [vertical_pod_autoscaling, node_config, node_pool, initial_node_count]
- `deletion_protection=True` on cluster resource
- Workload Identity pool: `<project>.svc.id.goog`, targeting KSA `vici/vici-app`

## Deviations
None.
