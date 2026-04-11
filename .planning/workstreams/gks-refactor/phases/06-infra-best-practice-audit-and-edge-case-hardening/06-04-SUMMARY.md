---
phase: 06-infra-best-practice-audit-and-edge-case-hardening
plan: "04"
subsystem: infra
tags: [pulumi, kubernetes, pdb, resource-limits, operations-runbook]
dependency_graph:
  requires:
    - "06-01: state_bucket.py + protect=True"
    - "06-02: network_policy.py (default_deny_policies export)"
    - "06-03: temporal ESO credential migration"
  provides:
    - infra/components/pdb.py: env-conditional PDBs for 3 workloads
    - infra/__main__.py: all Phase 6 modules wired (network_policy, pdb, state_bucket)
    - infra/OPERATIONS.md: cold-start, secret rotation, cluster upgrade, teardown runbook
    - resource limits on migration.py (2 containers) and opensearch.py (1 container)
  affects:
    - infra/components/pdb.py (new)
    - infra/components/migration.py
    - infra/components/opensearch.py
    - infra/__main__.py
    - infra/OPERATIONS.md (new)
tech_stack:
  added: []
  patterns:
    - k8s.policy.v1.PodDisruptionBudget with env-conditional instantiation
    - ResourceRequirementsArgs on Job containers for GKE Autopilot scheduling
    - Pulumi __main__.py import-to-register pattern with noqa F401
key_files:
  created:
    - infra/components/pdb.py
    - infra/OPERATIONS.md
  modified:
    - infra/components/migration.py
    - infra/components/opensearch.py
    - infra/__main__.py
decisions:
  - "PDBs use k8s.policy.v1 (not v1beta1, removed in K8s 1.25)"
  - "Temporal pod label selectors use app.kubernetes.io/component (Helm standard labels, A1 from RESEARCH.md)"
  - "pdb.py uses _PDB_DEFINITIONS list of tuples — avoids repetition while producing explicit instantiation per workload"
  - "state_bucket import position: after secrets (alphabetical: st > se), before temporal"
  - "network_policy import position: after namespaces (alphabetical: ne > na), before opensearch"
  - "pdb import position: after opensearch (alphabetical: p > o), before prometheus"
metrics:
  duration: "~8 minutes"
  completed_date: "2026-04-11T00:00:00Z"
  tasks_completed: 3
  files_changed: 5
---

# Phase 06 Plan 04: PDBs, Resource Limits, Module Wiring, and OPERATIONS.md Summary

**One-liner:** PodDisruptionBudgets for 3 workloads (staging/prod only), resource limits on 3 Job containers, all Phase 6 modules wired into `__main__.py`, and a 4-section operational runbook covering cold-start, secret rotation, cluster upgrade, and protected teardown.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create PDB module and add resource limits to migration and opensearch Jobs | 8f4233b | infra/components/pdb.py (new), infra/components/migration.py, infra/components/opensearch.py |
| 2 | Wire all Phase 6 modules into __main__.py | 4f3527f | infra/__main__.py |
| 3 | Create OPERATIONS.md operational runbook | 74a4512 | infra/OPERATIONS.md (new) |

## What Was Built

### Task 1: pdb.py + resource limits

**infra/components/pdb.py (new):** Defines `_PDB_DEFINITIONS` as a list of tuples
(pulumi_name, k8s_name, namespace, match_labels, min_available) for the 3 target
workloads. The `pdbs` dict is populated only when `ENV in ("staging", "prod")` — dev
skips PDBs entirely to avoid blocking single-replica node upgrades (D-08).

| Workload | Namespace | Label Selector | minAvailable |
|----------|-----------|----------------|--------------|
| vici-app | vici | `app: vici` | 1 |
| temporal-frontend | temporal | `app.kubernetes.io/name: temporal, app.kubernetes.io/component: frontend` | 1 |
| temporal-history | temporal | `app.kubernetes.io/name: temporal, app.kubernetes.io/component: history` | 1 |

