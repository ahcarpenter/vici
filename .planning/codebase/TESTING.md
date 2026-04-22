# Testing Patterns

**Analysis Date:** 2026-04-22

## Test Framework

**Runner:**
- `pytest` 9.0.2
- Config: `pyproject.toml` (`[tool.pytest.ini_options]`)

**Async support:**
- `pytest-asyncio` 1.3.0 with `asyncio_mode = "auto"` — all async test functions run automatically without `@pytest.mark.asyncio` decoration (though many tests still carry it redundantly from before the `auto` mode was set)

**Assertion Library:**
- Standard `assert` statements throughout — no custom assertion helpers

**HTTP client:**
- `httpx.AsyncClient` with `ASGITransport` — full ASGI stack, not mocked routing

**Coverage:**
- `pytest-cov` 7.0.0 installed as a dev dependency
- **Coverage is not run in CI.** No `--cov` flag in `.github/workflows/ci.yml`. No coverage threshold configured. No `.coveragerc`.

**Run Commands:**
```bash
uv run pytest tests/ -x --tb=short -q        # CI command (fail-fast)
uv run pytest tests/                          # full suite, verbose
uv run pytest tests/sms/                     # single domain
uv run pytest tests/ --cov=src --cov-report=term-missing  # with coverage (not in CI)
```

## Test File Organization

**Location:** Separate `tests/` tree mirroring `src/` domain structure — not co-located with source.

**Naming:**
- Test files: `test_<subject>.py`
- Test functions: `test_<what_is_verified>()`
- Test classes (rare): `TestPascalCase` — used in `tests/test_3nf_normalization.py`, `tests/infra/test_cd_static.py`

**Structure:**
```
tests/
├── conftest.py                        # session/function fixtures, factory fixtures
├── extraction/
│   ├── conftest.py                    # make_mock_openai_client, mock_pinecone_client helpers
│   ├── test_extraction_service_spans.py
│   ├── test_metrics.py
│   ├── test_persistence.py
│   ├── test_schemas.py
│   └── test_service.py
├── infra/
│   ├── test_cd_static.py              # AST-based static assertions on infra/
│   ├── test_cd_workflows_static.py
│   ├── test_observability_static.py
│   └── test_phase6_static.py
├── integration/
│   ├── test_job_posting.py
│   ├── test_unknown.py
│   └── test_worker_goal.py
├── matches/
│   └── test_match_service.py
├── sms/
│   └── test_webhook.py
├── temporal/
│   ├── test_activities.py
│   ├── test_spans.py
│   └── test_worker.py
├── test_3nf_normalization.py
├── test_config.py
├── test_health.py
├── test_logging.py
├── test_otel_config.py
├── test_pipeline_hardening.py
├── test_pipeline_orchestrator.py
└── test_repositories.py
```

## Test Structure

**Suite Organization:**
```python
# Standalone async functions (most common pattern)
@pytest.mark.asyncio
async def test_classify_job():
    ...

# Class-based grouping for related assertions on same target
class TestImageTagConfig:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = _read_source(INFRA_DIR / "config.py")

    def test_config_exports_image_tag(self) -> None:
        ...
```

**Representative test files:**
- `tests/sms/test_webhook.py` — full HTTP layer integration tests against live ASGI app
- `tests/temporal/test_activities.py` — unit tests of Temporal activity functions with heavy mocking
- `tests/matches/test_match_service.py` — repository + service integration tests against in-memory SQLite
- `tests/test_pipeline_orchestrator.py` — orchestrator unit tests + OTel span assertion tests
- `tests/infra/test_cd_static.py` — AST-based static analysis of infrastructure Python code
- `tests/extraction/test_service.py` — unit tests of `ExtractionService` with mock OpenAI client

## Test Types

**Unit Tests (majority):**
- Scope: single class or function; all external I/O mocked
- Examples: `tests/extraction/test_service.py`, `tests/temporal/test_activities.py`, `tests/test_pipeline_orchestrator.py`
- Pattern: construct subject under test with `AsyncMock` / `MagicMock` injected dependencies

