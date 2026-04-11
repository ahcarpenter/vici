# Coding Conventions

**Analysis Date:** 2026-04-06

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python modules
- Domain modules follow a canonical set: `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `constants.py`, `exceptions.py`, `dependencies.py`, `utils.py`
- Test files: `test_{module_or_feature}.py` in a mirrored `tests/{domain}/` directory

**Functions:**
- Use `snake_case` for all functions and methods
- Prefix private methods/functions with a single underscore: `_persist()`, `_call_with_retry()`, `_make_service()`
- Prefix private module-level constants with underscore: `_GAUGE_POLL_INTERVAL_SECONDS`, `_bt_logger`
- Factory fixtures use `make_{entity}` pattern: `make_user`, `make_job`, `make_work_goal`, `make_message`

**Variables:**
- Use `snake_case` for all variables
- Use ALL_CAPS for module-level constants: `CENTS_PER_DOLLAR`, `GPT_MODEL`, `EMPTY_TWIML`
- OTel attribute keys: `OTEL_ATTR_` prefix, e.g. `OTEL_ATTR_MESSAGE_ID` in `src/pipeline/constants.py`

**Types/Classes:**
- Use `PascalCase` for classes: `ExtractionService`, `JobPostingHandler`, `PipelineContext`
- Pydantic models: `PascalCase`, descriptive nouns: `ExtractionResult`, `JobCreate`, `SmsSettings`
- SQLModel tables: singular `PascalCase`: `Job`, `User`, `Message`, `WorkGoal`, `Match`
- Abstract base classes: `MessageHandler`, `BaseRepository`

**Database Tables:**
- Singular `snake_case`: `job`, `user`, `message`, `work_goal`, `match`, `audit_log`
- DateTime columns suffixed `_at`: `created_at`
- Composite tables with prefix: `pinecone_sync_queue`

## Code Style

**Formatting:**
- ruff format (configured in `pyproject.toml`)
- Target version: Python 3.12

**Linting:**
- ruff check with rules: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort)
- Per-file exception: `src/extraction/prompts.py` ignores `E501` for long LLM prompt strings
- Config location: `pyproject.toml` under `[tool.ruff]` and `[tool.ruff.lint]`

**Run commands:**
```bash
ruff check --fix src
ruff format src
```

## Import Organization

**Order:**
1. Standard library (`asyncio`, `json`, `hashlib`, `datetime`, `typing`, `dataclasses`)
2. Third-party (`fastapi`, `sqlmodel`, `structlog`, `opentelemetry`, `pydantic`, `temporalio`)
3. Local imports (`src.*`)

**Import style:**
- Use explicit module aliasing for cross-domain imports:
  ```python
  from src.sms import service as sms_service
  import src.temporal.activities as acts
  ```
- Use `from` imports for specific symbols within same domain or from `src.*`:
  ```python
  from src.extraction.schemas import ExtractionResult
  from src.pipeline.handlers.base import MessageHandler
  ```
- `TYPE_CHECKING` guard for circular imports:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from src.pipeline.orchestrator import PipelineOrchestrator
  ```

**Path Aliases:**
- No path aliases. All imports are absolute from `src.*`.

## Error Handling

**Domain exceptions** live in `src/{domain}/exceptions.py`:
- `src/sms/exceptions.py`: `TwilioSignatureInvalid`, `EarlyReturn`, `DuplicateMessageSid`, `RateLimitExceeded`
- `src/exceptions.py`: Global exception handlers (e.g., `twilio_signature_invalid_handler`)

**Patterns:**
- Twilio webhook path: NEVER raise `HTTPException` for 4xx -- Twilio retries on 4xx. Use custom `EarlyReturn` subclasses that return HTTP 200 with empty TwiML
- FastAPI exception handlers registered in `create_app()` in `src/main.py`
- Temporal activities: use `ApplicationError(message, non_retryable=True/False)` for Temporal-aware error semantics
- External API failures (Pinecone, OpenAI): catch, log with structlog, and degrade gracefully (e.g., enqueue for retry)
- Input validation: use Pydantic `Field` constraints (`min_length`, `max_length`, `gt`, `ge`)
- Config validation: `model_validator` in `src/config.py` fails fast on missing required credentials at startup

**Error hierarchy example:**
```python
class EarlyReturn(Exception):
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(reason)

class DuplicateMessageSid(EarlyReturn): pass
class RateLimitExceeded(EarlyReturn): pass
```

