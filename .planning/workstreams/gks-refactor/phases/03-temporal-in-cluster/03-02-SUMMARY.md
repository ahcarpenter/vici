---
phase: 03-temporal-in-cluster
plan: 02
subsystem: infra/temporal
tags: [temporal, pulumi, helm, cloud-sql, opensearch, schema-migration]
dependency_graph:
  requires:
    - infra/components/database.py (temporal_db_instance, connection_name)
    - infra/components/iam.py (temporal_app_ksa, temporal_gsa)
    - infra/components/namespaces.py (k8s_provider, namespaces)
    - infra/components/opensearch.py (opensearch_release, OPENSEARCH_SERVICE_HOST)
  provides:
    - infra/components/temporal.py — temporal_schema_job, temporal_release
  affects:
    - infra/__main__.py — needs import of temporal_schema_job, temporal_release
tech_stack:
  added:
    - temporal helm chart 0.74.0 (https://go.temporal.io/helm-charts)
    - temporalio/admin-tools:1.27.2 (schema migration Job image)
    - gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1 (Auth Proxy sidecar, TCP mode)
  patterns:
    - Auth Proxy native sidecar (init_containers with restart_policy=Always, TCP mode)
    - Pulumi Helm v3 Release with embedded Output values
    - k8s.batch.v1.Job for schema bootstrap with backoff_limit=0
key_files:
  created:
    - infra/components/temporal.py
  modified: []
decisions:
  - "Auth Proxy runs in TCP mode (--port=5432) for schema Job — temporal-sql-tool connects to localhost:5432 (Research Q1 resolution)"
  - "server.sidecarContainers injects Auth Proxy into all Temporal server pods (Research Q2 resolution)"
  - "numHistoryShards=512 is permanent per D-05; set at first deploy and cannot be changed"
  - "All bundled Temporal sub-charts disabled (cassandra, elasticsearch, prometheus, grafana) per D-02"
  - "postgres12 plugin used for Cloud SQL IAM auth; temporal_gsa.email transformed to IAM DB user format"
  - "OpenSearch visibility host imported from opensearch.py constant (canonical hostname lives there)"
  - "Temporal UI enabled as ClusterIP-only (D-13); no external Ingress until Phase 5"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-04"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
requirements: [TEMPORAL-01, TEMPORAL-04, TEMPORAL-05, TEMPORAL-06]
---

# Phase 03 Plan 02: Temporal Schema Migration Job and Helm Release Summary

Temporal Server deployed in-cluster via Helm chart 0.74.0 with Cloud SQL Auth Proxy (TCP mode) for both schema migration Job and server sidecar, OpenSearch visibility, and ClusterIP-only UI.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create Temporal schema migration Job (TCP Auth Proxy, temporal-sql-tool) | dccfb27 |
| 2 | Add Temporal Helm release and exports (all sub-charts disabled, postgres12, OpenSearch visibility) | dccfb27 |

## Key Decisions

- **Auth Proxy TCP mode for schema Job** — `temporal-sql-tool` uses `--ep`/`-p` for TCP host:port, not a unix socket path. Auth Proxy runs with `--port=5432`; tool connects to `localhost:5432`. No volumes needed (Research Q1 resolution).
- **server.sidecarContainers for Helm release** — Injects the Cloud SQL Auth Proxy into all four Temporal server component pods (frontend, history, matching, worker). Pulumi auto-resolves Output values embedded in Helm values dict (Research Q2 resolution).
- **numHistoryShards=512** — Set per D-05. This value is immutable after first deploy; changing it requires full cluster wipe.
- **All bundled sub-charts disabled** — cassandra, elasticsearch, prometheus, grafana all set to `enabled: False` per D-02. External dependencies (Cloud SQL, OpenSearch) are used instead.
- **postgres12 plugin** — Used for both `pluginName` and `driverName` per D-03. `temporal_gsa.email` is transformed from `temporal-app@PROJECT.iam.gserviceaccount.com` to the IAM DB user format `temporal-app@PROJECT.iam` via `.apply()`.
- **OpenSearch hostname from opensearch.py** — `OPENSEARCH_SERVICE_HOST` is imported from `components.opensearch` rather than redefined; the canonical hostname lives in the component that owns that resource.
- **Temporal UI as ClusterIP** — Per D-13/TEMPORAL-06, no external Ingress in Phase 3. Ingress deferred to Phase 5.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The component is infrastructure-as-code; all values are wired to real Pulumi outputs or module constants.

## Threat Flags

No new security surface beyond what is documented in the plan's threat model (T-03-03 through T-03-07).

- **T-03-03** (mitigate): Auth Proxy uses Workload Identity — no static credentials. Implemented via `temporal_app_ksa` annotation + `temporal_gsa` IAM binding.
- **T-03-04** (mitigate): `backoff_limit=0` ensures schema Job fails fast on error. Runs under `temporal-app` KSA with minimal IAM.
- **T-03-05/T-03-06** (accept): gRPC port 7233 and UI port 8080 are ClusterIP-only. No external exposure in Phase 3.
- **T-03-07** (accept): `numHistoryShards=512` is set once and documented as permanent.

## Self-Check: PASSED

- `infra/components/temporal.py` — FOUND
- Commit `dccfb27` — FOUND
