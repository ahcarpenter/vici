# Phase 6: Infra Best-Practice Audit and Edge-Case Hardening - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden existing GKE infrastructure with Pulumi resource protection, Kubernetes network policies, pod disruption budgets, Temporal credential migration to ESO, resource limits on Jobs, and an operational runbook for edge cases. No new infrastructure — audit and harden what exists.

</domain>

<decisions>
## Implementation Decisions

### Pulumi protect scope
- **D-01:** All stateful resources get `protect=True` in all environments (dev, staging, prod)
- **D-02:** Protected resources: Cloud SQL instances (app + Temporal), GKE cluster, Artifact Registry, GCS state bucket

### Network policies
- **D-03:** Default deny ingress and egress per namespace, then explicit allow rules for declared ports
- **D-04:** All 5 namespaces get NetworkPolicy resources: vici, temporal, observability, cert-manager, external-secrets
- **D-05:** Allow rules follow the actual traffic patterns (e.g., app->temporal:7233, app->jaeger-collector:4317, temporal->cloudsql, etc.)

### Temporal DB credentials
- **D-06:** Migrate Temporal DB credentials from Pulumi stack secrets to GCP Secret Manager, synced via ESO to K8s Secrets
- **D-07:** Temporal Helm chart should reference credentials via `existingSecret` — consistent with how all other secrets are managed

### Pod disruption budgets
- **D-08:** PDBs are env-conditional: staging and prod get PDBs, dev skips them (single-replica makes PDBs no-ops)
- **D-09:** PDBs apply to: vici-app, Temporal frontend, Temporal history (workloads with >1 replica in staging/prod)

### Edge-case runbook
- **D-10:** Mitigations documented in `infra/OPERATIONS.md` — a dedicated runbook alongside Pulumi code
- **D-11:** Covers: cold-start ordering (dependency chain for pulumi up), secret rotation procedure, cluster upgrade playbook

### Claude's Discretion
- Specific resource limit values for migration/schema Jobs (informed by observed usage)
- NetworkPolicy port numbers and label selectors (derived from actual service manifests)
- PDB minAvailable values per workload
- OPERATIONS.md structure and section ordering

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Infrastructure components
- `infra/components/cluster.py` — Existing deletion_protection and ignore_changes patterns
- `infra/components/database.py` — Cloud SQL instances, no protect flags currently
- `infra/components/temporal.py` — DB credentials in Helm values (D-06/D-07 target), schema Job without resource limits
- `infra/components/secrets.py` — ESO pattern to follow for Temporal credential migration
- `infra/components/migration.py` — Migration Job without resource limits
- `infra/components/opensearch.py` — Index-template Job without resource limits (OpenSearch itself has limits)
- `infra/components/app.py` — App Deployment (PDB target)
- `infra/config.py` — Environment config and stack-level settings

### Stack configs
- `infra/Pulumi.dev.yaml` — Dev stack config (Temporal DB creds currently here as stack secrets)
- `infra/Pulumi.staging.yaml` — Staging stack config
- `infra/Pulumi.prod.yaml` — Prod stack config

### Requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` — Phase 6 success criteria (5 items)
- `.planning/workstreams/gks-refactor/ROADMAP.md` §Phase 6 — Success criteria reference

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `secrets.py` `_SECRET_DEFINITIONS` list pattern: single source of truth for ESO-managed secrets — extend for Temporal DB creds
- `cluster.py` `deletion_protection=True` pattern: model for adding Pulumi-level `protect=True`
- `config.py` `ViciConfig`: env-aware config class — use for PDB conditional logic

### Established Patterns
- ESO flow: GCP Secret Manager -> SecretStore (namespace-scoped) -> ExternalSecret -> K8s Secret
- Auth Proxy sidecar: consistent across migration.py and temporal.py
- Pulumi `ResourceOptions(opts)` inheritance: all components accept parent opts

### Integration Points
- `__main__.py`: Pulumi entry point where new components (NetworkPolicy, PDB) would be wired
- `namespaces.py`: Creates all 5 namespaces — NetworkPolicy resources attach per-namespace
- `temporal.py` Helm values: where `existingSecret` replaces inline credentials

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-infra-best-practice-audit-and-edge-case-hardening*
*Context gathered: 2026-04-06*
