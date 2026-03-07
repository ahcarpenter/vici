# Phase 2: GPT Extraction Service - Research

**Researched:** 2026-03-07
**Domain:** OpenAI structured outputs, Pinecone async, Braintrust LLM observability, tenacity retry
**Confidence:** HIGH (all five key unknowns resolved against current docs/search)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXT-01 | GPT classifies SMS as job posting, worker earnings goal, or unknown | Wrapper-class discriminated union pattern via `client.beta.chat.completions.parse`; Literal discriminator field on each branch |
| EXT-02 | Job posting extracts description, date/time, flexibility, duration (optional), location, pay/rate | `JobExtraction(BaseModel)` with all required fields + `Optional[float]` duration; structured outputs enforces field presence |
| EXT-03 | Worker goal extracts target earnings amount and timeframe | `WorkerExtraction(BaseModel)` with `target_earnings: float` and `target_timeframe: str` |
| EXT-04 | Unknown messages return graceful fallback | `UnknownMessage(BaseModel)` branch in discriminated union; caller enqueues SMS reply when this type is returned |
| STR-01 | Extracted job data persisted in PostgreSQL jobs table | `JobRepository.create(session, job_create)` async write; Job SQLModel already exists from Phase 1 |
| STR-02 | Extracted worker goal persisted in PostgreSQL workers table | `WorkerRepository.create(session, worker_create)` async write; Worker SQLModel already exists |
| VEC-01 | Job embeddings written to Pinecone at job creation | `PineconeAsyncio` + `IndexAsyncio` context-manager pattern; `text-embedding-3-small` via AsyncOpenAI; upsert after job DB write returns id |
| OBS-01 | All GPT calls visible in Braintrust with prompt, output, model, latency, tokens | `wrap_openai(AsyncOpenAI(...))` + `init_logger(project=...)` — automatic instrumentation, no explicit span context needed |
</phase_requirements>

---

## Summary

Phase 2 builds the core extraction pipeline: a single OpenAI call that simultaneously classifies and extracts structured data from raw SMS text, persists results to PostgreSQL, and writes job embeddings to Pinecone. All five flagged unknowns are now resolved. The correct model string is `gpt-5.2` (confirmed live, 400K context window, $1.75/$14 per million tokens). Structured outputs support discriminated unions via a wrapper class pattern — the root object cannot be `anyOf` directly, but a wrapper with a `Literal` discriminator field on each branch resolves this. Braintrust instrumentation is a one-liner `wrap_openai(AsyncOpenAI(...))`. Pinecone provides a first-class async API via `PineconeAsyncio` / `IndexAsyncio` context managers. Tenacity retry uses `retry_if_exception_type(RateLimitError)` with `wait_random_exponential`.

**Primary recommendation:** Implement a single `ExtractionService.process(sms_text, phone_hash)` async method that runs the full pipeline — classify+extract in one GPT call, branch on result type, write to DB, optionally write to Pinecone. Keep the service pure (no FastAPI dependencies) so it is unit-testable with mocked OpenAI and Pinecone clients.

---

## Key Unknown Resolutions

### Unknown 1: GPT-5.2 Model String

**CONFIRMED.** The exact API model string is `gpt-5.2`.

- Context window: 400,000 tokens
- Knowledge cutoff: Aug 2025
- Pricing: $1.75 input / $14 output per million tokens
- Date-stamped snapshot format exists (e.g. `gpt-5.2-2025-XX-XX`) but the plain `gpt-5.2` alias tracks latest stable snapshot
- Confidence: HIGH — multiple current sources including OpenAI model catalog, OpenRouter, and search results dated March 2026

### Unknown 2: Structured Output API for Discriminated Union Schemas

**RESOLVED with workaround required.**

The Chat Completions API method `client.beta.chat.completions.parse` is the standard structured-output path (stable in SDK, `beta` namespace is a misnomer — this is production-ready). The `response_format` parameter accepts a Pydantic `BaseModel` class directly; the SDK handles JSON schema conversion and deserialization.

**Critical constraint:** The root schema object cannot be `anyOf` (union). OpenAI's structured outputs reject a bare `Union[JobExtraction, WorkerExtraction, UnknownMessage]` as the root. The workaround is a **wrapper class** pattern:

