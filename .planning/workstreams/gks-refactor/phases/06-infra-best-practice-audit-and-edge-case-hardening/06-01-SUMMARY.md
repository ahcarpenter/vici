---
phase: 06-infra-best-practice-audit-and-edge-case-hardening
plan: "01"
subsystem: infra
tags: [pulumi, resource-protection, gcs, gke, cloud-sql, artifact-registry, testing]
dependency_graph:
  requires: []
  provides:
    - protect=True on cluster, both Cloud SQL instances, Artifact Registry, GCS state bucket
    - Phase 6 static test scaffold (22 tests across 5 classes)
    - infra/components/state_bucket.py (new managed resource)
  affects:
    - infra/components/cluster.py
    - infra/components/database.py
    - infra/components/registry.py
tech_stack:
  added: []
  patterns:
    - Pulumi ResourceOptions(protect=True) on stateful GCP resources
    - Pulumi ResourceOptions(retain_on_delete=True) on GCS state bucket
    - Static AST/text test pattern from test_observability_static.py
key_files:
  created:
    - tests/infra/test_phase6_static.py
    - infra/components/state_bucket.py
  modified:
    - infra/components/cluster.py
    - infra/components/database.py
    - infra/components/registry.py
decisions:
  - "D-01/D-02: protect=True applied to all 5 stateful resources (cluster, app DB, temporal DB, registry, state bucket) in all environments"
  - "state_bucket.py does NOT import into __main__.py yet — wiring deferred to Plan 04 per plan spec"
  - "retain_on_delete=True added alongside protect=True on state bucket as defense-in-depth (T-6-01b)"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-04-11T23:26:28Z"
  tasks_completed: 2
  files_changed: 5
---

# Phase 06 Plan 01: Protect=True + Test Scaffold Summary

**One-liner:** Pulumi `protect=True` added to all 5 stateful resources (GKE cluster, app Cloud SQL, temporal Cloud SQL, Artifact Registry, GCS state bucket) with a 22-test static scaffold covering all Phase 6 success criteria.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create Phase 6 test scaffold | 083d63c | tests/infra/test_phase6_static.py |
| 2 | Add protect=True + create state_bucket.py | a5484fd | cluster.py, database.py, registry.py, state_bucket.py (new) |

## What Was Built

### Task 1: Test Scaffold (test_phase6_static.py)

22 tests across 5 classes following the exact pattern of `test_observability_static.py`:

- **TestProtect** (6 tests): cluster, app DB, temporal DB, registry, state_bucket protect=True; state_bucket retain_on_delete=True
- **TestNetworkPolicy** (4 tests): module exists, default-deny-all x5 namespaces, DNS egress x5 namespaces, Ingress+Egress policy types
- **TestTemporalESO** (4 tests): no cfg.require_secret for temporal_db_user/password, existingSecret present, temporal-db-password in secrets.py
- **TestPDB** (4 tests): module exists, ENV conditional with staging+prod, 3 workloads (vici-app, temporal-frontend, temporal-history), min_available used
- **TestOperationsDoc** (4 tests): OPERATIONS.md exists, cold-start section, secret rotation section, cluster upgrade section

TestProtect passes immediately (SC-1 implemented in Task 2). Other 4 classes currently fail as expected — they are the acceptance gates for Plans 02-05.

### Task 2: protect=True + state_bucket.py

**cluster.py:** Added `protect=True` to existing `ResourceOptions(ignore_changes=AUTOPILOT_VOLATILE_FIELDS)`.

**database.py:** Added `protect=True` to both `app_db_instance` and `temporal_db_instance` ResourceOptions (alongside existing `depends_on=[vpc_peering_connection]`). Database-level resources (`app_database`, `temporal_database`, `temporal_visibility_database`) intentionally NOT protected — only instances hold stateful data.

**registry.py:** Added `from pulumi import ResourceOptions` import and `opts=ResourceOptions(protect=True)` to the `registry` resource (previously had no opts).

**state_bucket.py (new):** GCS state bucket `vici-app-pulumi-state-{ENV}` as a Pulumi-managed resource with `protect=True` and `retain_on_delete=True`. Not yet wired into `__main__.py` — import deferred to Plan 04 per plan spec. Module is self-contained.

## Verification

```
pytest tests/infra/test_phase6_static.py::TestProtect -x
6 passed in 0.01s
```

```
pytest tests/infra/test_phase6_static.py --collect-only
22 tests collected
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

- `state_bucket.py` is not imported into `__main__.py` — intentional per plan spec. Plan 04 wires all new modules. The resource is self-contained and will show `protect=True` in `pulumi preview` only after import.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced. Changes are Pulumi resource option additions and a new managed resource definition for an existing GCS bucket.

## Self-Check: PASSED

- [x] tests/infra/test_phase6_static.py exists
- [x] infra/components/state_bucket.py exists
- [x] infra/components/cluster.py contains protect=True
- [x] infra/components/database.py contains protect=True (2x)
- [x] infra/components/registry.py contains protect=True
- [x] Commit 083d63c exists (test scaffold)
- [x] Commit a5484fd exists (protect=True additions)
- [x] pytest tests/infra/test_phase6_static.py::TestProtect -x exits 0
