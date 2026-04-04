---
created: 2026-04-04T15:47:57.595Z
title: Ensure environment parity across local dev, staging, and production
area: tooling
files:
  - docker-compose.yml
  - .env.example
---

## Problem

Local dev, staging, and production environments may diverge in ways that cause "works on my machine" bugs — different service versions (Postgres, Redis, Temporal), missing env vars, different database dialects (SQLite in tests vs Postgres in prod), or config values that aren't reflected across all tiers. This risk increases as the stack grows (Temporal, Jaeger, Prometheus, etc.).

## Solution

Audit all three environments and close gaps:

- Pin service versions in Docker Compose to match production (Postgres, Temporal, Jaeger)
- Ensure `.env.example` is complete and documents every variable used in the codebase
- Confirm test suite runs against Postgres (not just SQLite) to match production dialect
- Validate Alembic migrations apply cleanly in all environments
- Document environment setup in README so staging mirrors prod configuration