**infra/components/migration.py:** Added `ResourceRequirementsArgs` to both containers:
- `cloud-sql-proxy` init container: requests `{cpu: 100m, memory: 128Mi}`, limits `{cpu: 200m, memory: 256Mi}`
- `alembic-migration` main container: requests `{cpu: 100m, memory: 256Mi}`, limits `{cpu: 500m, memory: 512Mi}`

**infra/components/opensearch.py:** Added `ResourceRequirementsArgs` to the `index-template` container:
- requests `{cpu: 50m, memory: 64Mi}`, limits `{cpu: 100m, memory: 128Mi}`

### Task 2: __main__.py wiring

Three imports added in alphabetical order among component imports:

```python
from components.network_policy import default_deny_policies  # noqa: F401  # after namespaces
from components.pdb import pdbs  # noqa: F401                               # after opensearch
from components.state_bucket import state_bucket  # noqa: F401              # after secrets
```

All export names verified from source files before importing:
- `network_policy.py`: exports `default_deny_policies` (confirmed from 06-02-SUMMARY.md)
- `pdb.py`: exports `pdbs` (created in Task 1)
- `state_bucket.py`: exports `state_bucket` (confirmed from reading file)

### Task 3: OPERATIONS.md

Four sections covering all D-10/D-11 requirements:

1. **Cold-Start Ordering** — 17-step provisioning dependency chain, first-time setup commands, GCS state bucket import procedure, and 12-entry Secret Manager inventory table
2. **Secret Rotation** — Application secret rotation (ESO force-sync pattern), Temporal DB password rotation (Cloud SQL + SM + ESO + pod restarts), ESO sync verification
3. **Cluster Upgrade** — Pre-upgrade checklist (PDB verification, version check, deprecated API scan), monitoring during upgrade (node watch + eviction events), 4-step post-upgrade verification
4. **Protected Resource Teardown** — Lists all 5 protected resources with `protect=True`, 3-step removal procedure, GCS state bucket exception documented (never destroy via `pulumi destroy`)

## Verification

```
pytest tests/infra/test_phase6_static.py -x
22 passed in 0.02s
```

All 5 test classes pass: TestProtect, TestNetworkPolicy, TestTemporalESO, TestPDB, TestOperationsDoc.

```
pytest tests/infra/ -x
82 passed in 0.15s
```

Full infra test suite passes — no regressions across Phase 4 (observability, CD) and Phase 6 tests.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All 3 new modules are imported into `__main__.py` and will appear in `pulumi preview` once
the Pulumi stack is configured. The PDB module conditionally creates resources only in staging/prod
— this is intentional behavior, not a stub.

## Threat Surface Scan

All changes implement mitigations from the plan's `<threat_model>`:
- **T-6-04** (Denial of Service — node drain): PDBs created for vici-app, temporal-frontend,
  temporal-history in staging and prod.
- **T-6-04b** (Denial of Service — dev): PDBs skipped in dev per accepted risk disposition.
- **T-6-05** (Denial of Service — Job scheduling): Resource limits added to all 3 Job containers
  (migration cloud-sql-proxy, migration alembic, opensearch index-template).

No new network endpoints, auth paths, file access patterns, or trust boundaries introduced.

## Self-Check: PASSED

- [x] infra/components/pdb.py exists
- [x] infra/OPERATIONS.md exists
- [x] infra/__main__.py contains `from components.network_policy import`
- [x] infra/__main__.py contains `from components.pdb import`
- [x] infra/__main__.py contains `from components.state_bucket import`
- [x] infra/components/migration.py contains `ResourceRequirementsArgs` (2 occurrences)
- [x] infra/components/opensearch.py contains `ResourceRequirementsArgs`
- [x] Commit 8f4233b exists (Task 1 — pdb.py + resource limits)
- [x] Commit 4f3527f exists (Task 2 — __main__.py wiring)
- [x] Commit 74a4512 exists (Task 3 — OPERATIONS.md)
- [x] pytest tests/infra/test_phase6_static.py -x exits 0 (22/22 passed)
- [x] pytest tests/infra/ -x exits 0 (82/82 passed)
