---
phase: 06-infra-best-practice-audit-and-edge-case-hardening
verified: 2026-04-11T23:59:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run `pulumi preview --stack dev` against a live GCP project and confirm protect: true appears on all 5 stateful resources in the preview output"
    expected: "Cloud SQL app instance, Cloud SQL Temporal instance, GKE cluster, Artifact Registry, and GCS state bucket all show protect: true in the Pulumi preview diff"
    why_human: "protect=True is a Pulumi ResourceOptions flag. Code-level verification confirms it is set correctly in all files and all 22 static tests pass, but the rendered `pulumi preview` output can only be confirmed against a live GCP project."
  - test: "Run `kubectl get networkpolicy -A` in a live cluster after `pulumi up` and confirm default-deny-all exists in all 5 namespaces"
    expected: "Each of vici, temporal, observability, cert-manager, external-secrets namespaces shows a `default-deny-all` NetworkPolicy; port-forward tests confirm DNS resolution still works within each namespace"
    why_human: "NetworkPolicy enforcement is a runtime cluster-level behavior. Code-level verification confirms all 5 namespaces have `default-deny-all` and explicit allow rules correctly defined in network_policy.py (static tests pass), but actual enforcement by the CNI plugin can only be verified on a live cluster."
  - test: "After `pulumi up`, verify Temporal credentials flow end-to-end: `kubectl get externalsecret temporal-db-credentials -n temporal` shows Ready=True and Temporal server pods are Running"
    expected: "ESO ExternalSecret `temporal-db-credentials` in `temporal` namespace shows STATUS=SecretSynced, READY=True. Temporal frontend, history, matching, and worker pods are Running and the Helm release existingSecret reference resolves correctly."
    why_human: "ESO sync requires a live GCP Secret Manager instance with the `{env}-temporal-db-password` secret pre-populated. Pulumi code is correct (no cfg.require_secret, existingSecret pattern implemented), but actual K8s Secret creation and Temporal pod startup can only be validated on a live cluster."
  - test: "Verify PDBs appear in staging/prod clusters: `kubectl get pdb -A` should show vici-app, temporal-frontend, temporal-history in those environments but NOT in dev"
    expected: "staging and prod: 3 PDBs present (vici-app, temporal-frontend, temporal-history). dev: no PDBs present. All PDBs show DISRUPTIONS ALLOWED >= 0."
    why_human: "PDB conditional logic (`ENV in ('staging', 'prod')`) is code-verified and static tests pass, but verifying the absence of PDBs in dev and their presence in staging/prod requires running against the respective live stacks."
---

# Phase 6: Infra Best-Practice Audit and Edge-Case Hardening Verification Report