```python
class ExtractionResult(BaseModel):
    message_type: Literal["job_posting", "worker_goal", "unknown"]
    job: Optional[JobExtraction] = None
    worker: Optional[WorkerExtraction] = None
    unknown: Optional[UnknownMessage] = None
```

The model sets `message_type` and populates exactly one of the optional branches. The caller then checks `message_type` to determine which branch to read. This satisfies the "no anyOf root" constraint while producing a fully typed discriminated result.

**Additional constraints on Pydantic models used with structured outputs:**
- No field default values (use `Optional[X] = None` only where the field is genuinely nullable, not to smuggle defaults)
- `additionalProperties` must be `false` (SDK enforces this automatically for Pydantic models)
- Enums must be defined as `Literal` values rather than Python `Enum` classes for maximum compatibility

Confidence: HIGH — verified against OpenAI structured outputs docs and community forum issues.

### Unknown 3: Braintrust Instrumentation Pattern

**CONFIRMED.** Braintrust auto-instruments async OpenAI clients with a single wrap call.

```python
from braintrust import init_logger, wrap_openai
from openai import AsyncOpenAI

logger = init_logger(project="vici")
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
```

Every call through `client` is automatically logged — prompt, output, model, latency, tokens. No explicit span context or decorator needed. The `logger` should be initialized once at module load time (singleton), not per-request.

Confidence: HIGH — verified against Braintrust official docs at braintrust.dev/docs/providers/openai.

### Unknown 4: Pinecone v3+ Async Client Patterns

**CONFIRMED.** Pinecone provides a native async API via `PineconeAsyncio`.

```python
from pinecone import PineconeAsyncio, Vector

async with PineconeAsyncio(api_key=settings.pinecone_api_key) as pc:
    async with pc.IndexAsyncio(host=settings.pinecone_index_host) as idx:
        await idx.upsert(vectors=[
            Vector(id=str(job_id), values=embedding_vector, metadata={"phone_hash": phone_hash})
        ])
```

Install: `pip install "pinecone[asyncio]"` — the `asyncio` extra is required.

The `host` parameter requires the full index host URL from the Pinecone console (not just the index name). Store as `PINECONE_INDEX_HOST` env var.

For the test suite, `PineconeAsyncio` and `IndexAsyncio` should be mocked with `AsyncMock` using the context manager protocol.

Confidence: HIGH — verified against official Pinecone async SDK docs at sdk.pinecone.io/python/asyncio.html.

### Unknown 5: Tenacity Retry Patterns for OpenAI

**CONFIRMED.** Standard pattern:

```python
from openai import RateLimitError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

@retry(
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
    stop=stop_after_attempt(4),
    wait=wait_random_exponential(multiplier=1, min=1, max=60),
)
async def _call_openai_with_retry(...):
    ...
```

`wait_random_exponential` adds jitter to avoid thundering herd on 429 bursts. `stop_after_attempt(4)` prevents indefinite loops. `APIStatusError` (5xx) is included alongside `RateLimitError` (429) to handle transient server errors.

**Do not retry** on `openai.BadRequestError` (400) or `openai.AuthenticationError` (401) — these are configuration errors, not transient failures.

Confidence: HIGH — verified against OpenAI Cookbook and Instructor library docs.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| openai | >=1.0 | GPT-5.2 API client + embeddings | Official async SDK; `wrap_openai` compatible |
| pinecone[asyncio] | >=3.0 | Vector store upsert for job embeddings | Native async context managers; first-party |
| braintrust | latest | LLM observability (OBS-01) | Single `wrap_openai` call; zero-overhead for traces |
| tenacity | >=8.0 | Retry with exponential backoff | OpenAI Cookbook-recommended; `wait_random_exponential` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | >=2.0 | Extraction schema definitions | Already in stack via SQLModel; BaseModel for extraction results |
| pytest-mock / unittest.mock | stdlib | Mock OpenAI + Pinecone in tests | AsyncMock for async client methods |

### Not in Stack (already installed from Phase 1)
- `sqlmodel`, `sqlalchemy[asyncio]`, `asyncpg` — repository writes use existing async session infrastructure
- `structlog` — log extraction results using existing logger
- `opentelemetry-*` — OTel already instrumented; Braintrust handles LLM-specific tracing

**Installation additions for Phase 2:**
```bash
uv add openai "pinecone[asyncio]" braintrust tenacity
```