## Logging

**Framework:** structlog (JSON-rendered, with OTel trace context injection)

**Configuration:** `src/main.py` `_configure_structlog()` -- processors chain:
1. `structlog.stdlib.add_log_level`
2. `_add_otel_context` (custom -- injects `trace_id`, `span_id`)
3. `structlog.processors.TimeStamper(fmt="iso")`
4. `structlog.processors.JSONRenderer()`

**Usage pattern:**
```python
import structlog
log = structlog.get_logger()

# Module-level logger assignment
log.info("gpt_classified", message_type=result.message_type, phone_hash=phone_hash)
log.warning("match.job_excluded", job_id=job.id, reason="null_pay_rate")
log.error("pinecone_write_failed", job_id=job.id, error=str(e))
```

**Rules:**
- Use structured key-value pairs, never string interpolation in log messages
- Event names use `snake_case` with dot-separated domain prefix: `"gpt_classified"`, `"match.job_excluded"`, `"pinecone_write_failed"`
- Always include contextual identifiers: `job_id`, `phone_hash`, `message_sid`
- Never log raw phone numbers or PII -- use `phone_hash` instead

## Observability

**Distributed tracing:** OpenTelemetry with OTLP gRPC exporter to Jaeger
- `TracerProvider` configured in `src/main.py` `_configure_otel()`
- Module-level tracer: `tracer = otel_trace.get_tracer(__name__)`
- Manual span creation with `with tracer.start_as_current_span("span.name") as span:`
- Auto-instrumentation for FastAPI and SQLAlchemy
- Semantic conventions for attributes defined in `src/pipeline/constants.py`

**Metrics:** Prometheus via `prometheus_client` + `prometheus-fastapi-instrumentator`
- Metric singletons defined in `src/metrics.py` (import once at module level)
- Custom metrics: `gpt_calls_total`, `gpt_call_duration_seconds`, `gpt_input_tokens_total`, `gpt_output_tokens_total`, `pinecone_sync_queue_depth`, `pipeline_failures_total`
- Auto HTTP metrics via `Instrumentator().instrument(app).expose(app)` at `/metrics`
- Gauge updater: background task polls DB every 15s for `pinecone_sync_queue` depth

**LLM observability:** Braintrust via `braintrust.wrap_openai()` wrapper on OpenAI client

## Function Design

**Size:** Keep functions focused on single responsibility. Service methods typically 10-30 lines.

**Parameters:**
- Constructor injection for dependencies (repositories, services, clients)
- `AsyncSession` passed as first arg to repository methods
- Use `@dataclass` for structured input bags: `PipelineContext`, `ProcessMessageInput`

**Return Values:**
- Repository methods return domain model instances
- Service methods return Pydantic schema instances (`ExtractionResult`, `MatchResult`)
- Activities return `str` ("ok") for Temporal compatibility

## Module Design

**Exports:**
- No `__all__` declarations. Import specific symbols.
- `src/models.py` is a barrel file that imports all SQLModel tables to ensure registration

**Design Patterns:**
- **Repository pattern**: `BaseRepository` with `_persist()` template method in `src/repository.py`. Domain repos extend it.
- **Chain of Responsibility**: `MessageHandler` ABC in `src/pipeline/handlers/base.py` with `can_handle()` + `handle()`. Orchestrator iterates handlers.
- **Dependency Injection**: Constructor injection throughout. DI graph wired in `lifespan()` in `src/main.py`.
- **FastAPI dependency chain**: Validation gates chained via `Depends()` in `src/sms/dependencies.py` (signature -> idempotency -> user upsert -> rate limit).
- **Factory pattern**: Test fixtures use factory functions (`make_user`, `make_job`, etc.)

## Money Handling

- All monetary values stored as **integer cents** in the database
- Conversion utilities in `src/money.py`: `dollars_to_cents()` and `cents_to_dollars()`
- `dollars_to_cents` called at persistence boundary (LLM extraction -> DB)
- `cents_to_dollars` called at display boundary (DB -> SMS reply)

## Transaction Discipline

- Repositories use `_persist()` (flush only) -- caller owns the transaction
- Route handlers and pipeline handlers call `session.commit()` explicitly
- Pinecone writes happen AFTER commit (fire-and-forget with fallback queue)
- Separate sessions for fallback writes to avoid polluting the main transaction

---

*Convention analysis: 2026-04-06*
