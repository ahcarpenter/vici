---
phase: 06-infra-best-practice-audit-and-edge-case-hardening
plan: "03"
subsystem: infra
tags: [pulumi, eso, temporal, gcp-secret-manager, k8s-secrets, credential-migration]
dependency_graph:
  requires:
    - 06-01 (protect=True + test scaffold)
  provides:
    - temporal-db-password GCP SM secret + custom ExternalSecret in secrets.py
    - temporal.py using existingSecret/secretKey pattern (no Pulumi stack secrets)
    - Schema Job reading DB password from ESO-synced K8s Secret env var
  affects:
    - infra/components/secrets.py
    - infra/components/temporal.py
    - infra/Pulumi.dev.yaml
tech_stack:
  added: []
  patterns:
    - ESO ExternalSecret with custom secretKey mapping (overrides default uppercase slug)
    - Helm existingSecret/secretKey pattern for Temporal DB credentials
    - K8s Secret env var injection (valueFrom.secretKeyRef) in batch Jobs
    - Resource limits on schema Job containers (main + cloud-sql-proxy sidecar)
key_files:
  created: []
  modified:
    - infra/components/secrets.py
    - infra/components/temporal.py
    - infra/Pulumi.dev.yaml
decisions:
  - "D-06/D-07: Temporal DB password moved from Pulumi stack secrets to GCP SM, synced via custom ESO ExternalSecret with key 'password'"
  - "temporal_db_user remains a hardcoded constant ('temporal') — username is not sensitive; only the password required Secret Manager"
  - "Custom ExternalSecret (ext-secret-temporal-db-credentials) overwrites the generic loop entry for temporal-db-password to produce key 'password' instead of 'TEMPORAL_DB_PASSWORD'"
  - "Schema Job command chain rebuilt as static string using $TEMPORAL_DB_PASSWORD shell env var; removed pulumi.Output.all dependency"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-04-11T23:50:00Z"
  tasks_completed: 2
  files_changed: 3
---

# Phase 06 Plan 03: Temporal DB Credential Migration to ESO Summary

**One-liner:** Temporal DB password migrated from Pulumi encrypted stack secrets to GCP Secret Manager, synced via a custom ESO ExternalSecret to a K8s Secret with key `password`, consumed by both the Helm release (`existingSecret`) and schema migration Job (`TEMPORAL_DB_PASSWORD` env var).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add temporal-db-password to GCP SM and custom ExternalSecret in secrets.py | 6fa7dfe | infra/components/secrets.py |
| 2 | Replace Pulumi stack secrets with existingSecret in temporal.py; clean Pulumi.dev.yaml | c93f2f0 | infra/components/temporal.py, infra/Pulumi.dev.yaml |

## What Was Built

### Task 1: secrets.py — GCP SM Secret + Custom ExternalSecret

**_SECRET_DEFINITIONS:** Added `("temporal-db-password", "temporal", "temporal-db-credentials")`. This causes the generic GCP SM loop to create `{ENV}-temporal-db-password` in Secret Manager.

**Custom ExternalSecret:** Added `ext-secret-temporal-db-credentials` after the generic ExternalSecret loop. This overwrites the generic entry (`external_secrets["temporal-db-password"]`) in the dict with a resource that maps the GCP SM value to K8s Secret key `"password"` (not the default `"TEMPORAL_DB_PASSWORD"` that the generic loop would produce). The target K8s Secret is named `temporal-db-credentials` in the `temporal` namespace. `depends_on` includes `secret_stores["temporal"]` and `sm_secrets["temporal-db-password"]`.

### Task 2: temporal.py — ESO-based credential consumption

**Import changes:**
- Removed `cfg` from `from config import ENV, cfg`
- Added `from components.secrets import external_secrets`

**Credential constants:**
- Removed `_TEMPORAL_DB_USER = cfg.require_secret("temporal_db_user")` — replaced with hardcoded `_TEMPORAL_DB_USER = "temporal"` (username is not sensitive)
- Removed `_TEMPORAL_DB_PASS = cfg.require_secret("temporal_db_password")`
- Removed `_build_schema_commands()` helper function and `pulumi.Output.all()` call