**Integration Tests (DB-backed):**
- Scope: service + repository + SQLite in-memory DB via `async_session` fixture
- Examples: `tests/matches/test_match_service.py`, `tests/test_repositories.py`, `tests/sms/test_webhook.py`
- Use `AsyncClient` + `ASGITransport` for HTTP-layer tests — real app lifecycle with session override

**Static / Structural Tests:**
- Scope: parse and assert on Python source files in `infra/` using `ast` and text search
- Examples: `tests/infra/test_cd_static.py`, `tests/infra/test_cd_workflows_static.py`
- Purpose: enforce infra coding contracts without running Pulumi

**Span / Observability Tests:**
- Scope: OTel span emission; use `InMemorySpanExporter` + `TracerProvider` injection
- Examples: `tests/test_pipeline_orchestrator.py:240-383`, `tests/temporal/test_spans.py`, `tests/extraction/test_extraction_service_spans.py`
- Pattern: swap module-level `tracer` with a test tracer, run subject, assert span names and attributes

**E2E Tests:** Not implemented. No browser automation, no live service calls.

## Mocking

**Framework:** `unittest.mock` — `AsyncMock`, `MagicMock`, `patch`

**Patterns:**

```python
# Standard service mock via AsyncMock constructor injection
mock_extraction_service = AsyncMock()
mock_extraction_service.process = AsyncMock(return_value=extraction_result)
service = ExtractionService(openai_client=mock_client, settings=MockSettings())

# Context manager mock (async session)
mock_session = AsyncMock()
mock_session.__aenter__ = AsyncMock(return_value=mock_session)
mock_session.__aexit__ = AsyncMock(return_value=None)

# patch() for module-level state mutation (Temporal activity singletons)
original = acts._orchestrator
acts._orchestrator = mock_orchestrator
try:
    result = await process_message_activity(inp)
finally:
    acts._orchestrator = original  # always restored

# patch() as context manager for patching module-level dependencies
with patch("src.temporal.activities.get_sessionmaker", return_value=mock_sessionmaker):
    result = await process_message_activity(inp)
```

**Temporal singleton pattern:** `src/temporal/activities.py` uses module-level `_orchestrator` and `_openai_client` singletons. Tests mutate these directly with try/finally restore rather than using `patch()` — fragile but consistent. See `tests/temporal/test_activities.py:60-75`.

**What is mocked:**
- OpenAI client (`beta.chat.completions.parse`)
- Pinecone write function (`write_job_embedding`)
- DB session/sessionmaker for activity-level tests
- Temporal client (`app.state.temporal_client` — auto-mocked via `_auto_mock_temporal_client` fixture in `tests/conftest.py:97`)
- Twilio `RequestValidator.validate` (via `mock_twilio_validator` fixture)
- `asyncio.to_thread` for Twilio send calls in pipeline handlers

**What is NOT mocked:**
- SQLAlchemy / SQLModel operations in DB-backed tests — real SQLite via `async_session`
- FastAPI routing and middleware — real ASGI stack via `AsyncClient`
- OTel span creation — real `InMemorySpanExporter` used

## Fixtures and Factories

**Root `tests/conftest.py` provides:**

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `_test_env` | session, autouse | Sets all required env vars; clears `get_settings` / `get_engine` caches |
| `_prometheus_registry_isolation` | session, autouse | Sentinel — prevents duplicate metric registration across session |
| `app` | session | `create_app()` singleton |
| `test_engine` | session | In-memory SQLite async engine; creates/drops all tables |
| `async_session` | function | Transaction-scoped async session; rolls back after each test |
| `client` | function | `httpx.AsyncClient` with `get_session` dependency override |
| `_auto_mock_temporal_client` | function, autouse | Injects `AsyncMock` Temporal client into `app.state.temporal_client` |
| `mock_twilio_validator` | function | Patches `RequestValidator.validate` to return `True` |
| `make_user` | function | Factory: creates `User` with auto-generated `phone_hash` |
| `make_message` | function | Factory: creates `Message` linked to a user |
| `make_job` | function | Factory: creates `Job` with sensible defaults; accepts overrides |
| `make_work_goal` | function | Factory: creates `WorkGoal` linked to a user/message |