**Phase Goal:** All stateful infrastructure is protected from accidental deletion, namespaces enforce least-privilege network access, Temporal credentials follow the ESO pattern, and operators have a runbook for edge-case scenarios
**Verified:** 2026-04-11T23:59:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `pulumi preview` shows `protect: true` on Cloud SQL instances, GKE cluster, Artifact Registry, and GCS state bucket across all environments | VERIFIED | `cluster.py` L64-67: `protect=True` in ResourceOptions. `database.py` L76, L107: `protect=True` on both `app_db_instance` and `temporal_db_instance`. `registry.py` L18: `protect=True`. `state_bucket.py` L26-28: `protect=True` + `retain_on_delete=True`. All 6 TestProtect assertions pass. |
| 2 | Each of the 5 namespaces (vici, temporal, observability, cert-manager, external-secrets) has a default-deny NetworkPolicy and explicit allow rules matching actual traffic patterns | VERIFIED | `network_policy.py` (443 lines): `default_deny_policies` dict populated with one `default-deny-all` policy per namespace (5 total), `dns_allow_policies` with one `allow-dns-egress` per namespace (5 total), and `allow_policies` with 8 named per-namespace allow rules. All 4 TestNetworkPolicy assertions pass. |
| 3 | Temporal DB credentials are sourced from GCP Secret Manager via ESO (not Pulumi stack secrets) and the Temporal Helm release uses `existingSecret` | VERIFIED | `temporal.py`: no `cfg.require_secret` calls. Helm values include `"existingSecret": "temporal-db-credentials"` and `"secretKey": "password"` (L195-196). Schema Job injects password via `secretKeyRef` pointing to `temporal-db-credentials` / `password` (L104-112). `secrets.py`: custom ExternalSecret `ext-secret-temporal-db-credentials` maps GCP SM key to K8s Secret key `"password"` (L167-190). `Pulumi.dev.yaml`: no `temporal_db_user` or `temporal_db_password` entries. All 4 TestTemporalESO assertions pass. |
| 4 | PDBs exist for vici-app, temporal-frontend, and temporal-history in staging and prod (not dev) | VERIFIED | `pdb.py`: `if ENV in ("staging", "prod")` guard at L46. `_PDB_DEFINITIONS` contains all 3 workloads with `min_available=1`. `k8s.policy.v1.PodDisruptionBudget` used (v1, not deprecated v1beta1). All 4 TestPDB assertions pass. |
| 5 | `infra/OPERATIONS.md` documents cold-start ordering, secret rotation, and cluster upgrade procedures | VERIFIED | `OPERATIONS.md` (240 lines) contains 4 sections: Cold-Start Ordering (17-step dependency chain + secret inventory table), Secret Rotation (app secrets + Temporal DB password rotation procedures), Cluster Upgrade (pre-checklist, monitoring, post-verification), Protected Resource Teardown. All 4 TestOperationsDoc assertions pass. |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infra/components/cluster.py` | GKE cluster with protect=True | VERIFIED | L64-67: `protect=True` in `ResourceOptions(ignore_changes=..., protect=True)` |
| `infra/components/database.py` | Both Cloud SQL instances with protect=True | VERIFIED | `app_db_instance` L76, `temporal_db_instance` L107 — both have `protect=True` |
| `infra/components/registry.py` | Artifact Registry with protect=True | VERIFIED | L18: `opts=ResourceOptions(protect=True)` |
| `infra/components/state_bucket.py` | GCS state bucket with protect=True and retain_on_delete=True | VERIFIED | L26-28: both flags present |
| `infra/components/network_policy.py` | Default-deny NetworkPolicy for all 5 namespaces | VERIFIED | 443 lines; 5 default-deny-all + 5 DNS-allow + 8 explicit allow rules |
| `infra/components/secrets.py` | temporal-db-password SM secret + custom ExternalSecret | VERIFIED | `_SECRET_DEFINITIONS` includes `temporal-db-password`. Custom ExternalSecret with `"secretKey": "password"` at L167-190 |
| `infra/components/temporal.py` | existingSecret pattern, no cfg.require_secret | VERIFIED | Helm values use `"existingSecret": "temporal-db-credentials"`. No `cfg.require_secret` present. |
| `infra/components/pdb.py` | PDB module with env-conditional creation | VERIFIED | `if ENV in ("staging", "prod")` at L46; 3 PDBs for vici-app, temporal-frontend, temporal-history |
| `infra/__main__.py` | Imports network_policy, pdb, state_bucket | VERIFIED | L28: `from components.network_policy import default_deny_policies`, L30: `from components.pdb import pdbs`, L41: `from components.state_bucket import state_bucket` — all with `# noqa: F401` |
| `infra/OPERATIONS.md` | Cold-start, secret rotation, cluster upgrade sections | VERIFIED | All 3 required sections present plus Protected Resource Teardown |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `infra/__main__.py` | `infra/components/network_policy.py` | `from components.network_policy import default_deny_policies` | WIRED | L28 in `__main__.py` — explicit import with noqa comment |
| `infra/__main__.py` | `infra/components/pdb.py` | `from components.pdb import pdbs` | WIRED | L30 in `__main__.py` — explicit import with noqa comment |
| `infra/__main__.py` | `infra/components/state_bucket.py` | `from components.state_bucket import state_bucket` | WIRED | L41 in `__main__.py` — explicit import with noqa comment |
| `infra/components/network_policy.py` | `infra/components/namespaces.py` | `from components.namespaces import k8s_provider, namespaces` | WIRED | L30 in `network_policy.py` — k8s_provider and namespaces used in all ResourceOptions |
| `infra/components/temporal.py` | `infra/components/secrets.py` | `from components.secrets import external_secrets` + `existingSecret: temporal-db-credentials` | WIRED | `external_secrets["temporal-db-password"]` in depends_on at L129 and L257 |
| `infra/components/secrets.py` | GCP Secret Manager | ExternalSecret with `remoteRef.key: {ENV}-temporal-db-password` | WIRED (code) | L183: `"remoteRef": {"key": f"{ENV}-temporal-db-password"}` — runtime sync requires human verification |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `temporal.py` schema Job | `TEMPORAL_DB_PASSWORD` env var | ESO-synced K8s Secret `temporal-db-credentials` via `secretKeyRef` | Code-verified (runtime sync: human needed) | WIRED — secretKeyRef at L107-111 maps to ESO-created Secret; Secret populated by GCP SM via custom ExternalSecret in secrets.py |
| `temporal.py` Helm release | `existingSecret: temporal-db-credentials` | Same K8s Secret | Code-verified (runtime sync: human needed) | WIRED — Helm values at L195-196 reference the ESO-managed Secret |
| `pdb.py` pdbs dict | `ENV` from config | `config.py` `cfg.require("env")` | Real (stack config value) | FLOWING — ENV determines PDB creation via `if ENV in ("staging", "prod")` |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All Phase 6 static tests pass | `/Users/ahcarpenter/workspace/vici/.venv/bin/pytest tests/infra/test_phase6_static.py -v` | 22 passed in 0.02s | PASS |
| Full infra test suite — no regressions | `/Users/ahcarpenter/workspace/vici/.venv/bin/pytest tests/infra/ -v` | 82 passed in 0.13s | PASS |
| Python syntax valid on all Phase 6 files | `ast.parse()` on network_policy.py, pdb.py, state_bucket.py, temporal.py, secrets.py | All OK | PASS |
| protect=True count in database.py | `grep -c "protect=True" database.py` | 2 (app_db_instance + temporal_db_instance) | PASS |
| Pulumi.dev.yaml has no temporal stack secrets | `grep temporal_db Pulumi.dev.yaml` | No match (9-line file, no stack secrets) | PASS |

