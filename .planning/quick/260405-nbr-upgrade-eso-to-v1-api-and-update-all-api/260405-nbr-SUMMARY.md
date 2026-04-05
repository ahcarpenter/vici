---
phase: quick
plan: 260405-nbr
subsystem: infra/secrets
tags: [eso, external-secrets, helm, k8s, crd]
dependency_graph:
  requires: []
  provides: [eso-v1-crds, secret-store-v1, external-secret-v1]
  affects: [infra/components/secrets.py]
tech_stack:
  added: []
  patterns: [helm-chart-upgrade, k8s-crd-api-version-bump]
key_files:
  modified:
    - infra/components/secrets.py
decisions:
  - "ESO chart pinned to 1.0.5 (latest stable 1.x GA) rather than 1.0.0 minimum — 1.0.5 includes patch fixes"
  - "Spec shape unchanged between v1beta1 and v1 — only apiVersion string updated"
metrics:
  duration: "5 minutes"
  completed: "2026-04-05T20:49:57Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
---

# Quick Task 260405-nbr: Upgrade ESO to v1 API Summary

**One-liner:** Bumped ESO Helm chart from 0.10.7 to 1.0.5 and updated all SecretStore/ExternalSecret CRs from `external-secrets.io/v1beta1` to `external-secrets.io/v1`.

## What Was Done

### Task 1: Upgrade ESO chart version and update all api_version references to v1

Updated `infra/components/secrets.py` with three targeted changes:

1. `_ESO_CHART_VERSION` constant: `"0.10.7"` → `"1.0.5"`
2. SecretStore loop `api_version`: `"external-secrets.io/v1beta1"` → `"external-secrets.io/v1"`
3. ExternalSecret loop `api_version`: `"external-secrets.io/v1beta1"` → `"external-secrets.io/v1"`

No spec shape changes — the `workloadIdentity` block with `clusterLocation`, `clusterName`, and `serviceAccountRef` is valid and identical in v1.

**Commit:** fb89423

### Task 2: Verify no other v1beta1 ESO references exist in infra/

Scanned all `.py` source files under `infra/` for `external-secrets.io/v1beta1`. Zero matches found. A stale `.pyc` bytecode cache file matched but is not a source reference and will be invalidated on next import.

**Result:** PASS — no additional files required updating.

## Verification

```
grep -c "external-secrets.io/v1beta1" infra/components/secrets.py  # → 0
grep -c 'external-secrets.io/v1"' infra/components/secrets.py      # → 2
grep '_ESO_CHART_VERSION' infra/components/secrets.py              # → _ESO_CHART_VERSION = "1.0.5"
grep -r "external-secrets.io/v1beta1" infra/ --include="*.py"      # → (no output)
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. This is a pure version bump and API string update.

## Self-Check: PASSED

- [x] `infra/components/secrets.py` modified with correct values
- [x] Commit fb89423 exists: `feat(quick-260405-nbr): upgrade ESO chart to v1.0.5 and update api_version to v1`
- [x] Zero v1beta1 ESO references in source files
