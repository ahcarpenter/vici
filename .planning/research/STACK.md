# Stack Research

**Domain:** SMS-based job matching API (Python/FastAPI + Twilio + OpenAI + PostgreSQL/pgvector)
**Researched:** 2026-03-05
**Confidence:** MEDIUM — web tools unavailable; based on training data (cutoff Aug 2025). Flag version pins for verification before first `pip install`.

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
| PostgreSQL | 16 | Primary datastore | pgvector extension is available on PG 14+ but PG 16 has the best support with pgvector 0.7+; most managed providers (Supabase, Neon, Railway) default to PG 16. Confidence: HIGH |
| pgvector | ^0.3 (Python), extension 0.7+ | Vector storage and similarity search | The `pgvector-python` package exposes `Vector` column type for SQLAlchemy 2.0 async; pgvector 0.7 added HNSW index support which outperforms IVFFlat for small-to-medium datasets. Schema includes embeddings now even though v1 matching is earnings math only. Confidence: MEDIUM (verify pgvector-python version) |
| Alembic | ^1.13 | Database schema migrations | First-class SQLAlchemy integration; supports async engines via `run_sync` pattern; the only production-viable migration tool for SQLAlchemy projects. Confidence: HIGH |
| openai | ^1.30 | OpenAI GPT API client | The v1.x SDK (released Nov 2023) is the modern interface: `client.chat.completions.create()` with `response_format={"type": "json_schema", ...}` enables structured outputs. gpt-5.3-chat-latest is specified by the product owner; use the model string `"gpt-5.3-chat-latest"` in requests. Confidence: MEDIUM (verify latest 1.x pin; gpt-5.3-chat-latest model string needs validation against OpenAI's naming) |
| twilio | ^9.0 | Twilio SMS SDK | Handles signature validation (`RequestValidator`) and outbound `client.messages.create()`. The Python helper library generates TwiML response XML which FastAPI returns as `Response(content=twiml, media_type="text/xml")`. Confidence: MEDIUM (verify 9.x is current series) |
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
| tenacity | ^8.2 | Retry logic | Wrap OpenAI API calls with exponential backoff; OpenAI rate limits and transient errors are the most common production failure mode. Confidence: HIGH |
| structlog | ^24.0 | Structured logging | JSON-formatted logs with request context (phone number, message ID) are essential for observability; integrates cleanly with FastAPI middleware. |
| sentry-sdk | ^2.0 | Error tracking | Add `sentry_sdk.init()` at startup; the FastAPI integration captures unhandled exceptions automatically with full request context. |
| gunicorn | ^22.0 | Process manager | In production, run `gunicorn -w 4 -k uvicorn.workers.UvicornWorker`; manages worker restarts without a separate supervisor. Only needed for multi-worker production deploys. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Dependency management and virtual environments | Dramatically faster than pip+venv; `uv sync` installs from `pyproject.toml` lockfile. Use `pyproject.toml` as the single source of truth for deps. Replaces pip, pip-tools, and virtualenv. |
| ruff | Linting + formatting | Replaces flake8 + black + isort in a single fast tool; configure in `pyproject.toml` under `[tool.ruff]`. |
| mypy | Static type checking | With SQLAlchemy 2.0's `MappedColumn` types and Pydantic v2 models, type coverage is high; configure `strict = false` initially and tighten over time. |
| Docker + docker-compose | Local dev environment | `docker-compose.yml` with a `postgres` service (image: `pgvector/pgvector:pg16`) gives a local DB with the extension pre-installed; avoids pgvector extension install friction. |
| pre-commit | Git hook runner | Enforce ruff + mypy on commit; prevents type and lint regressions from landing. |

---

## Installation

```bash
# Requires uv (https://docs.astral.sh/uv/)

# Core runtime
uv add fastapi "uvicorn[standard]" sqlalchemy asyncpg alembic \
       pgvector openai twilio \
       pydantic-settings tenacity structlog sentry-sdk

# Dev / test
uv add --dev pytest pytest-asyncio httpx factory-boy \
            ruff mypy pre-commit

# Local secrets loading (dev only)
uv add python-dotenv
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| SQLAlchemy 2.0 async | Tortoise ORM | If you want a Django-style async ORM with simpler migration story; not recommended here because pgvector integration is SQLAlchemy-first and Alembic is required by the layered architecture constraint. |
| SQLAlchemy 2.0 async | SQLModel | SQLModel (FastAPI author's lib) is thin SQLAlchemy + Pydantic wrapper; fine for simple apps but adds an abstraction layer that complicates pgvector column types and async session scoping. Avoid for this complexity level. |
| asyncpg | psycopg3 (async) | psycopg3 has excellent async support and is more standard; either works. asyncpg has the larger existing body of community examples for SQLAlchemy + FastAPI. Stick with asyncpg unless you hit a specific compatibility issue. |
| pgvector-python | pgvecto.rs | pgvecto.rs is a newer alternative with better performance at scale; but pgvector has better managed-cloud support and is the safe default for MVP. Revisit at 1M+ vectors. |
| structlog | Python stdlib logging | stdlib logging doesn't produce structured JSON by default; structlog requires ~5 lines of config and the observability benefit is immediate in a production webhook handler. |
| uv | poetry | poetry is viable; uv is 10-100x faster and has become the community standard as of 2025. Either works; uv is the better default for new projects. |
| tenacity | custom retry loop | Roll-your-own retry logic for OpenAI calls is a common source of subtle bugs (non-retryable errors being retried, missing jitter). Use tenacity. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| psycopg2 | Synchronous only; blocks the event loop in async FastAPI handlers, causing cascading latency under concurrent SMS traffic | asyncpg (via SQLAlchemy `postgresql+asyncpg://`) |
| Flask | No native async; every Twilio webhook handler blocks the process; poor OpenAPI support | FastAPI |
| Django ORM | Sync-only ORM (Django async support is partial); pgvector integration via `django-pgvector` is third-party with limited SQLAlchemy/Alembic compatibility | SQLAlchemy 2.0 async |
| SQLAlchemy 1.x | The legacy `Query` API is removed in 2.0; 1.x async patterns (`AsyncSession` via `sqlalchemy.ext.asyncio`) require significant boilerplate vs. 2.0's unified API | SQLAlchemy 2.0 |
| Pydantic v1 | FastAPI 0.100+ uses Pydantic v2 internally; mixing v1 models causes `ValidationError` import conflicts and breaks OpenAI structured output schema generation | Pydantic v2 (comes with FastAPI) |
| LangChain | Significant abstraction overhead for a single-model, single-prompt use case; hides token costs, complicates structured output schemas, and adds a large transitive dependency tree | Direct `openai` SDK with Pydantic schema |
| Celery + Redis | Overkill for SMS webhook volume in v1; adds operational complexity (Redis instance, worker processes, broker config) for a use case that async FastAPI + asyncpg handles inline | Inline async handlers in FastAPI; revisit if queue depth becomes a problem |
| requests | Synchronous HTTP client; blocks event loop | httpx (async) |

---

## Stack Patterns by Variant

**If deploying to Railway (recommended for MVP):**
- Use `pgvector/pgvector:pg16` as the Postgres service image or Railway's managed Postgres (which includes pgvector)
- Set `DATABASE_URL` as a Railway environment variable; `pydantic-settings` binds it automatically
- Single `Dockerfile` with `CMD ["gunicorn", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app"]`

**If deploying to Fly.io:**
- Use Fly Postgres with the pgvector extension enabled (`fly postgres connect` + `CREATE EXTENSION vector;`)
- `fly.toml` with health check on `GET /health`
- Same `gunicorn` command as above

**If running locally:**
- `docker-compose up` starts `pgvector/pgvector:pg16` on port 5432
- `uv run uvicorn app.main:app --reload` for hot reload
- Use `ngrok http 8000` to expose local endpoint to Twilio webhook config

**If OpenAI rate limits become a bottleneck:**
- Add `tenacity` retry with `wait_exponential(multiplier=1, min=2, max=30)` and `retry_on_exception(is_rate_limit_error)`
- Consider batching multiple extractions into a single prompt (but v1 volume is low enough this won't be needed)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| fastapi ^0.111 | pydantic v2.x | FastAPI 0.100+ dropped pydantic v1 support; do not mix |
| sqlalchemy ^2.0 | asyncpg ^0.29 | SQLAlchemy 2.0 async engine requires asyncpg 0.24+; 0.29 is safe |
| pgvector ^0.3 | sqlalchemy ^2.0 | pgvector-python 0.3+ has SQLAlchemy 2.0 `TypeDecorator` support |
| alembic ^1.13 | sqlalchemy ^2.0 | Alembic 1.13 is the first release with full SQLAlchemy 2.0 support for async migration env config |
| pytest-asyncio ^0.23 | pytest ^8.0 | pytest-asyncio 0.21+ changed the default mode to `strict`; set `asyncio_mode = "auto"` in `pyproject.toml` or annotate every async test |
| openai ^1.30 | python 3.12 | openai v1.x requires Python 3.7.1+; no known conflicts on 3.12 |
| twilio ^9.0 | python 3.12 | twilio 9.x dropped Python 3.7 support; requires 3.8+; compatible with 3.12 |

---

## Critical Integration Patterns

### Twilio Webhook Handler

Twilio sends `application/x-www-form-urlencoded` POST, not JSON. FastAPI does not auto-parse form data as Pydantic models; use `Form(...)` params or a dedicated `Request` object.

```python
# Correct pattern
from fastapi import APIRouter, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

@router.post("/sms")
async def handle_sms(
    From: str = Form(...),
    Body: str = Form(...),
    # ... other Twilio fields
):
    # Validate Twilio signature before processing
    # Return TwiML XML, not JSON
    resp = MessagingResponse()
    resp.message("Got it.")
    return Response(content=str(resp), media_type="text/xml")
```

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

Use FastAPI dependency injection to scope sessions per request, not per application.

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
```

`expire_on_commit=False` is required for async; otherwise accessing attributes after `commit()` triggers a lazy-load which fails outside a session context.

---

## Sources

- Training data (cutoff Aug 2025) — FastAPI, SQLAlchemy 2.0, asyncpg, Pydantic v2 patterns — HIGH confidence for established patterns
- Training data — OpenAI SDK v1 structured outputs (`beta.chat.completions.parse`) — MEDIUM confidence (verify `gpt-5.3-chat-latest` model string against OpenAI's current model naming)
- Training data — Twilio Python SDK 9.x, `RequestValidator`, TwiML patterns — MEDIUM confidence (verify 9.x is current major version)
- Training data — pgvector-python 0.3+ SQLAlchemy 2.0 integration — MEDIUM confidence (verify version pin)
- Training data — uv, ruff as 2025 Python toolchain standards — HIGH confidence
- **NOTE:** WebSearch and WebFetch were unavailable during this research session. All version numbers should be verified against PyPI before committing to a lockfile: `uv add fastapi openai twilio pgvector sqlalchemy asyncpg alembic` will resolve current compatible versions automatically.

---

*Stack research for: Vici SMS job matching API*
*Researched: 2026-03-05*
