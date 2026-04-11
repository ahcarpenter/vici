---
status: fixing
trigger: "temporal-schema-migration Job fails with exit code 1 in CD Dev after CRD cleanup fixes"
created: 2026-04-06T23:30:00Z
updated: 2026-04-06T23:30:00Z
---

## Current Focus

hypothesis: TBD — need actual migration container logs first
test: fetch pod logs via kubernetes MCP or gcloud logging
expecting: actual stderr from temporal-sql-tool (connection refused, auth failed, schema version mismatch, etc.)
next_action: list pods in temporal namespace and read container logs

## Symptoms

expected: pulumi up completes; temporal-schema-migration Job Succeeded:1
actual: Job replaced (~spec), pod temporal-schema-migration-dev-hcht6 runs, temporal-schema-migration container exits 1, BackoffLimitExceeded
errors: container "temporal-schema-migration" completed with exit code 1; cloud-sql-proxy sidecar PodInitializing
reproduction: push to main -> CD Dev runs pulumi up --stack dev
started: after CRD cleanup fixes unmasked downstream failures

## Eliminated

## Evidence

- checked: gcloud logging read for container=temporal-schema-migration
  found: `pq: password authentication failed for user "vici"` — cloud-sql-proxy reachable at 127.0.0.1:5432; Postgres rejects auth
- checked: gcloud sql users list --instance=vici-temporal-dev
  found: only the built-in `postgres` user exists; no `vici` user
- checked: infra/components/database.py
  found: no gcp.sql.User resource for the temporal instance — DB user was never provisioned
- checked: infra/components/temporal.py lines 37-38
  found: `_TEMPORAL_DB_USER = cfg.require_secret("temporal_db_user")` / `temporal_db_password` — Pulumi config has the creds but nothing creates the matching Postgres user

## Resolution

root_cause: The temporal Cloud SQL instance (vici-temporal-dev) never had the `vici` Postgres user created. `infra/components/database.py` provisions the DatabaseInstance and two databases (temporal, temporal_visibility) but no `gcp.sql.User` resource. The Pulumi config contains `temporal_db_user`/`temporal_db_password` secrets used by both the schema migration Job and the Helm release, but the user doesn't exist on the actual SQL instance, so temporal-sql-tool's auth fails with `pq: password authentication failed for user "vici"` and exits 1.
fix: Add a `gcp.sql.User` resource in database.py that creates the user on temporal_db_instance using the same secrets temporal.py reads (temporal_db_user / temporal_db_password). Wire it as a dependency of temporal_schema_job so the user exists before the migration runs. Do the same for app_db_instance to prevent the equivalent failure downstream.
verification:
files_changed: []
