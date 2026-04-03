---
phase: quick-260403-4ps
plan: 01
subsystem: infra/config
tags: [docker-compose, env-files, configuration, secrets]
dependency_graph:
  requires: []
  provides: [per-service-env-files]
  affects: [docker-compose.yml, .gitignore]
tech_stack:
  added: []
  patterns: [per-service env file injection]
key_files:
  created:
    - .env.app.development
    - .env.postgres.development
    - .env.temporal.development
    - .env.temporal-ui.development
    - .env.opensearch.development
    - .env.grafana.development
    - .env.jaeger-query.development
    - .env.app.example
    - .env.postgres.example
    - .env.temporal.example
    - .env.temporal-ui.example
    - .env.opensearch.example
    - .env.grafana.example
    - .env.jaeger-query.example
  modified:
    - docker-compose.yml
    - .gitignore
decisions:
  - Per-service env files use .env.{service}.{env} naming — supports staging/production gitignore while tracking dev+example
  - .gitignore updated to !.env.*.development and !.env.*.example — staging/production always gitignored
metrics:
  duration: 5m
  completed: 2026-04-03
  tasks_completed: 2
  files_created: 14
  files_modified: 2
---

# Quick Task 260403-4ps: Per-Service Env File Refactor Summary

**One-liner:** Extracted all docker-compose inline environment blocks into per-service `.env.{service}.development` files, with matching `.env.{service}.example` documentation files and updated .gitignore patterns.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create per-service development env files and examples | b404129 | 14 new env files, .gitignore |
| 2 | Refactor docker-compose.yml to use env_file only | cf65608 | docker-compose.yml |

## Changes

### docker-compose.yml

All 7 services that previously used inline `environment:` blocks now use `env_file:` exclusively:
- `postgres` → `.env.postgres.development`
- `opensearch` → `.env.opensearch.development`
- `jaeger-query` → `.env.jaeger-query.development`
- `app` → `.env.app.development` (replaced `env_file: .env` + `environment:` override block)
- `temporal` → `.env.temporal.development`
- `temporal-ui` → `.env.temporal-ui.development`
- `grafana` → `.env.grafana.development`

`jaeger-collector` and `prometheus` have no env vars — no `env_file:` added.

### .gitignore

Old pattern:
```
.env
.env.*
!.env.example
!.env.development
```

New pattern:
```
# Environment files — secrets
.env
.env.*

# Allow committed development defaults and examples
!.env.*.development
!.env.*.example
```

## Verification

- `docker compose config` exits 0 — all env_file references resolve
- `grep -n "environment:" docker-compose.yml` → no matches
- `.env.app.staging` is gitignored (confirmed via git status test)
- All 14 new files committed and tracked

## Deviations from Plan

None — plan executed exactly as written. The only ordering change was updating .gitignore before staging the new env files (required because the old pattern blocked `git add`).

## Self-Check: PASSED

- All 14 env files exist and are committed (b404129)
- docker-compose.yml committed with no environment: blocks (cf65608)
- docker compose config passes with no errors
- Staging files correctly gitignored
