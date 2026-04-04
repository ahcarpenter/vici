---
created: 2026-04-04T15:46:52.855Z
title: Validate Postgres alongside SQLite in tests and cross-dialect fallbacks
area: testing
files:
  - tests/conftest.py
  - src/matches/repository.py
---

## Problem

The test suite uses SQLite for speed and portability, but several production code paths are explicitly written around SQLite limitations (e.g., `try/except IntegrityError` instead of `pg_insert().on_conflict_do_nothing()`). This means dialect-specific Postgres behavior — CHECK constraints, ENUM types, `ON CONFLICT DO NOTHING`, index naming conventions — is never exercised in CI. Bugs that only manifest on Postgres can slip through undetected.

Surfaced during Phase 3 planning: `MatchRepository.persist_matches()` uses a cross-dialect `try/except IntegrityError` fallback specifically because the test DB is SQLite.

## Solution

Add a Postgres test configuration (e.g., `pytest --db=postgres` or a separate `conftest_pg.py`) that runs the full test suite against a real Postgres instance (Docker Compose service already exists). Key areas to validate:

- `ON CONFLICT DO NOTHING` / `on_conflict_do_nothing()` upsert paths
- CHECK constraints (e.g., `pay_rate > 0`, `status IN (...)`)
- Any SQLAlchemy Enum columns if introduced
- Index naming convention enforcement (`POSTGRES_INDEXES_NAMING_CONVENTION`)
- Alembic migrations applied cleanly to Postgres (not just SQLite)

Consider running Postgres tests in CI on PRs touching `src/*/repository.py` or migration files.