---

## Architecture Patterns

### Recommended Project Structure for Phase 2

```
src/
├── extraction/
│   ├── __init__.py
│   ├── schemas.py          # ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage
│   ├── service.py          # ExtractionService with process() method
│   ├── prompts.py          # System prompt string (single source of truth)
│   └── pinecone_client.py  # PineconeAsyncio wrapper / singleton factory
├── jobs/
│   ├── models.py           # Job SQLModel (already exists)
│   ├── schemas.py          # JobCreate (fill out from Phase 2)
│   └── repository.py       # async create() method
└── workers/
    ├── models.py            # Worker SQLModel (already exists)
    ├── schemas.py           # WorkerCreate (fill out from Phase 2)
    └── repository.py        # async create() method
```

### Pattern 1: Wrapper-Class Discriminated Union for Structured Outputs

**What:** A single root Pydantic model with a `Literal` discriminator field and optional branches for each result type.

**When to use:** Any time you need OpenAI to return one of several structured types — the API forbids `anyOf` at root, so all branching must be inside a wrapper.

```python
# src/extraction/schemas.py
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel


class JobExtraction(BaseModel):
    description: str
    ideal_datetime: Optional[str] = None   # ISO-8601 string; nullable per EXT-02
    datetime_flexible: bool
    estimated_duration_hours: Optional[float] = None  # explicitly optional per EXT-02
    location: str
    pay_rate: float


class WorkerExtraction(BaseModel):
    target_earnings: float
    target_timeframe: str


class UnknownMessage(BaseModel):
    reason: str   # short explanation for logging


class ExtractionResult(BaseModel):
    message_type: Literal["job_posting", "worker_goal", "unknown"]
    job: Optional[JobExtraction] = None
    worker: Optional[WorkerExtraction] = None
    unknown: Optional[UnknownMessage] = None
```

### Pattern 2: ExtractionService with Dependency Injection

**What:** A class initialized with OpenAI client and settings; `process()` is the public async method; no FastAPI imports.

**When to use:** Keeps service unit-testable (inject mock clients) and decoupled from HTTP layer.

```python
# src/extraction/service.py
from braintrust import init_logger, wrap_openai
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from src.extraction.schemas import ExtractionResult
from src.extraction.prompts import SYSTEM_PROMPT

logger = init_logger(project="vici")

class ExtractionService:
    def __init__(self, settings):
        self._client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0))

    async def process(self, sms_text: str, phone_hash: str) -> ExtractionResult:
        result = await self._call_with_retry(sms_text)
        return result

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_random_exponential(multiplier=1, min=1, max=60),
    )
    async def _call_with_retry(self, sms_text: str) -> ExtractionResult:
        completion = await self._client.beta.chat.completions.parse(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": sms_text},
            ],
            response_format=ExtractionResult,
        )
        return completion.choices[0].message.parsed
```

Note: `max_retries=0` on the OpenAI client disables SDK-level retries — tenacity handles all retry logic consistently.

### Pattern 3: Pinecone Write After DB Insert

**What:** Write embedding to Pinecone only after the PostgreSQL row is committed and has an `id`. Use the DB row `id` as the Pinecone vector id.

**When to use:** Every job creation in `ExtractionService.process()` when `message_type == "job_posting"`.

```python
# Inside ExtractionService.process() after job DB write
embedding_response = await self._client.embeddings.create(
    model="text-embedding-3-small",
    input=extraction.description,
)
vector = embedding_response.data[0].embedding  # 1536-dim list[float]

async with PineconeAsyncio(api_key=settings.pinecone_api_key) as pc:
    async with pc.IndexAsyncio(host=settings.pinecone_index_host) as idx:
        await idx.upsert(vectors=[
            Vector(id=str(job_id), values=vector, metadata={"phone_hash": phone_hash})
        ])
```

### Anti-Patterns to Avoid

