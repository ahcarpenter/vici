<!-- generated-by: gsd-doc-writer -->
# Testing

Guide for running and writing tests in the Vici project.

## Test framework and setup

Vici uses **pytest** with **pytest-asyncio** for async test support and **pytest-cov** for coverage reporting. Key dev dependencies (from `pyproject.toml` `[dependency-groups] dev`):

| Package | Purpose |
|---------|---------|
| `pytest >=9.0.2` | Test runner |
| `pytest-asyncio >=1.3.0` | Async test support (`asyncio_mode = "auto"`) |
| `pytest-cov >=7.0.0` | Coverage reporting |
| `aiosqlite >=0.22.1` | Async SQLite driver used by the test database |
| `httpx >=0.28.1` | Async HTTP test client (`AsyncClient` + `ASGITransport`) |

Pytest configuration lives in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

The local test suite uses an **in-memory SQLite** database (`sqlite+aiosqlite:///:memory:`) instead of PostgreSQL, configured in `tests/conftest.py` via the `DATABASE_URL_TEST` constant. A single session-scoped async engine is created, `SQLModel.metadata.create_all` runs once at the start of the session, and the tables are dropped and the engine disposed at teardown. Each test gets its own `async_session` that rolls back after the test completes.

Before running tests, install dev dependencies:

```bash
uv sync
```

## Running tests

Run the full test suite (matches the CI command):

```bash
uv run pytest tests/ -x --tb=short -q
```

### Running a subset of tests

Run a specific test directory (e.g., only the extraction domain):

```bash
uv run pytest tests/extraction/ -v
```

Run a single test file:

```bash
uv run pytest tests/test_health.py -v
```

Run a single test function by name using a keyword expression:

```bash
uv run pytest tests/ -k "test_match_service" -v
```

Run every test whose name contains a substring across the whole suite:

```bash
uv run pytest tests/ -k "webhook or health"
```

Stop on the first failure and show short tracebacks:

```bash
uv run pytest tests/ -x --tb=short
```

Run with coverage:

```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## Writing new tests

### File naming and location

Tests are organized by domain, mirroring the `src/` structure:

```
tests/
├── conftest.py                      # Global fixtures (client, async_session, factories)
├── extraction/
│   ├── conftest.py                  # Extraction-specific fixtures
│   ├── test_service.py
│   ├── test_schemas.py
│   ├── test_metrics.py
│   ├── test_persistence.py
│   └── test_extraction_service_spans.py
├── infra/
│   └── test_observability_static.py
├── integration/
│   ├── test_job_posting.py
│   ├── test_worker_goal.py
│   └── test_unknown.py
├── matches/
│   └── test_match_service.py
├── sms/
│   └── test_webhook.py
├── temporal/
│   ├── test_worker.py
│   ├── test_activities.py
│   └── test_spans.py
├── test_3nf_normalization.py
├── test_config.py
├── test_health.py
├── test_logging.py
├── test_otel_config.py
├── test_pipeline_hardening.py
├── test_pipeline_orchestrator.py
└── test_repositories.py
```

New test files should follow the `test_*.py` naming convention. Place domain-specific tests in a subdirectory matching the `src/` domain (e.g., tests for `src/extraction/` go in `tests/extraction/`). Cross-cutting or root-level tests go directly in `tests/`.

### Key fixtures

The root `tests/conftest.py` provides several shared fixtures:

- **`app`** — Session-scoped FastAPI application instance built via `create_app()`.
- **`test_engine`** — Session-scoped async SQLAlchemy engine bound to in-memory SQLite. Creates/drops SQLModel metadata for the session.
- **`async_session`** — Per-test async SQLAlchemy session backed by `test_engine`. Rolls back after each test.
- **`client`** — Per-test `httpx.AsyncClient` wired to the FastAPI app via `ASGITransport`, with `get_session` overridden to use `async_session`. Use this for endpoint tests.
- **`make_user`** / **`make_message`** / **`make_job`** / **`make_work_goal`** — Async factory fixtures for creating domain entities with sensible defaults. Each accepts keyword overrides and flushes to `async_session`.
- **`mock_twilio_validator`** — Patches `twilio.request_validator.RequestValidator.validate` to return `True`.
- **`_auto_mock_temporal_client`** — Auto-used fixture that replaces `app.state.temporal_client` with an `AsyncMock` whose `start_workflow` returns `"wf-run-id"`.
- **`_test_env`** — Session-scoped autouse fixture that sets default environment variables (`DATABASE_URL`, `TWILIO_*`, `WEBHOOK_BASE_URL`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `TEMPORAL_ADDRESS`, `ENV`) and clears `get_settings` / `get_engine` caches.
- **`_prometheus_registry_isolation`** — Session-scoped autouse sentinel that prevents duplicate Prometheus metric registration errors across the test session.

### Async test client pattern

Because `asyncio_mode = "auto"` is set in `pyproject.toml`, all `async def` test functions are automatically recognized as async tests — no `@pytest.mark.asyncio` decorator is needed.

The `client` fixture yields an `httpx.AsyncClient` backed by `ASGITransport(app=app)`, so requests are dispatched in-process without spinning up a real HTTP server. Use `await client.<method>(...)` to exercise endpoints:

```python
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_create_entity(client, make_user):
    user = await make_user()
    resp = await client.post("/messages", json={"user_id": str(user.id), "body": "hi"})
    assert resp.status_code == 201
```

Under the hood, the `client` fixture overrides the `get_session` FastAPI dependency so that any route handler that calls `Depends(get_session)` receives the same rollback-scoped `async_session` the test is using. This means assertions made against `async_session` see the same data the handlers wrote.

### Environment variables

The `_test_env` session fixture in `conftest.py` sets default environment variables for the test session. These can be overridden per-test with `monkeypatch` or `unittest.mock.patch`. If a test needs a fresh `Settings` instance after mutating env, call `get_settings.cache_clear()`.

## Coverage requirements

No minimum coverage threshold is configured in the project (no `[tool.coverage.*]` section in `pyproject.toml` and no `--cov-fail-under` in CI). Coverage can be generated on demand with `--cov` flags:

```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
uv run pytest tests/ --cov=src --cov-report=html  # writes htmlcov/
```

## CI integration

Tests run in the **CI** workflow (`.github/workflows/ci.yml`) on every push to `main` and on pull requests targeting `main`.

The workflow runs a single `test` job on `ubuntu-latest`:

1. **Checkout** — `actions/checkout@v4`
2. **Setup uv** — `astral-sh/setup-uv@v5` with caching enabled
3. **Install dependencies** — `uv sync --frozen`
4. **Lint** — `uv run ruff check src/ tests/`
5. **Test** — `uv run pytest tests/ -x --tb=short -q`

CI uses a file-based SQLite database (`DATABASE_URL=sqlite+aiosqlite:///./test.db`) and sets stub values for all required environment variables (`TWILIO_*`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`, `BRAINTRUST_API_KEY`, `WEBHOOK_BASE_URL`, plus `INNGEST_DEV` / `INNGEST_BASE_URL`) so no external services are contacted during test runs.
