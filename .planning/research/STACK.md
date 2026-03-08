# Stack Research

**Domain:** SMS-based job matching API (Python/FastAPI + Twilio + OpenAI + PostgreSQL + Pinecone + Inngest)
**Researched:** 2026-03-08
**Confidence:** HIGH — derived from the actual built system (Phases 01–02.5 complete). Source: STATE.md, PROJECT.md, REQUIREMENTS.md.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | Runtime | 3.12 offers the best balance of performance improvements (faster CPython) and ecosystem support; 3.13 is too new for stable library support across the board as of mid-2025. Confidence: HIGH |
| FastAPI | ^0.111 | HTTP framework + webhook handler | Native async, automatic OpenAPI docs, Pydantic v2 integration, and the de-facto standard for Python ML/AI APIs. The single Twilio webhook endpoint is trivially modeled as a `POST /sms` route. Confidence: MEDIUM (verify latest pin) |
| Pydantic | v2 (ships with FastAPI) | Request/response validation and structured extraction models | v2 is 5-50x faster than v1 for validation; `model_json_schema()` feeds directly into OpenAI structured outputs. Do not pin separately — FastAPI manages the compatible range. Confidence: HIGH |
| SQLAlchemy | ^2.0 | ORM + async query layer | SQLAlchemy 2.0 unified the sync/async API under a single `AsyncSession`; the `mapped_column` + `DeclarativeBase` pattern gives typed models without the boilerplate of 1.x. Required for Alembic integration. Confidence: HIGH |
| asyncpg | ^0.29 | Async PostgreSQL driver | Fastest async Postgres driver for Python; used as the backend for SQLAlchemy `AsyncEngine` via `create_async_engine("postgresql+asyncpg://...")`. Do not use psycopg2 in an async app. Confidence: HIGH |
| PostgreSQL | 16 | Primary datastore | postgres:16 plain image — no vector column — Pinecone is the external vector store. Confidence: HIGH |
| Alembic | ^1.13 | Database schema migrations | First-class SQLAlchemy integration; supports async engines via `run_sync` pattern; the only production-viable migration tool for SQLAlchemy projects. Confidence: HIGH |
| openai | ^1.30 | OpenAI GPT API client | The v1.x SDK (released Nov 2023) is the modern interface: `client.beta.chat.completions.parse()` with Pydantic model `response_format` enables structured outputs. gpt-5.3-chat-latest is specified by the product owner; use the model string `"gpt-5.3-chat-latest"` in requests. Confidence: MEDIUM (verify latest 1.x pin; gpt-5.3-chat-latest model string needs validation against OpenAI's naming) |
| twilio | ^9.0 | Twilio SMS SDK | Handles signature validation (`RequestValidator`) and outbound `client.messages.create()`. Outbound SMS via `asyncio.to_thread()` wrapper (SDK is sync); webhook returns HTTP 200 after Inngest event emit — no TwiML response. Confidence: HIGH |
| Inngest | Cloud-hosted (local: Dev Server) | Async event queue | `process-message` function (3 retries, on_failure handler) + `sync-pinecone-queue` cron sweep (*/5 * * * *) | Confidence: HIGH |
| Braintrust | current | LLM observability | Wraps `AsyncOpenAI` client via `braintrust.wrap_openai()` before injection into ExtractionService | Confidence: HIGH |
| Pinecone | current | Vector store | `text-embedding-3-small` (1536 dims); job embeddings written at creation time; failed writes queued in `pinecone_sync_queue` and retried by Inngest cron | Confidence: HIGH |
| uvicorn | ^0.30 | ASGI server | Production ASGI server for FastAPI; pair with `uvicorn[standard]` for `uvloop` (faster event loop) and `httptools` (faster HTTP parsing). Confidence: HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | ^1.0 | Environment variable loading | Local dev only; in production use the platform's native secrets injection. |
| pydantic-settings | ^2.0 | Settings management with env var binding | Ship a `Settings` class on app startup; avoids scattered `os.getenv()` calls and validates config types at startup. Always use this. |
| httpx | ^0.27 | Async HTTP client | Needed if adding outbound webhook calls or health checks; also the test client backend for FastAPI `TestClient`. Confidence: HIGH |
| pytest | ^8.0 | Test runner | Standard Python test framework. Confidence: HIGH |
| pytest-asyncio | ^0.23 | Async test support | Required for testing async FastAPI routes and SQLAlchemy async sessions. Pin `asyncio_mode = "auto"` in `pytest.ini`. Confidence: HIGH |
| factory-boy | ^3.3 | Test data factories | Cleaner than hand-crafting fixture dicts; pairs well with SQLAlchemy models. |
| tenacity | ^8.2 | Retry logic | Not used for Inngest retry (Inngest handles 3 retries natively). Kept as library but not active retry mechanism. |
| structlog | ^24.0 | Structured JSON logging | per-request context (phone hash, message_id, trace_id). ✅ Implemented (OBS-04) |
| opentelemetry-sdk + opentelemetry-exporter-otlp | current | OTel distributed tracing | ALWAYS_ON sampler, OTLP gRPC export to Jaeger v2 collector. ✅ Implemented (OBS-03) |
| prometheus-client | current | Prometheus metrics | Custom GPT counters, latency histograms, queue depth gauge. ✅ Implemented (OBS-02) |
| inngest | current | Inngest Python SDK | See Core Technologies above. ✅ Implemented (ASYNC-01, ASYNC-03) |
| braintrust | current | Braintrust Python SDK | See Core Technologies above. ✅ Implemented (OBS-01) |
| pinecone-client | current | Pinecone Python SDK | See Core Technologies above. ✅ Implemented (VEC-01) |
| pytest-cov | current | Test coverage reporting | Integrated with GitHub Actions CI. ✅ Implemented (PROD-05, PROD-08) |
| sentry-sdk | ^2.0 | Error tracking | NOT ADOPTED — not in use; remove from `uv add` commands |
| gunicorn | ^22.0 | Process manager | NOT ADOPTED — Render.com uses Docker runtime directly; not in use |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Dependency management and virtual environments | Dramatically faster than pip+venv; `uv sync` installs from `pyproject.toml` lockfile. Use `pyproject.toml` as the single source of truth for deps. Replaces pip, pip-tools, and virtualenv. |
| ruff | Linting + formatting | Replaces flake8 + black + isort in a single fast tool; configure in `pyproject.toml` under `[tool.ruff]`. |
| mypy | Static type checking | With SQLAlchemy 2.0's `MappedColumn` types and Pydantic v2 models, type coverage is high; configure `strict = false` initially and tighten over time. |
| Docker + docker-compose | Local dev environment | `docker-compose.yml` with `postgres:16` service (plain image — no vector extension); 8-service Docker Compose: postgres, opensearch, jaeger-collector, jaeger-query, app, inngest, prometheus, grafana |
| pre-commit | Git hook runner | Enforce ruff + mypy on commit; prevents type and lint regressions from landing. |

---

## Installation

```bash
# Requires uv (https://docs.astral.sh/uv/)

# Core runtime
uv add fastapi "uvicorn[standard]" sqlalchemy asyncpg alembic \
       openai twilio inngest braintrust \
       opentelemetry-sdk opentelemetry-exporter-otlp prometheus-client \
       pydantic-settings tenacity structlog

# Dev / test
uv add --dev pytest pytest-asyncio pytest-cov httpx factory-boy \
            ruff mypy pre-commit

# Local secrets loading (dev only)
uv add python-dotenv
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| SQLAlchemy 2.0 async | Tortoise ORM | If you want a Django-style async ORM with simpler migration story; not recommended here because Alembic is required by the layered architecture constraint. |
| SQLAlchemy 2.0 async | SQLModel | SQLModel (FastAPI author's lib) is thin SQLAlchemy + Pydantic wrapper; fine for simple apps but adds an abstraction layer that complicates async session scoping. Avoid for this complexity level. |
| asyncpg | psycopg3 (async) | psycopg3 has excellent async support and is more standard; either works. asyncpg has the larger existing body of community examples for SQLAlchemy + FastAPI. Stick with asyncpg unless you hit a specific compatibility issue. |
| Pinecone | External vector DB (e.g. self-hosted) | Pinecone is the external vector store in this project. Decision is final — postgres:16 plain image is in use. No vector extension needed. |
| structlog | Python stdlib logging | stdlib logging doesn't produce structured JSON by default; structlog requires ~5 lines of config and the observability benefit is immediate in a production webhook handler. |
| uv | poetry | poetry is viable; uv is 10-100x faster and has become the community standard as of 2025. Either works; uv is the better default for new projects. |
| Inngest | Celery + Redis | Inngest is already implemented; handles retries, cron, and event-driven async without Redis operational overhead. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| psycopg2 | Synchronous only; blocks the event loop in async FastAPI handlers, causing cascading latency under concurrent SMS traffic | asyncpg (via SQLAlchemy `postgresql+asyncpg://`) |
| Flask | No native async; every Twilio webhook handler blocks the process; poor OpenAPI support | FastAPI |
| Django ORM | Sync-only ORM (Django async support is partial); limited SQLAlchemy/Alembic compatibility | SQLAlchemy 2.0 async |
| SQLAlchemy 1.x | The legacy `Query` API is removed in 2.0; 1.x async patterns require significant boilerplate vs. 2.0's unified API | SQLAlchemy 2.0 |
| Pydantic v1 | FastAPI 0.100+ uses Pydantic v2 internally; mixing v1 models causes `ValidationError` import conflicts | Pydantic v2 (comes with FastAPI) |
| LangChain | Significant abstraction overhead for a single-model, single-prompt use case; hides token costs, complicates structured output schemas | Direct `openai` SDK with Pydantic schema |
| FastAPI BackgroundTasks | Not used for this async pattern — Inngest is the async queue | Inngest event-driven processing |
| Celery + Redis | Overkill for SMS webhook volume; adds operational complexity for a use case that Inngest handles with retries and cron | Inngest (already implemented) |
| requests | Synchronous HTTP client; blocks event loop | httpx (async) |

---

## Stack Patterns by Variant

**Deploying to Render.com (actual deployment target):** render.yaml Blueprint already exists (PROD-04 complete). Web service uses Docker runtime directly (no gunicorn). Pre-deploy migration hook: `alembic upgrade head`. GIT_SHA env var must be set manually or via deploy hooks. PostgreSQL 16 basic-256mb instance provisioned via Blueprint. First production deploy validation is Phase 4.

**If running locally:**
- `docker compose up` starts 8 services: postgres (postgres:16), opensearch, jaeger-collector, jaeger-query, app, inngest, prometheus, grafana
- `uv run uvicorn src.main:app --reload` for hot reload
- Use `ngrok http 8000` to expose local endpoint to Twilio webhook config

**If OpenAI rate limits become a bottleneck:**
- Inngest handles function-level retries (3 retries configured with exponential backoff)
- Consider batching multiple extractions into a single prompt (but v1 volume is low enough this won't be needed)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| fastapi ^0.111 | pydantic v2.x | FastAPI 0.100+ dropped pydantic v1 support; do not mix |
| sqlalchemy ^2.0 | asyncpg ^0.29 | SQLAlchemy 2.0 async engine requires asyncpg 0.24+; 0.29 is safe |
| alembic ^1.13 | sqlalchemy ^2.0 | Alembic 1.13 is the first release with full SQLAlchemy 2.0 support for async migration env config |
| pytest-asyncio ^0.23 | pytest ^8.0 | pytest-asyncio 0.21+ changed the default mode to `strict`; set `asyncio_mode = "auto"` in `pyproject.toml` or annotate every async test |
| openai ^1.30 | python 3.12 | openai v1.x requires Python 3.7.1+; no known conflicts on 3.12 |
| twilio ^9.0 | python 3.12 | twilio 9.x dropped Python 3.7 support; requires 3.8+; compatible with 3.12 |

---

## Critical Integration Patterns

### Twilio Webhook Handler

Twilio sends `application/x-www-form-urlencoded` POST, not JSON. FastAPI does not auto-parse form data as Pydantic models; use `Form(...)` params or a dedicated `Request` object.

```python
# Actual implemented pattern — no TwiML returned
@router.post("/webhook/sms")
async def handle_sms(request: Request, ...):
    # 5-gate security chain: signature → idempotency → user → rate limit → persist
    await emit_message_received_event(message_id=message.id, sms_text=body)
    return Response(status_code=200)  # HTTP 200 after Inngest event emit; no TwiML
```

All GPT processing happens in Inngest `process-message` function outside the Twilio response window.

**Twilio signature validation is mandatory in production.** Without it, any HTTP client can POST to your webhook and trigger SMS sends.

### OpenAI Structured Outputs

Use `response_format` with a Pydantic model schema for reliable extraction. GPT-4o and later models support JSON schema mode natively.

```python
# Correct pattern for structured extraction
from openai import AsyncOpenAI
from pydantic import BaseModel

class JobPosting(BaseModel):
    description: str
    location: str
    pay_rate: float
    # ...

client = AsyncOpenAI()
response = await client.beta.chat.completions.parse(
    model="gpt-5.3-chat-latest",
    messages=[...],
    response_format=JobPosting,
)
posting = response.choices[0].message.parsed  # typed JobPosting instance
```

Use `AsyncOpenAI` not `OpenAI` — the synchronous client blocks the event loop.

### SQLAlchemy Async Session Scoping

Use FastAPI dependency injection to scope sessions per request, not per application. Inngest functions are NOT FastAPI request handlers — they create their own sessions via the module-level session factory.

```python
# Correct pattern
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

@router.post("/sms")
async def handle_sms(db: AsyncSession = Depends(get_db), ...):
    ...

# In Inngest function — create a fresh session directly (not via Depends)
async def process_message(ctx, step):
    async with async_session_factory() as session:
        await _orchestrator.run(ctx.event.data["message_id"], session)
```

`expire_on_commit=False` is required for async; otherwise accessing attributes after `commit()` triggers a lazy-load which fails outside a session context.

---

## Sources

Sources: STATE.md, PROJECT.md, REQUIREMENTS.md (HIGH confidence — derived from built system). Updated 2026-03-08.

---

*Stack research for: Vici SMS job matching API*
*Researched: 2026-03-08*
