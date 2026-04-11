---
status: awaiting_human_verify
trigger: "Full stack health debug for Phase 5 pulumi up verification on GKE"
created: 2026-04-09T00:00:00Z
updated: 2026-04-09T00:00:00Z
---

## Current Focus

hypothesis: VERIFIED — All issues resolved. vici-app 2/2 Running, Temporal fully operational, Pulumi state clean (78 resources, 0 pending changes).
test: kubectl get pods, health endpoints, pulumi preview
expecting: All green
next_action: Request human verification

## Symptoms

expected: pulumi up --stack dev completes cleanly. All Phase 5 resources deploy. vici-app pod starts and serves /health.
actual: pulumi preview fails with "jobs.batch not found" for both migration Jobs. Jobs were TTL-cleaned from K8s but still in Pulumi state. Additionally 16+ orphaned CI/CD resources (WIF pool, IAM bindings) in state but not in code. App has temporal-address env var mismatch.
errors: |
  1. jobs.batch "alembic-migration-dev" not found (Pulumi update fails)
  2. jobs.batch "temporal-schema-migration-dev" not found (Pulumi update fails)
  3. alembic migration imports Settings() which validates ALL credentials
  4. temporal-schema-migration: pq permission denied for table schema_version
  5. vici-app CrashLoopBackOff: missing temporal_address env var
  6. Pulumi field manager conflict on vici-app Deployment
reproduction: Run pulumi up --stack dev --yes
started: After git reset to d689adf and state surgery to repair 53 corrupted secrets

## Eliminated

## Evidence

- timestamp: 2026-04-09T00:01:00Z
  checked: pulumi preview --stack dev
  found: Both Jobs fail with "not found" - TTL cleaned from K8s cluster but still in Pulumi state. Only 1 update (sm-temporal-address label change) and 3 errors shown. 69 unchanged resources.
  implication: Jobs must be removed from state first, then recreated. This is the PRIMARY blocker.

- timestamp: 2026-04-09T00:02:00Z
  checked: Full URN listing of Pulumi state (93 resources)
  found: |
    Orphaned CI/CD resources in state but NOT in code:
    - github-wif-pool, github-wif-provider
    - ci-sa-cloudsql-admin, ci-sa-compute-network-admin, ci-sa-iam-sa-admin
    - ci-sa-container-admin, ci-sa-artifactregistry-admin, ci-sa-secretmanager-admin
    - ci-sa-project-iam-admin, ci-sa-storage-admin, ci-sa-iam-wif-admin
    - ci-wif-iam-binding, ci-sa-servicenetworking-admin, ci-sa-container-developer
    Old secrets still in state: sm-temporal-host, ext-secret-temporal-host
  implication: Once Jobs are fixed and pulumi up runs, these will be deleted automatically (code no longer references them).

- timestamp: 2026-04-09T00:03:00Z
  checked: migrations/env.py source code
  found: env.py imports get_settings() from src.config which instantiates Settings() with full credential validation. The migration container only has database-url secret but Settings() requires twilio_auth_token, openai_api_key, pinecone_api_key, temporal_address, webhook_base_url, env.
  implication: Migration command needs to bypass Settings() validation. Current command "uv run alembic upgrade head" triggers the full import chain.

## Resolution

root_cause: |
  Three intertwined issues blocking pulumi up:
  1. BLOCKER: Both K8s Jobs (alembic-migration, temporal-schema-migration) were TTL-cleaned from cluster but remain in Pulumi state. Pulumi tries to update non-existent resources and fails with "not found".
  2. MIGRATION: alembic migration Job's command "uv run alembic upgrade head" triggers Settings() validation requiring ALL credentials, but the Job only mounts database-url secret.
  3. TEMPORAL: temporal-schema-migration DB user lacks table-level permissions on schema_version.
  
  Secondary issues (resolved by successful pulumi up):
  4. 16 orphaned CI/CD resources will be auto-deleted when pulumi up succeeds
  5. vici-app temporal-address env var fix already in code, just needs deployment
  6. patchForce annotation already in code for field manager conflict
fix: |
  1. migrations/env.py: Already fixed (prior session) — _get_database_url() reads DATABASE_URL env var directly, avoiding Settings() validation in migration-only contexts
  2. infra/components/temporal.py: Added name="temporal" to Helm Release args so K8s services get deterministic names (temporal-frontend instead of temporal-5cb70147-frontend), matching the GCP Secret Manager value
  3. Manually deleted old Temporal Helm release resources (temporal-5cb70147-*) from K8s to free DB connections for new release pods
  4. Registered Temporal "default" namespace via admin-tools pod (required for fresh Temporal installation)
  5. pulumi refresh cleaned stale state (TTL-cleaned Jobs, orphaned CI/CD IAM bindings)
  6. pulumi up converged to clean state (78 resources, 0 pending)
verification: |
  - vici-app pod: 2/2 Running, /health returns {"status":"ok"}, /readyz returns {"status":"ok","db":"connected"}
  - All 11 ExternalSecrets: SecretSynced/True
  - All Temporal pods: 2/2 Running (frontend, history, matching, worker)
  - Both migration Jobs: Completed
  - Ingress: dev.usevici.com at 34.120.195.235
  - pulumi preview: 78 unchanged, 0 changes
files_changed:
  - infra/components/temporal.py