- **Root-level Union as response_format:** `response_format=Union[JobExtraction, WorkerExtraction]` — OpenAI rejects `anyOf` at root. Always use a wrapper class with a discriminator field.
- **Pydantic fields with non-None defaults:** `description: str = ""` — OpenAI structured outputs reject fields with default values (other than `None` for Optional). Every non-optional field must have no default.
- **Re-initializing Braintrust logger per request:** `init_logger` should be called once at module load; calling it per-request creates duplicate loggers and corrupts trace context.
- **Opening Pinecone context manager per call inside tight loops:** For batch writes, reuse a single `IndexAsyncio` context. For one-off writes (job creation), the context manager overhead is acceptable.
- **Retrying on `BadRequestError`:** 400-class errors from OpenAI indicate a schema or prompt problem — retrying wastes quota and masks the root cause.
- **SDK-level retries AND tenacity:** Set `max_retries=0` on `AsyncOpenAI` when using tenacity to avoid double-retry and unpredictable backoff behavior.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema validation of GPT output | Custom schema parser | `client.beta.chat.completions.parse` + Pydantic | SDK handles schema enforcement, refusal detection, and deserialization |
| Retry with jitter | Custom sleep loop | `tenacity.wait_random_exponential` | Handles thread-safety, async compatibility, and jitter math correctly |
| LLM call tracing | Custom span creation | `braintrust.wrap_openai` | Captures token counts, latency, and prompt/response — no manual instrumentation |
| Async vector upsert | HTTP requests to Pinecone REST | `pinecone[asyncio]` `PineconeAsyncio` | Handles connection pooling, retries, batching |
| Embedding generation | Local embedding model | `text-embedding-3-small` via same AsyncOpenAI client | Already wrapped by Braintrust; consistent observability |

**Key insight:** The OpenAI SDK's `parse()` method is the only safe path for structured outputs. Any raw JSON parsing, regex extraction, or manual schema validation will fail on edge cases the SDK handles correctly (refusals, partial JSON, schema violations).

---

## Common Pitfalls

### Pitfall 1: anyOf at Root Rejected by Structured Outputs

**What goes wrong:** Passing `response_format=Union[JobExtraction, WorkerExtraction, UnknownMessage]` causes an immediate API error: "Root objects cannot be the anyOf type."

**Why it happens:** OpenAI's structured output grammar engine requires a single root schema object; union at root produces `anyOf` which the grammar engine cannot root against.

**How to avoid:** Always wrap in `ExtractionResult` with a `message_type: Literal[...]` discriminator. The model learns to set the flag and populate the matching branch.

**Warning signs:** `openai.BadRequestError` with schema validation message on first call.

### Pitfall 2: Optional Fields with Default Values Rejected

**What goes wrong:** A Pydantic model like `class JobExtraction(BaseModel): description: str = ""` causes API rejection.

**Why it happens:** OpenAI structured outputs require `additionalProperties: false` and no default values in the schema. Pydantic's `default=` emits a `default` key in the JSON schema that OpenAI rejects.

**How to avoid:** Non-optional fields have no default. Optional fields use `Optional[X] = None` only. Never use `= ""`, `= 0`, `= []`, etc.

**Warning signs:** `openai.BadRequestError` referencing "default values not supported."

### Pitfall 3: Pinecone Index Host vs. Index Name

**What goes wrong:** Passing the index name (e.g., `"vici-jobs"`) to `IndexAsyncio(host=...)` fails with a connection error.

**Why it happens:** Pinecone v3+ requires the full host URL (e.g., `"vici-jobs-xxxx.svc.aped-4627-b74a.pinecone.io"`), not the index name. The host is different per account and region.

**How to avoid:** Store `PINECONE_INDEX_HOST` as an env var with the full host URL from the Pinecone console. Never construct the host from the index name.

**Warning signs:** `ConnectionError` or DNS resolution failure when constructing `IndexAsyncio`.

### Pitfall 4: Braintrust `init_logger` Called Per Request

**What goes wrong:** Calling `init_logger(project="vici")` inside `ExtractionService.process()` creates a new logger per call, leading to duplicate trace exports and memory growth.

**Why it happens:** `init_logger` creates a new logger instance; it is not idempotent by default.

**How to avoid:** Call `init_logger` once at module level or in `__init__`; store as class attribute.

**Warning signs:** Braintrust dashboard shows duplicate traces for each call.

### Pitfall 5: Forgetting `max_retries=0` on AsyncOpenAI with tenacity

**What goes wrong:** The OpenAI SDK default `max_retries=2` retries silently before tenacity sees the error, causing 3x actual attempts per tenacity attempt and corrupting backoff timing.

**Why it happens:** SDK-level retry is independent of tenacity; they compose multiplicatively.