---

### Requirements Coverage

Phase 6 has no formal requirement IDs (hardening phase). All 5 Success Criteria from ROADMAP.md are verified above. No orphaned REQUIREMENTS.md entries map to Phase 6.

---

### Anti-Patterns Found

No stubs, placeholder comments, TODO/FIXME markers, or empty implementations found in any Phase 6 files (`network_policy.py`, `pdb.py`, `state_bucket.py`, `temporal.py`, `secrets.py`, `OPERATIONS.md`).

One intentional design choice worth noting: `pdb.py` produces an empty `pdbs` dict in dev (because `ENV in ("staging", "prod")` evaluates to False in dev). This is correct and documented — the empty dict is not a stub; it is the intended behavior for the dev environment.

---

### Human Verification Required

#### 1. pulumi preview — protect: true in rendered output

**Test:** Run `cd infra && pulumi preview --stack dev` against a live GCP project and inspect the preview output for all 5 stateful resources.
**Expected:** Cloud SQL app instance (`vici-app-dev`), Cloud SQL Temporal instance (`vici-temporal-dev`), GKE cluster (`vici-dev`), Artifact Registry (`vici-registry`), and GCS state bucket (`pulumi-state-bucket`) all show `protect: true` in the resource properties column of the preview output.
**Why human:** The `protect=True` Pulumi ResourceOptions flag is set correctly in all 5 source files and all 6 TestProtect static assertions pass. However, the success criterion specifies "`pulumi preview` shows `protect: true`" — confirming the rendered preview output requires a live GCP project and Pulumi stack.

#### 2. NetworkPolicy enforcement in live cluster

**Test:** After `pulumi up --stack dev`, run `kubectl get networkpolicy -A` and verify all 5 namespaces have `default-deny-all`. Then test that DNS resolution still works from a pod in each namespace (e.g., `kubectl exec -n vici deploy/vici-app -- nslookup kubernetes.default`).
**Expected:** All 5 namespaces show `default-deny-all` NetworkPolicy. Pods can resolve DNS (DNS egress allow rules are present). Cross-namespace traffic to undeclared ports is blocked; declared ports (e.g., vici → temporal:7233) are allowed.
**Why human:** NetworkPolicy enforcement depends on the GKE CNI plugin at runtime. Code verification confirms all policies are correctly defined (static tests pass), but actual traffic blocking/allowing can only be validated in a live cluster.

#### 3. Temporal credentials end-to-end via ESO

**Test:** After `pulumi up`, run `kubectl get externalsecret temporal-db-credentials -n temporal` and then check Temporal pod status.
**Expected:** ExternalSecret shows `STATUS=SecretSynced, READY=True`. Temporal frontend, history, matching, and worker pods are all Running. The GCP Secret Manager secret `{env}-temporal-db-password` must be pre-created manually before `pulumi up`.
**Why human:** ESO sync and Temporal pod startup require a live GCP project with the Secret Manager secret pre-populated. The code removes all Pulumi stack secret references and implements the existingSecret pattern correctly; runtime validation requires the cluster.

#### 4. PDB presence/absence by environment

**Test:** Check `kubectl get pdb -A` in dev, staging, and prod stacks after respective `pulumi up` runs.
**Expected:** dev: no PDBs in any namespace. staging: vici-app, temporal-frontend, temporal-history PDBs present in their respective namespaces. prod: same 3 PDBs present.
**Why human:** PDB creation is guarded by `ENV in ("staging", "prod")` which is a Pulumi stack config value. Verifying correct conditional behavior requires running against multiple live stacks.

---

### Gaps Summary

No code-level gaps found. All 5 success criteria are verified at code level:

- SC-1 (protect=True): All 5 stateful resources have `protect=True` in ResourceOptions. `state_bucket.py` additionally has `retain_on_delete=True`.
- SC-2 (NetworkPolicies): All 5 namespaces have default-deny-all + DNS-egress-allow + per-namespace explicit allow rules covering all documented traffic patterns.
- SC-3 (ESO credentials): Temporal DB password removed from Pulumi stack secrets, custom ExternalSecret creates K8s Secret with correct key `"password"`, Helm release uses `existingSecret`, schema Job reads password via `secretKeyRef`.
- SC-4 (PDBs): `pdb.py` creates PDBs for vici-app, temporal-frontend, temporal-history only when `ENV in ("staging", "prod")`.
- SC-5 (OPERATIONS.md): 240-line runbook covering cold-start ordering (17-step chain), secret rotation (app + Temporal DB procedures), cluster upgrade (pre/during/post checklists), and protected resource teardown.

The 4 human verification items are runtime confirmation of code-correct implementations — they do not represent gaps in the implementation.

---

_Verified: 2026-04-11T23:59:00Z_
_Verifier: Claude (gsd-verifier)_