**Schema commands:** Rebuilt as a static f-string using `$TEMPORAL_DB_PASSWORD` shell variable. All six `temporal-sql-tool` invocations now reference the env var instead of a Pulumi Output.

**Schema Job container:**
- `env` block added to `temporal-schema-migration` container: `TEMPORAL_DB_PASSWORD` sourced via `valueFrom.secretKeyRef` pointing to `temporal-db-credentials` / `password`
- Resource limits added to main container: requests `{cpu: 100m, memory: 256Mi}`, limits `{cpu: 500m, memory: 512Mi}`
- Resource limits added to `cloud-sql-proxy` init container: requests `{cpu: 100m, memory: 128Mi}`, limits `{cpu: 200m, memory: 256Mi}`
- `depends_on` on schema Job extended with `external_secrets["temporal-db-password"]`

**Helm values:** In `server.config.persistence.default.sql`, replaced `"password": _TEMPORAL_DB_PASS` with `"existingSecret": "temporal-db-credentials"` and `"secretKey": "password"`. Username stays as `"user": _TEMPORAL_DB_USER` (hardcoded string `"temporal"`).

**temporal_release:** `depends_on` extended with `external_secrets["temporal-db-password"]`.

**Pulumi.dev.yaml:** Removed `vici-infra:temporal_db_user` and `vici-infra:temporal_db_password` (and their `secure:` values). File reduced from 13 lines to 9 lines. Staging and prod never had these stack secrets (confirmed by research).

## Verification

```
pytest tests/infra/test_phase6_static.py::TestTemporalESO -x -v
4 passed in 0.01s
```

All four TestTemporalESO assertions pass:
- `test_temporal_py_no_require_secret_user` — PASSED
- `test_temporal_py_no_require_secret_password` — PASSED
- `test_temporal_py_uses_existing_secret` — PASSED
- `test_secrets_py_has_temporal_db_password` — PASSED

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The GCP SM secret `{ENV}-temporal-db-password` must be created manually in GCP Console (or via `gcloud secrets create`) before `pulumi up` can succeed. This is documented in the plan's `user_setup` section as an intentional pre-deployment gate, not a stub — the infrastructure code is complete.

## Threat Surface Scan

| Flag | File | Description |
|------|------|-------------|
| threat_flag: info_disclosure_reduced | infra/Pulumi.dev.yaml | Temporal DB password removed from version-controlled encrypted config — reduces blast radius if encryption key is compromised |
| threat_flag: k8s_secret_write | infra/components/secrets.py | ESO ExternalSecret with `creationPolicy: Owner` is sole writer to `temporal-db-credentials` K8s Secret — mitigates tampering (T-6-02b) |

Both flags are mitigations, not new attack surface. No new network endpoints or auth paths introduced.

## Self-Check: PASSED

- [x] infra/components/secrets.py contains `temporal-db-password` (4 occurrences)
- [x] infra/components/secrets.py contains `"secretKey": "password"` custom key mapping
- [x] infra/components/secrets.py contains `temporal-db-credentials` as target name
- [x] infra/components/secrets.py contains `ext-secret-temporal-db-credentials` as Pulumi resource name
- [x] infra/components/temporal.py does NOT contain `cfg.require_secret`
- [x] infra/components/temporal.py contains `"existingSecret": "temporal-db-credentials"`
- [x] infra/components/temporal.py contains `"secretKey": "password"`
- [x] infra/components/temporal.py contains `TEMPORAL_DB_PASSWORD` as env var name
- [x] infra/components/temporal.py contains `ResourceRequirementsArgs` (resource limits)
- [x] infra/Pulumi.dev.yaml does NOT contain `temporal_db_user` or `temporal_db_password`
- [x] Commit 6fa7dfe exists (Task 1)
- [x] Commit c93f2f0 exists (Task 2)
- [x] pytest tests/infra/test_phase6_static.py::TestTemporalESO -x exits 0
