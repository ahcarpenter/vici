---
phase: 03-temporal-in-cluster
plan: 01
subsystem: infra/observability
tags: [opensearch, pulumi, helm, observability, temporal-visibility]
dependency_graph:
  requires: [infra/components/namespaces.py]
  provides: [infra/components/opensearch.py — opensearch_release, OPENSEARCH_SERVICE_HOST]
  affects: [infra/__main__.py — needs import, infra/components/temporal.py — reads OPENSEARCH_SERVICE_HOST]
tech_stack:
  added: [opensearch helm chart 2.37.0, curlimages/curl:8.7.1]
  patterns: [Pulumi Helm v3 Release, k8s.batch.v1.Job for post-deploy init, module-level constants]
key_files:
  created: [infra/components/opensearch.py]
  modified: []
decisions:
  - "Pinned OpenSearch chart to 2.x (2.37.0) — OpenSearch 3.x breaks Temporal's Elasticsearch client (D-08)"
  - "Security plugin disabled for v1.0 internal-only use; ClusterIP-only service (T-03-01 accepted)"
  - "Index template Job sets number_of_replicas: 0 globally to prevent yellow cluster state on single-node (D-07)"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-04"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
requirements: [TEMPORAL-02, TEMPORAL-03]
---

# Phase 03 Plan 01: OpenSearch Pulumi Component Summary

Single-node OpenSearch deployed via Helm chart 2.37.0 in the observability namespace with a post-deploy index template Job enforcing `number_of_replicas: 0`.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create OpenSearch Pulumi component | ee555a1 |

## Key Decisions

- **Chart version pinned to 2.37.0** — OpenSearch 3.x is incompatible with Temporal's Elasticsearch visibility client (D-08). The 2.x line must be used.
- **Security plugin disabled** — `plugins.security.disabled: true` is set in `opensearch.yml`. The service is ClusterIP-only (not exposed via Ingress), making this acceptable for v1.0 per threat register entry T-03-01.
- **Index template Job** — A `curlimages/curl:8.7.1` Job runs after the Helm release and POSTs an index template that sets `number_of_replicas: 0` for all indices. This prevents OpenSearch from entering a yellow cluster state on a single-node deployment (D-07/OBS-01).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None beyond what is documented in the plan's threat model (T-03-01, T-03-02 — both accepted).

## Self-Check: PASSED

- `infra/components/opensearch.py` — FOUND
- Commit `ee555a1` — FOUND
