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
| `aiosqlite >=0.22.1` | In-memory SQLite backend for tests |
| `httpx >=0.28.1` | Async HTTP test client (`AsyncClient`) |

The test suite uses an **in-memory SQLite** database (`sqlite+aiosqlite:///:memory:`) instead of PostgreSQL, configured in `tests/conftest.py`. SQLModel metadata is created fresh per session and dropped after.

Before running tests, install dev dependencies:

```bash
uv sync
```

## Running tests

Run the full test suite:

```bash
uv run pytest tests/ -x --tb=short -q
```

Run a specific test directory:

```bash
uv run pytest tests/extraction/ -v
```

Run a single test file:

```bash
uv run pytest tests/test_health.py -v
```

Run a single test by name:

```bash
uv run pytest tests/ -k "test_match_service" -v
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
├── conftest.py                    # Global fixtures (client, session, factories)
├── extraction/
│   ├── conftest.py                # Extraction-specific fixtures
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

- **`client`** -- An async `httpx.AsyncClient` wired to the FastAPI app with session overrides. Use for endpoint testing.
- **`async_session`** -- An async SQLAlchemy session backed by in-memory SQLite. Rolls back after each test.
- **`app`** -- The FastAPI application instance (session-scoped).
- **`make_user`** / **`make_message`** / **`make_job`** / **`make_work_goal`** -- Factory fixtures for creating domain entities with sensible defaults.
- **`mock_twilio_validator`** -- Patches Twilio request validation to always return `True`.
- **`_auto_mock_temporal_client`** -- Auto-used fixture that mocks `app.state.temporal_client` for all tests.

### Async tests

Because `asyncio_mode = "auto"` is set in `pyproject.toml`, all `async def` test functions are automatically recognized as async tests. No `@pytest.mark.asyncio` decorator is needed:

```python
async def test_something(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
```

### Environment variables

The `_test_env` session fixture in `conftest.py` sets default environment variables for the test session (DATABASE_URL, TWILIO credentials, OPENAI_API_KEY, etc.). These can be overridden per-test with `monkeypatch` or `unittest.mock.patch`.

## Coverage requirements

No minimum coverage threshold is configured in the project. Coverage can be generated on demand with `--cov` flags as shown above.

## CI integration

Tests run in the **CI** workflow (`.github/workflows/ci.yml`) on every push to `main` and on pull requests targeting `main`.

The workflow runs a single `test` job on `ubuntu-latest`:

1. **Checkout** -- `actions/checkout@v4`
2. **Setup uv** -- `astral-sh/setup-uv@v5` with caching enabled
3. **Install dependencies** -- `uv sync --frozen`
4. **Lint** -- `uv run ruff check src/ tests/` (currently `continue-on-error: true`)
5. **Test** -- `uv run pytest tests/ -x --tb=short -q`

CI uses a file-based SQLite database (`sqlite+aiosqlite:///./test.db`) and sets stub values for all required environment variables (Twilio, OpenAI, Pinecone, Braintrust, etc.) so no external services are contacted during test runs.
