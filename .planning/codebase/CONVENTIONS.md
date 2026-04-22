# Coding Conventions

**Analysis Date:** 2026-04-22

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions observed
- Domain modules use single-word names: `router.py`, `service.py`, `schemas.py`, `models.py`, `repository.py`, `constants.py`, `exceptions.py`, `dependencies.py`, `utils.py`
- Module-level aggregator at root: `src/models.py` re-exports all SQLModel table classes for Alembic discovery

**Functions / Methods:**
- `snake_case` for all functions, methods, and module-level helpers
- Private helpers prefixed with `_`: `_configure_structlog()`, `_configure_otel()`, `_add_otel_context()`, `_update_gauges()` (`src/main.py`)
- Private repository / service methods prefixed with `_`: `_persist()` (`src/repository.py`), `_dp_select()`, `_build_candidates()`, `_sort_results()` (`src/matches/service.py`)
- Static methods on repository classes are named imperatively: `check_idempotency`, `enforce_rate_limit`, `get_or_create`

**Classes:**
- `PascalCase` throughout
- Domain-specific suffixes: `Service`, `Repository`, `Handler`, `Settings`, `Workflow`, `Activity`
- Exception classes use descriptive names: `TwilioSignatureInvalid`, `DuplicateMessageSid`, `RateLimitExceeded`, `EarlyReturn`

**Variables:**
- `snake_case` for all local and module-level variables
- Module-level singletons use leading underscore: `_orchestrator`, `_openai_client` (`src/temporal/activities.py`)
- Tracer instances consistently named `tracer` at module level
- Logger instances consistently named `log` at module level

**Constants:**
- `UPPER_SNAKE_CASE` for all constants; type-annotated
- Grouped per domain in `constants.py` files — no magic numbers in logic files
- Examples: `GPT_CALL_TIMEOUT_SECONDS`, `MAX_MESSAGES_PER_WINDOW`, `WORKER_SHUTDOWN_TIMEOUT_SECONDS`, `CENTS_PER_DOLLAR`

**Database Tables:**
- `lower_snake_case` singular: `user`, `message`, `job`, `work_goal`, `audit_log`, `rate_limit`, `match`
- `_at` suffix for datetime columns: `created_at`
- Explicit FK/index names via `POSTGRES_INDEXES_NAMING_CONVENTION` in `src/database.py`

## Code Style

**Formatter:**
- `ruff format` — enforced in CI via `uv run ruff format --check src/ tests/ infra/`
- Config in `pyproject.toml` (`[tool.ruff]`) targeting `py312`

**Linter:**
- `ruff check` with rules `E` (pycodestyle), `F` (pyflakes), `I` (isort)
- Per-file ignore: `src/extraction/prompts.py` exempts `E501` (long lines in LLM prompts)
- No `W`, `N`, `ANN`, `D` (pydocstyle) rules — type checking and docstring completeness are **not** linter-enforced

**Static Type Checking:**
- **No mypy or pyright configured.** There is no `mypy.ini`, `.mypy.ini`, or pyright config in the project root.
- Type annotations are present but incomplete. Notable gaps:
  - `run_worker(client: Client, orchestrator, openai_client)` in `src/temporal/worker.py:28` — `orchestrator` and `openai_client` parameters lack type annotations
  - `ExtractionService.__init__(self, openai_client, settings)` in `src/extraction/service.py:41` — both constructor parameters untyped
  - Route handler `receive_sms(... gates=Depends(enforce_rate_limit))` in `src/sms/router.py:28` — `gates` lacks annotation
- Python 3.12 builtins used in annotations (`list[T]`, `dict[K,V]`) — correct modern style, no `from __future__ import annotations` needed
- `Optional[T]` from `typing` still used in SQLModel models (required for SQLModel compatibility)

## Import Organization

**Order enforced by ruff isort (`I` rules):**
1. Standard library (`from datetime import ...`, `import asyncio`)
2. Third-party (`from fastapi import ...`, `import structlog`)
3. First-party src (`from src.config import ...`)

**Path Aliases:** None — always `from src.<domain>.<module> import <name>`

**Cross-domain imports:** Use explicit module path, not relative:
```python
from src.sms import service as sms_service        # src/sms/dependencies.py
from src.pipeline.handlers.job_posting import JobPostingHandler
```

**`noqa` usage:**
- `# noqa: F401` used legitimately in `src/models.py` (import-for-side-effect) and `tests/conftest.py`
- No suppression of logic-relevant lint warnings found

## Error Handling

**Patterns:**
- Domain exceptions live in `<domain>/exceptions.py` — e.g., `src/sms/exceptions.py`
- Exception hierarchy uses inheritance for grouping: `DuplicateMessageSid(EarlyReturn)`, `RateLimitExceeded(EarlyReturn)`
- FastAPI exception handlers registered in `create_app()` in `src/main.py`: `TwilioSignatureInvalid` → 403 JSON, `EarlyReturn` → 200 empty TwiML
- Never raise `HTTPException` on Twilio webhook paths — Twilio retries on 4xx (enforced by `EarlyReturn` pattern, documented in `src/sms/exceptions.py:12`)
- Temporal activities raise `ApplicationError(non_retryable=True)` for unrecoverable errors and `ApplicationError(non_retryable=False)` for retriable ones
- External I/O failures (Pinecone, Twilio) are caught at handler level, logged, and swallowed to prevent pipeline abort — `src/pipeline/handlers/job_posting.py`, `src/pipeline/handlers/unknown.py`
- Bare `except Exception as exc:` used (not `except BaseException`) in retry/fallback blocks

