# Phase 6: Infra Best-Practice Audit and Edge-Case Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-06
**Phase:** 06-infra-best-practice-audit-and-edge-case-hardening
**Areas discussed:** Pulumi protect scope, Network policies, Temporal DB credentials, PDBs + Runbook

---

## Pulumi Protect Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All stateful, all envs | Cloud SQL, GKE cluster, Artifact Registry, GCS bucket — protected in all envs | ✓ |
| All stateful, prod only | Only prod stack gets protect=True; dev/staging can be torn down freely | |
| Prod + staging stateful | Dev can be destroyed freely; staging and prod protected | |
| You decide | Claude picks based on best practices | |

**User's choice:** All stateful, all envs (Recommended)
**Notes:** None

---

## Network Policies — Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Deny-all + allow-list | Default deny ingress/egress per namespace, explicit allow rules for declared ports | ✓ |
| Deny ingress only | Block inbound cross-namespace traffic but allow all egress | |
| App namespaces only | NetworkPolicy on vici + temporal only; skip system namespaces | |
| You decide | Claude picks based on GKE Autopilot best practices | |

**User's choice:** Deny-all + allow-list (Recommended)
**Notes:** None

## Network Policies — Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All 5 namespaces | vici, temporal, observability, cert-manager, external-secrets — full lockdown | ✓ |
| App namespaces only | vici + temporal + observability; skip cert-manager and external-secrets | |
| You decide | Claude determines based on traffic patterns | |

**User's choice:** All 5 namespaces (Recommended)
**Notes:** None

---

## Temporal DB Credentials

| Option | Description | Selected |
|--------|-------------|----------|
| Wire through ESO | Store in GCP Secret Manager, sync via ESO, reference via existingSecret — consistent with all other secrets | ✓ |
| Keep Pulumi stack secrets | Current approach — encrypted in Pulumi state but plaintext in Helm values | |
| You decide | Claude picks based on security posture | |

**User's choice:** Wire through ESO (Recommended)
**Notes:** None

---

## Pod Disruption Budgets

| Option | Description | Selected |
|--------|-------------|----------|
| Env-conditional | PDBs in staging/prod; skip in dev where replicas=1 makes PDBs no-ops | ✓ |
| All envs, all workloads | PDBs everywhere — documents intent even if not operationally effective | |
| Skip PDBs entirely | Autopilot handles node management; marginal value at current scale | |
| You decide | Claude picks based on Autopilot behavior | |

**User's choice:** Env-conditional (Recommended)
**Notes:** None

---

## Edge-Case Runbook Location

| Option | Description | Selected |
|--------|-------------|----------|
| infra/OPERATIONS.md | Dedicated runbook alongside Pulumi code — operators find it where they work | ✓ |
| Code comments inline | Mitigations as comments in each component file — close to code but scattered | |
| docs/DEPLOYMENT.md | Extend existing deployment doc — single doc but mixes setup with operations | |
| You decide | Claude picks the best location | |

**User's choice:** infra/OPERATIONS.md (Recommended)
**Notes:** None

---

## Claude's Discretion

- Specific resource limit values for migration/schema Jobs
- NetworkPolicy port numbers and label selectors
- PDB minAvailable values per workload
- OPERATIONS.md structure and section ordering

## Deferred Ideas

None — discussion stayed within phase scope
