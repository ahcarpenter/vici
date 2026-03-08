---
phase: quick-1
plan: 1
subsystem: configuration
tags: [env-vars, observability, otel, docker-compose, render]
key-files:
  modified:
    - .env.example
    - docker-compose.yml
    - render.yaml
decisions:
  - OTEL_SERVICE_NAME hardcoded to "vici" in docker-compose and render.yaml — value is immutable per service identity
  - OTEL_EXPORTER_OTLP_ENDPOINT uses sync:false in render.yaml — production collector endpoint depends on deployment topology
metrics:
  duration: "~5 minutes"
  completed: "2026-03-08"
  tasks_completed: 2
  files_modified: 3
---

# Quick Task 1: Ensure All Env Variables Are Declared — Summary

**One-liner:** Fixed `OTL_SERVICE_NAME` typo to `OTEL_SERVICE_NAME` in `.env.example` and added both OTEL vars to `docker-compose.yml` app service and `render.yaml` production env block.

## What Was Done

### Task 1 — Fix .env.example typo

`.env.example` line 41 had `OTL_SERVICE_NAME=vici` (missing the "E"). Renamed to `OTEL_SERVICE_NAME=vici`. This typo would cause `pydantic-settings` to silently fall back to its default value for `otel_service_name` in any environment that sourced this file directly.

All other Settings flat fields were already present and correctly named.

### Task 2 — Add OTEL vars to docker-compose.yml and render.yaml

**docker-compose.yml:** The `app` service environment block already set `OTEL_EXPORTER_OTLP_ENDPOINT` but was missing `OTEL_SERVICE_NAME`. Added `OTEL_SERVICE_NAME: vici` in the same block.

**render.yaml:** The production envVars list was missing both observability vars. Added after the `GIT_SHA` entry:
- `OTEL_EXPORTER_OTLP_ENDPOINT` with `sync: false` (operator must set production collector URL)
- `OTEL_SERVICE_NAME` with `value: "vici"` (hardcoded — never changes)

## Verification

All automated checks passed:
- `grep "OTEL_SERVICE_NAME" .env.example` — present
- `grep "OTL_SERVICE_NAME" .env.example` — absent
- Both vars present in `docker-compose.yml` and `render.yaml`
- `uv run pytest -x -q` — 76 passed, 0 failures

## Deviations from Plan

None — plan executed exactly as written.

## Commits

- `c2b8edc`: fix(quick-1): rename OTL_SERVICE_NAME to OTEL_SERVICE_NAME in .env.example
- `18b907e`: fix(quick-1): add OTEL_SERVICE_NAME to docker-compose and render.yaml