**Factory fixture pattern:**
```python
@pytest_asyncio.fixture
async def make_job(async_session, make_user, make_message):
    async def _factory(**kwargs) -> Job:
        user = kwargs.pop("user", None) or await make_user()
        message = kwargs.pop("message", None) or await make_message(user=user)
        job = Job(
            message_id=kwargs.get("message_id", message.id),
            description=kwargs.get("description", "Test job description"),
            pay_rate=dollars_to_cents(kwargs.get("pay_rate", 25.0)) if kwargs.get("pay_rate", 25.0) is not None else None,
            ...
        )
        async_session.add(job)
        await async_session.flush()
        return job
    return _factory
```

**Domain conftest:** `tests/extraction/conftest.py` provides `make_mock_openai_client()` and `mock_pinecone_client()` as plain functions (not fixtures), imported directly into test modules.

## Mocking Quality Notes

**Strengths:**
- `_auto_mock_temporal_client` (autouse, function scope) prevents Temporal startup from leaking into all tests
- `mock_twilio_validator` fixture is explicit — tests that need it opt in; avoids invisible patches
- Factory fixtures use `async_session.flush()` (not `commit()`) to stay within the test transaction that rolls back after each test

**Weaknesses / Smells:**
- `tests/temporal/test_activities.py` uses direct attribute mutation (`acts._orchestrator = mock`) + try/finally instead of `patch()`. This pattern is not thread-safe and can corrupt state if a test errors before the finally. Should use `patch.object(acts, "_orchestrator", mock_orchestrator)`.
- `tests/extraction/test_service.py` defines `MockSettings`, `MockExtractionSettings`, `MockObservabilitySettings` as hand-rolled stub classes instead of using `MagicMock(spec=Settings)`. These drift when `Settings` evolves.
- `tests/integration/test_worker_goal.py:17-22` contains a `@pytest.mark.skip` test with reason "needs rewrite for Temporal worker" — stale placeholder, not failing CI but not testing anything.

## Coverage

**Requirements:** None enforced. No coverage thresholds configured. `pytest-cov` is present as a dev dep but is not invoked in CI.

**Known gaps:**
- `src/temporal/worker.py` — `start_cron_if_needed()` RPCError branch minimally tested
- `src/database.py` — engine creation path not independently tested
- `src/matches/formatter.py` — `_format_job_line()` (private) tested only indirectly through `format_match_sms()`
- No test exercises the `readyz` endpoint DB-error path (503 branch in `src/main.py:211-217`)
- No test covers `_update_gauges()` failure escalation beyond the `test_gauge_updater_no_silent_pass` source-inspection test

**View Coverage (manual):**
```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## CI Test Pipeline

Defined in `.github/workflows/ci.yml`. Triggers on push/PR to `main`.

```
Steps:
1. actions/checkout@v4
2. astral-sh/setup-uv@v5  (with cache)
3. uv sync --frozen
4. uv run ruff check src/ tests/ infra/
5. uv run ruff format --check src/ tests/ infra/
6. uv run pytest tests/ -x --tb=short -q
```

**Test environment in CI:**
- `DATABASE_URL: sqlite+aiosqlite:///./test.db` (overridden to in-memory by `conftest.py` `_test_env` fixture)
- All external API keys are stub strings (`test_key`, `test_sid`, etc.)
- No Postgres, no Temporal server, no Pinecone, no Twilio in CI — all mocked

**CI gaps:**
- No coverage gate — `pytest-cov` not invoked
- No type-check step — mypy/pyright absent
- `INNGEST_DEV` and `INNGEST_BASE_URL` env vars set in CI (`ci.yml:34-35`) are dead config from a removed dependency (Inngest replaced by Temporal in Phase 02.9)
- No separate integration or e2e job

---

*Testing analysis: 2026-04-22*
