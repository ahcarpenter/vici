---
phase: quick-2
plan: 2
subsystem: infrastructure
tags: [docker-compose, configuration, env-vars]
dependency_graph:
  requires: []
  provides: [parameterised-compose-urls]
  affects: [docker-compose.yml, .env.example]
tech_stack:
  added: []
  patterns: [shell-default-substitution]
key_files:
  created: []
  modified:
    - docker-compose.yml
    - .env.example
decisions:
  - "Leave DATABASE_URL, INNGEST_BASE_URL, OTEL_EXPORTER_OTLP_ENDPOINT as-is; they use Compose-internal service names not relevant outside docker-compose"
  - "INNGEST_APP_URL is documented in .env.example but NOT added to src/config.py — it is a Compose-only concern"
metrics:
  duration: 5m
  completed: 2026-03-08
---

# Quick Task 2: Parameterise Env-Sensitive URLs in docker-compose.yml Summary

One-liner: Replaced two hardcoded URL strings in docker-compose.yml with `${VAR:-default}` shell substitution and documented the new `INNGEST_APP_URL` variable in .env.example.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Parameterise hardcoded URLs in docker-compose.yml | 43303c7 | docker-compose.yml |
| 2 | Document INNGEST_APP_URL in .env.example | 2bb4d6c | .env.example |

## Changes Made

### docker-compose.yml

- `WEBHOOK_BASE_URL` on the `app` service now uses `${WEBHOOK_BASE_URL:-http://localhost:8000}`, consistent with the existing `GIT_SHA` pattern on the same service.
- `inngest` service command now uses `${INNGEST_APP_URL:-http://app:8000}/api/inngest` so the Docker Compose service name and port are overridable without editing the file.

### .env.example

- Added `INNGEST_APP_URL=http://app:8000` under the Inngest local dev section, after `INNGEST_BASE_URL`, with a comment clarifying it is used only by docker-compose.yml.

## Deviations from Plan

None - plan executed exactly as written.

## Verification

All three grep checks passed:
- `WEBHOOK_BASE_URL:-` found in docker-compose.yml
- `INNGEST_APP_URL:-` found in docker-compose.yml
- `INNGEST_APP_URL` found in .env.example

Test suite: 76 passed, 0 failed.

## Self-Check: PASSED

- docker-compose.yml updated with both substitutions
- .env.example updated with INNGEST_APP_URL
- Commits 43303c7 and 2bb4d6c verified in git log
