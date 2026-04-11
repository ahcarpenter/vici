---
status: partial
phase: 06-infra-best-practice-audit-and-edge-case-hardening
source: [06-VERIFICATION.md]
started: 2026-04-11T23:45:00Z
updated: 2026-04-11T23:45:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. pulumi preview shows protect=true on all stateful resources
expected: Run `pulumi preview --stack dev` and confirm protect=true on both Cloud SQL instances, GKE cluster, Artifact Registry, and GCS state bucket
result: [pending]

### 2. NetworkPolicy enforcement in live cluster
expected: After `pulumi up`, `kubectl get networkpolicy -A` shows default-deny-all in all 5 namespaces (vici, temporal, observability, cert-manager, external-secrets). DNS resolution works. Cross-namespace undeclared ports blocked.
result: [pending]

### 3. Temporal credentials end-to-end via ESO
expected: After pre-creating `{env}-temporal-db-password` in GCP Secret Manager, `pulumi up` succeeds, `kubectl get externalsecret temporal-db-credentials -n temporal` shows Ready=True, Temporal pods Running.
result: [pending]

### 4. PDB presence/absence by environment
expected: `kubectl get pdb -A` in dev shows 0 PDBs; staging/prod show 3 PDBs (vici-app, temporal-frontend, temporal-history)
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
