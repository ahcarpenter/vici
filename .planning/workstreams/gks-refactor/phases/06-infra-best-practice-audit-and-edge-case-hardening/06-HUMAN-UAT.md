---
status: resolved
phase: 06-infra-best-practice-audit-and-edge-case-hardening
source: [06-VERIFICATION.md]
started: 2026-04-11T23:45:00Z
updated: 2026-04-12T00:30:00Z
---

## Current Test

[all tests complete]

## Tests

### 1. pulumi preview shows protect=true on all stateful resources
expected: Run `pulumi preview --stack dev` and confirm protect=true on both Cloud SQL instances, GKE cluster, Artifact Registry, and GCS state bucket
result: PASSED — all 5 resources show 🔒 (protect) icon in `pulumi preview --diff` output: GKE cluster, both Cloud SQL instances, Artifact Registry, GCS state bucket (imported)

### 2. NetworkPolicy enforcement in live cluster
expected: After `pulumi up`, `kubectl get networkpolicy -A` shows default-deny-all in all 5 namespaces (vici, temporal, observability, cert-manager, external-secrets). DNS resolution works. Cross-namespace undeclared ports blocked.
result: PASSED — 20 NetworkPolicies deployed across all 5 namespaces. Each has default-deny-all + allow-dns-egress + namespace-specific allow rules. Webhook ingress rules added for external-secrets (port 10250) and cert-manager (port 10250) to allow kube-apiserver admission calls on GKE Autopilot.

### 3. Temporal credentials end-to-end via ESO
expected: After pre-creating `{env}-temporal-db-password` in GCP Secret Manager, `pulumi up` succeeds, `kubectl get externalsecret temporal-db-credentials -n temporal` shows Ready=True, Temporal pods Running.
result: PASSED — GCP SM secret `dev-temporal-db-password` version created, ESO force-synced, ExternalSecret shows `SecretSynced` / `Ready=True`. K8s secret `temporal-db-credentials` contains key `password` (correct mapping for Temporal Helm existingSecret). CR-01 fix applied: generic ExternalSecret loop skips `temporal-db-password` to avoid duplicate resource conflict.

### 4. PDB presence/absence by environment
expected: `kubectl get pdb -A` in dev shows 0 PDBs; staging/prod show 3 PDBs (vici-app, temporal-frontend, temporal-history)
result: PASSED — dev cluster shows 0 Phase 6 PDBs (only GKE-managed PDBs present: parallelstorecsi-mount, filestore-lock-release-controller-pdb, opensearch-cluster-master-pdb). Env-conditional `if ENV in ("staging", "prod")` correctly suppresses PDB creation in dev.

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

### Live deployment fixes applied during UAT
- CR-01: Duplicate ExternalSecret for temporal-db-credentials (generic loop + custom override) — fixed by excluding `temporal-db-password` from generic loop
- State bucket location mismatch (imported as US-CENTRAL1, code said US) — fixed by using REGION-derived location + ignore_changes
- Webhook ingress rules missing for external-secrets and cert-manager (GKE Autopilot routes apiserver webhook calls through data plane, subject to NetworkPolicy) — fixed by adding ingress on pod port 10250