**How to avoid:** Always `AsyncOpenAI(max_retries=0)` when tenacity is the retry layer.

---

## Code Examples

### Braintrust + AsyncOpenAI Initialization (Module Level)

```python
# src/extraction/service.py  — module-level singleton
import os
from braintrust import init_logger, wrap_openai
from openai import AsyncOpenAI

_bt_logger = init_logger(project="vici")

def make_openai_client(api_key: str) -> AsyncOpenAI:
    """Return a Braintrust-wrapped async OpenAI client with retries disabled."""
    return wrap_openai(AsyncOpenAI(api_key=api_key, max_retries=0))
```

### Tenacity Decorator for Async OpenAI Calls

```python
from openai import RateLimitError, APIStatusError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

@retry(
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
    stop=stop_after_attempt(4),
    wait=wait_random_exponential(multiplier=1, min=1, max=60),
)
async def _call_openai(client, messages, response_format):
    completion = await client.beta.chat.completions.parse(
        model="gpt-5.2",
        messages=messages,
        response_format=response_format,
    )
    return completion.choices[0].message.parsed
```

### Pinecone Async Upsert

```python
from pinecone import PineconeAsyncio, Vector

async def write_job_embedding(
    job_id: int,
    description: str,
    phone_hash: str,
    openai_client,
    pinecone_api_key: str,
    pinecone_index_host: str,
) -> None:
    # Generate embedding via the same Braintrust-wrapped client
    emb_resp = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=description,
    )
    vector = emb_resp.data[0].embedding  # list[float], 1536 dims

    async with PineconeAsyncio(api_key=pinecone_api_key) as pc:
        async with pc.IndexAsyncio(host=pinecone_index_host) as idx:
            await idx.upsert(vectors=[
                Vector(id=str(job_id), values=vector, metadata={"phone_hash": phone_hash})
            ])
```

### Mocking in Tests (AsyncMock pattern)

