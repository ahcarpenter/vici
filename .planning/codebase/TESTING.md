# Testing Patterns

**Analysis Date:** 2026-04-06

## Test Framework

**Runner:**
- pytest >= 9.0.2
- pytest-asyncio >= 1.3.0 (with `asyncio_mode = "auto"`)
- pytest-cov >= 7.0.0
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`

**Assertion Library:**
- Built-in `assert` statements (pytest-native)

**Run Commands:**
```bash
uv run pytest                    # Run all tests
uv run pytest tests/sms/         # Run domain-specific tests
uv run pytest -x                 # Stop on first failure
uv run pytest --cov=src          # Coverage report
uv run pytest -k "test_health"   # Run specific test by name
```

## Test File Organization

**Location:** Separate `tests/` directory mirroring `src/` domain structure

**Naming:** `test_{feature_or_module}.py`

**Structure:**
```
tests/
├── __init__.py
├── conftest.py                          # Global fixtures: app, client, DB, factories
├── extraction/
│   ├── __init__.py
│   ├── conftest.py                      # Domain fixtures: mock OpenAI client factory
│   ├── test_extraction_service_spans.py # OTel span tests
│   ├── test_metrics.py
│   ├── test_persistence.py
│   ├── test_schemas.py
│   └── test_service.py                  # Unit tests for ExtractionService
├── infra/
│   ├── __init__.py
│   └── test_observability_static.py
├── integration/
│   ├── __init__.py
│   ├── test_job_posting.py              # Handler-level integration tests
│   ├── test_unknown.py
│   └── test_worker_goal.py
├── matches/
│   ├── __init__.py
│   └── test_match_service.py            # DP algorithm + formatter + persistence
├── sms/
│   ├── __init__.py
│   └── test_webhook.py                  # HTTP-level webhook tests
├── temporal/
│   ├── __init__.py
│   ├── test_activities.py               # Temporal activity unit tests
│   ├── test_spans.py
│   └── test_worker.py
├── test_3nf_normalization.py            # Schema constraint tests
├── test_config.py                       # Settings validation tests
├── test_health.py                       # Health/metrics endpoint tests
├── test_logging.py                      # structlog + OTel context tests
├── test_otel_config.py
├── test_pipeline_hardening.py           # Production hardening verification
├── test_pipeline_orchestrator.py        # Orchestrator + span tests
└── test_repositories.py                 # Repository CRUD + idempotency tests
```

## Test Structure

**Async mode:** `asyncio_mode = "auto"` -- no need for `@pytest.mark.asyncio` on tests that use async fixtures (but many tests still include it explicitly; both work).

**Suite Organization:**
```python
# Flat function tests (most common pattern)
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200

# Class-based grouping (used for related schema tests)
class TestUserIdRemoved:
    def test_job_construction_without_user_id(self):
        job = Job(message_id=1, description="test", pay_rate=10.0)
        assert "user_id" not in Job.model_fields