## Logging

**Framework:** `structlog` — configured in `src/main.py:_configure_structlog()`

**Configuration:**
- `structlog.configure()` called once at lifespan startup
- Processors: `add_log_level` → `_add_otel_context` (injects `trace_id`, `span_id`) → `TimeStamper(fmt="iso")` → `JSONRenderer()`
- Level: `INFO` and above (`make_filtering_bound_logger(logging.INFO)`)
- Output: stdout via `PrintLoggerFactory`

**Usage Pattern:**
```python
log = structlog.get_logger()  # module-level singleton, acquired once

log.info("gpt_classified", message_type=result.message_type, phone_hash=phone_hash)
log.warning("sync-pinecone-queue: upsert failed", job_id=row["job_id"], error=str(exc))
log.error("unknown_reply_failed", message_sid=ctx.message_sid, error=str(exc))
log.critical("gauge_updater: repeated DB failures, metric unreliable", ...)
```

**Key rules:**
- Log event string is a `snake_case` or `kebab-case` identifier. Context passed as keyword arguments.
- Phone numbers are hashed with SHA-256 before logging. `phone_e164` never appears in logs — only `phone_hash`.

## Comments

**When to Comment:**
- Class/function-level docstrings on public APIs and non-obvious abstractions
- Inline comments for non-obvious design constraints, referencing decision codes as `D-XX`, `SEC-XX` where applicable (e.g., `# per D-06`, `# SEC-04`)
- `# noqa: F401` with explanation where imports are side-effect-only

**Docstring style:** Single-line or short multi-line. No formal parameter documentation (`:param:`, `:returns:`) — not enforced by linter.

```python
"""SHA-256 hash of E.164 phone number. Twilio From is already E.164."""

"""Raised by dependencies to short-circuit processing with HTTP 200 TwiML response.
FastAPI exception handlers converts this to HTTP 200. Never raise HTTPException
for Twilio webhook paths — Twilio retries on 4xx responses."""
```

## Function Design

**Async / Sync:**
- `async def` for all I/O-bound routes, dependencies, service methods, and repository methods
- `def` for pure computation: `_dp_select()`, `_sort_results()`, `dollars_to_cents()`, `format_match_sms()`
- Blocking sync library calls (`twilio_client.messages.create`) wrapped with `asyncio.to_thread()` — see `src/pipeline/handlers/unknown.py:45`

**Parameters:**
- Services accept dependencies via constructor injection; never call `get_settings()` inside service methods
- Repository methods receive `AsyncSession` as first parameter after `self`/`cls`
- All `@staticmethod` repository class methods still accept `session` as first arg

**Return values:**
- Repositories return the persisted entity (flush-only — caller commits)
- Services return domain objects or Pydantic schemas
- Temporal activities return `"ok"` string on success

## Module Design

**Exports:** No `__all__` defined — not a library; all public symbols discoverable by linter
**Barrel files:** `src/models.py` is the only barrel — exists solely to trigger SQLModel table registration before Alembic `create_all`
**`__init__.py` files:** Present but empty in all domain directories

## Pydantic / SQLModel Patterns

**Schema validation:**
- `Field(min_length=..., max_length=..., gt=0)` validators on all Pydantic input schemas (see `src/extraction/schemas.py`)
- `Literal["hourly", "flat", "unknown"]` used to constrain enumerable fields at schema level
- DB-level `CheckConstraint` mirrors schema-level validation for defense-in-depth (e.g., `src/jobs/models.py:11-21`)

**Settings:**
- `Settings(BaseSettings)` with flat env vars remapped into nested sub-models via `@model_validator(mode="after")` — see `src/config.py`
- `lru_cache(maxsize=1)` on `get_settings()` ensures singleton; `get_settings.cache_clear()` called in tests to reset
- Fail-fast `@model_validator` raises `ValueError` on empty required credentials at startup

## Pre-commit Hooks

**No pre-commit configuration exists.** There is no `.pre-commit-config.yaml` in the project root. All lint and format checks run only in CI, not locally before commit.

## CI Gates

CI runs on push/PR to `main` via `.github/workflows/ci.yml`:

1. `uv run ruff check src/ tests/ infra/` — lint
2. `uv run ruff format --check src/ tests/ infra/` — format diff check
3. `uv run pytest tests/ -x --tb=short -q` — full test suite (fail-fast `-x`)

**Gaps:**
- No type-check step (`mypy` or `pyright` absent from CI)
- No coverage threshold enforcement (`pytest-cov` installed as dev dep but not invoked in CI)
- `INNGEST_DEV` and `INNGEST_BASE_URL` still present as CI env vars (`ci.yml:34-35`) despite Inngest having been removed; these are dead config

---

*Convention analysis: 2026-04-22*