```python
from unittest.mock import AsyncMock, MagicMock, patch
from src.extraction.schemas import ExtractionResult, JobExtraction

def make_mock_openai_client(parsed_result: ExtractionResult):
    mock_message = MagicMock()
    mock_message.parsed = parsed_result
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)
    mock_client.embeddings.create = AsyncMock(return_value=MagicMock(
        data=[MagicMock(embedding=[0.0] * 1536)]
    ))
    return mock_client
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Two-step: classify then extract | Single `parse()` call with `ExtractionResult` wrapper | GPT-4o era (2024) | Halves latency and token cost; eliminates second-call failure mode |
| Manual JSON parsing of GPT output | `client.beta.chat.completions.parse` | SDK v1.0+ | Guaranteed schema compliance; SDK handles malformed JSON |
| `openai.ChatCompletion.create` | `client.beta.chat.completions.parse` | SDK v1.0 migration | async-native, typed response |
| Pinecone `pinecone.init()` global state | `PineconeAsyncio` context manager | Pinecone SDK v3 | Thread/async safe; explicit resource cleanup |
| Manual OTel spans for LLM calls | `braintrust.wrap_openai` | Braintrust SDK 2024+ | Automatic token/latency capture with zero code change |

**Deprecated/outdated:**
- `pinecone.init(api_key=..., environment=...)` — removed in v3; replaced by `Pinecone(api_key=...)` / `PineconeAsyncio`
- `openai.ChatCompletion.create` (sync) — replaced by `client.chat.completions.create` async
- `response_format={"type": "json_object"}` (JSON mode) — superseded by structured outputs with schema enforcement

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (already installed) |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/extraction/ -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXT-01 | Job posting SMS returns `message_type="job_posting"` with `JobExtraction` populated | unit | `pytest tests/extraction/test_service.py::test_classify_job -x` | Wave 0 |
| EXT-01 | Worker SMS returns `message_type="worker_goal"` with `WorkerExtraction` populated | unit | `pytest tests/extraction/test_service.py::test_classify_worker -x` | Wave 0 |
| EXT-02 | JobExtraction has all required fields + nullable duration | unit | `pytest tests/extraction/test_schemas.py::test_job_extraction_schema -x` | Wave 0 |
| EXT-03 | WorkerExtraction has target_earnings + target_timeframe | unit | `pytest tests/extraction/test_schemas.py::test_worker_extraction_schema -x` | Wave 0 |
| EXT-04 | Ambiguous SMS returns `message_type="unknown"` | unit | `pytest tests/extraction/test_service.py::test_classify_unknown -x` | Wave 0 |
| STR-01 | Job record written to PostgreSQL after job extraction | integration | `pytest tests/extraction/test_service.py::test_job_persistence -x` | Wave 0 |
| STR-02 | Worker record written to PostgreSQL after worker extraction | integration | `pytest tests/extraction/test_service.py::test_worker_persistence -x` | Wave 0 |
| VEC-01 | Pinecone upsert called with job_id and 1536-dim embedding after job creation | unit | `pytest tests/extraction/test_service.py::test_pinecone_upsert -x` | Wave 0 |
| OBS-01 | Braintrust `wrap_openai` applied to client (instrumentation present) | unit | `pytest tests/extraction/test_service.py::test_braintrust_instrumentation -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/extraction/ -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/extraction/__init__.py` — package init
- [ ] `tests/extraction/test_schemas.py` — Pydantic schema validation tests
- [ ] `tests/extraction/test_service.py` — ExtractionService unit + integration tests with AsyncMock
- [ ] `tests/extraction/conftest.py` — shared mock client fixtures

*(Existing `tests/conftest.py` session fixtures can be reused; extraction tests need their own mock factories)*

---

## Open Questions

1. **Pinecone index dimension and region**
   - What we know: `text-embedding-3-small` produces 1536-dim vectors; Pinecone index must be created with `dimension=1536` and `metric="cosine"`
   - What's unclear: The Pinecone index does not yet exist in the project; `PINECONE_API_KEY` and `PINECONE_INDEX_HOST` are not in `.env`
   - Recommendation: Wave 0 of Plan 02-02 should include a "create Pinecone index" setup step and add both env vars to `.env.example`

2. **Braintrust project exists?**
   - What we know: `init_logger(project="vici")` creates the project on first use if it doesn't exist
   - What's unclear: `BRAINTRUST_API_KEY` is not yet in `.env`
   - Recommendation: Add `BRAINTRUST_API_KEY` to settings and `.env.example` in Wave 0 of Plan 02-01

3. **`ideal_datetime` storage format**
   - What we know: The `Job` SQLModel column is `Optional[datetime]`; GPT returns ISO-8601 strings
   - What's unclear: GPT may return relative times ("tomorrow morning") that cannot be parsed into datetime without knowing the sender's timezone
   - Recommendation: Store as `Optional[str]` in `JobExtraction` (raw GPT output), then attempt `datetime.fromisoformat()` parse in the repository layer; fall back to `None` on failure. Defer full datetime normalization to v2.

---

## Sources

### Primary (HIGH confidence)
- OpenAI model catalog search (March 2026) — `gpt-5.2` model string confirmed
- [OpenRouter GPT-5.2 entry](https://openrouter.ai/openai/gpt-5.2) — context window (400K) and pricing ($1.75/$14)
- [Pinecone Async SDK docs](https://sdk.pinecone.io/python/asyncio.html) — `PineconeAsyncio` / `IndexAsyncio` pattern
- [Braintrust OpenAI provider docs](https://www.braintrust.dev/docs/providers/openai) — `wrap_openai(AsyncOpenAI(...))` pattern
- [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs/) — `client.beta.chat.completions.parse` + Pydantic

### Secondary (MEDIUM confidence)
- [OpenAI community forum: anyOf at root rejected](https://community.openai.com/t/responses-api-doesnt-like-my-list-of-anyof-output-schema/1276965) — discriminated union constraint verified by community reports consistent with official docs behavior
- [Instructor library retry docs](https://python.useinstructor.com/concepts/retrying/) — tenacity pattern for OpenAI async

### Tertiary (LOW confidence)
- None — all critical claims verified by primary or secondary sources

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed via official docs and search with current (March 2026) sources
- Architecture: HIGH — wrapper-class discriminated union pattern verified against OpenAI API constraints
- Pitfalls: HIGH — `anyOf` root rejection confirmed via official community/docs; others derived from verified constraints
- Model string: HIGH — `gpt-5.2` confirmed via multiple current sources

**Research date:** 2026-03-07
**Valid until:** 2026-04-07 (stable APIs; OpenAI model catalog changes faster — re-verify if project pauses > 30 days)