```

**Naming convention:** `test_{what_is_being_tested}` -- descriptive, reads as a behavior spec. Every test has a docstring explaining the assertion.

## Database Testing

**Strategy:** In-memory SQLite via aiosqlite (no real Postgres in tests)

**Engine setup:**
```python
DATABASE_URL_TEST = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(DATABASE_URL_TEST, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()
```

**Session fixture:** Per-test with automatic rollback
```python
@pytest_asyncio.fixture
async def async_session(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
```

**App client:** Overrides `get_session` dependency to use test DB
```python
@pytest_asyncio.fixture
async def client(async_session, app):
    async def override_get_session():
        yield async_session
    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

## Fixtures and Factories

**Global fixtures** in `tests/conftest.py`:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `_test_env` | session | Sets required env vars with `os.environ.setdefault` |
| `_prometheus_registry_isolation` | session | Prevents duplicate metric registration |
| `app` | session | `create_app()` singleton |
| `test_engine` | session | In-memory SQLite engine |
| `async_session` | function | Per-test DB session with rollback |
| `client` | function | httpx `AsyncClient` with DI overrides |
| `_auto_mock_temporal_client` | function (autouse) | Mocks `app.state.temporal_client` |
| `mock_twilio_validator` | function | Patches Twilio signature validation to always pass |
| `make_user` | function | Factory: creates `User` with auto-generated `phone_hash` |
| `make_message` | function | Factory: creates `Message` linked to a user |
| `make_job` | function | Factory: creates `Job` linked to user+message |
| `make_work_goal` | function | Factory: creates `WorkGoal` linked to user+message |

**Factory pattern:**
```python
@pytest_asyncio.fixture
async def make_user(async_session):
    _counter = {"n": 0}
    async def _factory(phone_hash: str | None = None, phone_e164: str | None = None) -> User:
        if phone_hash is None:
            _counter["n"] += 1
            phone_hash = hashlib.sha256(f"phone_{_counter['n']}".encode()).hexdigest()
        user = User(phone_hash=phone_hash, phone_e164=phone_e164)
        async_session.add(user)
        await async_session.flush()
        return user
    return _factory
```

**Domain fixtures** in `tests/extraction/conftest.py`:
```python
def make_mock_openai_client(parsed_result: ExtractionResult):
    """Returns a fully-mocked AsyncOpenAI client that returns the given parsed_result."""
    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)
    mock_client.embeddings.create = AsyncMock(...)
    return mock_client
```

## Mocking

**Framework:** `unittest.mock` (AsyncMock, MagicMock, patch)

**Common mock targets:**
- OpenAI client: `mock_client.beta.chat.completions.parse`
- Twilio validator: `twilio.request_validator.RequestValidator.validate`
- Temporal client: `app.state.temporal_client` (autouse fixture)
- structlog: `patch("structlog.get_logger", return_value=CapturingLogger())`
- Database sessionmaker: `patch("src.temporal.activities.get_sessionmaker", ...)`
- Module-level tracers: `svc_module.tracer = test_tracer` (direct assignment)

**Patterns:**

Mocking external services:
```python
mock_client = AsyncMock()
mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)
service = ExtractionService(openai_client=mock_client, settings=MockSettings())
```

Capturing log output:
```python
class CapturingLogger:
    def __init__(self):
        self.logged_warnings = []
    def warning(self, event, **kw):
        self.logged_warnings.append((event, kw))
    def info(self, *a, **kw): pass
    def error(self, *a, **kw): pass

with patch("structlog.get_logger", return_value=CapturingLogger()):
    await function_under_test()
```

Also uses `structlog.testing.capture_logs()` context manager (see `tests/matches/test_match_service.py`):
```python
with structlog.testing.capture_logs() as cap:
    candidates = await repo.find_candidates_for_goal(session)
assert any(e.get("reason") == "null_pay_rate" for e in cap)
```

**What to mock:**
- External API clients (OpenAI, Twilio, Pinecone)
- Temporal client (`start_workflow`)
- Database sessionmaker when testing activities outside HTTP context
- Module-level tracers for span assertion tests

**What NOT to mock:**
- SQLModel/SQLAlchemy operations against in-memory SQLite (use real DB fixtures)
- Pydantic validation (test real schema constraints)
- Business logic (DP algorithm in `MatchService`)

## OTel Span Testing

**Pattern:** Use `InMemorySpanExporter` to capture spans without a real backend
```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
test_tracer = provider.get_tracer("test")

# Monkey-patch module-level tracer
import src.extraction.service as svc_module
svc_module.tracer = test_tracer

# After test execution:
spans = exporter.get_finished_spans()
span_names = [s.name for s in spans]
assert "gpt.classify_and_extract" in span_names
```

**Span test files:**
- `tests/extraction/test_extraction_service_spans.py`
- `tests/temporal/test_spans.py`
- `tests/test_pipeline_orchestrator.py` (span test section)

## Coverage

**Requirements:** No enforced minimum. pytest-cov is available.

**View Coverage:**
```bash
uv run pytest --cov=src --cov-report=term-missing
```

## Test Types

**Unit Tests:**
- Test individual services, repositories, schemas in isolation
- Mock all external dependencies
- Files: `tests/extraction/test_service.py`, `tests/test_config.py`, `tests/extraction/test_schemas.py`

**Integration Tests (handler-level):**
- Test pipeline handlers with mocked repos but real handler logic
- Verify transaction discipline (commit counts, repo call assertions)
- Files: `tests/integration/test_job_posting.py`, `tests/test_pipeline_orchestrator.py`

**HTTP Integration Tests:**
- Test full request/response cycle via httpx AsyncClient
- Real SQLite DB, mocked external services
- Files: `tests/sms/test_webhook.py`, `tests/test_health.py`

**Schema/Constraint Tests:**
- Verify model field presence/absence, Pydantic validation
- Files: `tests/test_3nf_normalization.py`, `tests/extraction/test_schemas.py`

**Observability Tests:**
- Verify OTel spans are emitted with correct attributes
- Verify structlog trace context injection
- Verify Prometheus metric registration and increments
- Files: `tests/test_logging.py`, `tests/test_otel_config.py`, `tests/infra/test_observability_static.py`

**Static source analysis tests:**
- Read source files and assert patterns (e.g., no bare `except: pass`)
- Files: `tests/test_pipeline_orchestrator.py` (`test_gauge_updater_no_silent_pass`)
- Files: `tests/integration/test_job_posting.py` (`test_rate_limit_rolling_window`)

**E2E Tests:**
- Not present. No end-to-end tests with real Temporal, Postgres, or external APIs.

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_classify_job():
    service = _make_service(mock_client)
    result = await service.process("Need a mover", "hash123")
    assert result.message_type == "job_posting"
```

**Error Testing:**
```python
@pytest.mark.asyncio
async def test_gpt_none_parsed_raises():
    from temporalio.exceptions import ApplicationError
    with pytest.raises(ApplicationError):
        await service.process("Hello", "hash123")
```

**Config Testing (with cache management):**
```python
def test_config(monkeypatch):
    from src.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    settings = get_settings()
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    get_settings.cache_clear()  # Always clear after
```

**Idempotency Testing:**
```python
async def test_idempotency(client, mock_twilio_validator, async_session):
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)  # same SID
    assert response.status_code == 200
    result = await async_session.execute(select(Message).where(...))
    assert len(result.all()) == 1  # only one row
```

---

*Testing analysis: 2026-04-06*
