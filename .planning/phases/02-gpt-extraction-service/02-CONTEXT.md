# Phase 2: GPT Extraction Service - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Build `ExtractionService` — a single GPT call that classifies each inbound SMS as a job posting, worker earnings goal, or unknown; extracts structured fields from the message; persists results to PostgreSQL; and writes job embeddings to Pinecone. Braintrust wraps all GPT calls for LLM observability. This phase does NOT send confirmation or match SMS replies — that is Phase 4. Phase 2 ends when extraction data is persisted and embeddings are queued.

</domain>

<decisions>
## Implementation Decisions

### System Prompt Design
- **Context**: Minimal — task-only, no product backstory in system prompt
- **Examples**: 5 few-shot examples (2 job postings, 2 worker goals, 1 unknown) in `src/extraction/prompts.py` as a static constant string
- **Field definitions**: Explicit field definitions for all ambiguous fields: `location` (street address or neighborhood mentioned), `pay_rate`/`pay_type` (rate as-extracted, type as 'hourly' | 'flat' | 'unknown'), `datetime_flexible` (whether the poster indicated flexibility), `target_timeframe` (the worker's stated window)
- **Date injection**: Static system prompt; today's UTC date injected as prefix of the user message: `"Today is {ISO-8601 date}. Message: {sms_text}"`. This preserves prompt caching and keeps Braintrust traces comparable across calls.
- **Datetime resolution**: Instruct GPT to resolve relative datetimes ("tomorrow morning") to ISO-8601 using the injected date. Infer timezone from the location field (e.g., "downtown Chicago" → America/Chicago). Fall back to UTC when timezone cannot be inferred from location.
- **Unknown classification**: Strict — if not clearly a job posting or worker goal, classify as unknown. No stretching.
- **Duration**: Instruct GPT to convert vague durations ("a few hours", "half a day") to best-guess float (e.g., 3.0, 4.0).
- **Missing pay_rate**: A job posting with no rate is still classified as `job_posting` with `pay_rate=null`. Pay is not required for classification.

### Extraction Schemas (src/extraction/schemas.py)
```python
class JobExtraction(BaseModel):
    description: str
    ideal_datetime: Optional[str] = None        # ISO-8601; null if GPT cannot resolve
    raw_datetime_text: Optional[str] = None     # GPT's raw datetime expression
    inferred_timezone: Optional[str] = None     # IANA name, e.g. "America/Chicago"
    datetime_flexible: bool
    estimated_duration_hours: Optional[float] = None
    raw_duration_text: Optional[str] = None     # GPT's raw duration expression
    location: str
    pay_rate: Optional[float] = None            # null if not mentioned
    pay_type: Literal["hourly", "flat", "unknown"]

class WorkerExtraction(BaseModel):
    target_earnings: float
    target_timeframe: str

class UnknownMessage(BaseModel):
    reason: str

class ExtractionResult(BaseModel):
    message_type: Literal["job_posting", "worker_goal", "unknown"]
    job: Optional[JobExtraction] = None
    worker: Optional[WorkerExtraction] = None
    unknown: Optional[UnknownMessage] = None
```

### Database Schema Additions (Phase 2 migration)
New migration adds the following to the `job` table (existing Phase 1 migration untouched):
- `pay_type` VARCHAR NOT NULL DEFAULT 'unknown' (with CHECK (pay_type IN ('hourly', 'flat', 'unknown')))
- `pay_rate` made nullable: DROP NOT NULL constraint on `pay_rate`; retain CHECK (pay_rate > 0) when not null
- `raw_datetime_text` TEXT NULL
- `inferred_timezone` TEXT NULL — IANA timezone name (e.g., 'America/Chicago')
- `raw_duration_text` TEXT NULL

New table: `pinecone_sync_queue`
- `id` SERIAL PK
- `job_id` INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE
- `status` VARCHAR NOT NULL DEFAULT 'pending' — 'pending' | 'synced' | 'failed'
- `attempts` INTEGER NOT NULL DEFAULT 0
- `last_error` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL

### ExtractionService Module Structure (src/extraction/)
```
src/extraction/
├── __init__.py
├── constants.py       # GPT_MODEL = "gpt-5.2", UNKNOWN_REPLY_TEXT, embedding constants
├── schemas.py         # ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage
├── service.py         # ExtractionService class
├── prompts.py         # SYSTEM_PROMPT string (static), few-shot examples inline
└── pinecone_client.py # PineconeAsyncio wrapper factory
```

### ExtractionService Lifecycle
- Instantiated once as an **app-level singleton** in FastAPI's lifespan context manager, stored on `app.state.extraction_service`
- FastAPI dependency retrieves it from `request.app.state`
- Braintrust logger and OpenAI client initialized once; not re-initialized per request
- `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`, `BRAINTRUST_API_KEY` added to `src/config.py` `Settings`

### Pinecone / Embeddings
- **Provider**: Pinecone Inference API — `llama-text-embed-v2` model (dimension: 1024)
- **Index**: `vici-dev` (already exists and configured with the inference model)
- **Env var**: `PINECONE_INDEX_HOST` stores the full host URL from the Pinecone console. `OPENAI_EMBEDDING_MODEL` is NOT used — Pinecone Inference handles embeddings.
- **Upsert pattern**: Pass `record_id=str(job_id)` + `text=job.description` to Pinecone; the index generates the embedding
- **Failure handling**: Fire-and-forget — if Pinecone upsert fails, log the error, write a `pinecone_sync_queue` row with `status='pending'`, and continue. Do NOT fail the pipeline.
- **Retry**: Inngest cron function `sync-pinecone-queue` sweeps `pinecone_sync_queue` every **5 minutes** for pending/failed rows and retries upsert. Implemented in Phase 2 as a stub cron; full retry logic can follow.

### Pipeline Flow (inside Inngest `process-message`)
1. Call `ExtractionService.process(sms_text, phone_hash, message_id)`
2. GPT classify+extract in one call (`client.beta.chat.completions.parse`)
3. Store full API response JSON in `message.raw_gpt_response` (SEC-04)
4. Branch on `message_type`:
   - `job_posting`: In a **single transaction**, create `job` row + UPDATE `message.message_type = 'job_posting'`. After commit, attempt Pinecone upsert (fire-and-forget).
   - `worker_goal`: In a **single transaction**, create `work_request` row + UPDATE `message.message_type = 'worker_goal'`.
   - `unknown` / GPT refusal: UPDATE `message.message_type = 'unknown'`. Queue unknown reply SMS (Phase 4 wires the send).
5. Write `audit_log` events (see below)
6. If GPT call fails after tenacity exhausted: re-raise exception for Inngest to retry. If Inngest retries also exhaust: send generic error SMS to user — "Sorry, something went wrong. Please try again."

### Error Handling
- **Content refusals** (policy violation): treat as `unknown` — same branch, same fallback SMS
- **GPT call failure** (network/5xx, tenacity exhausted): re-raise → Inngest retries the full function
- **Inngest retries exhausted**: catch at Inngest function level, send error SMS "Sorry, something went wrong. Please try again."
- **Pinecone write failure**: log + write to `pinecone_sync_queue`; do not propagate

### audit_log Events (Phase 2 additions)
| event | detail | when |
|-------|--------|------|
| `gpt_classified` | `{"message_type": "...", "raw_type": "..."}` | After GPT returns |
| `job_created` | `{"job_id": N}` | After job DB write commits |
| `work_request_created` | `{"work_request_id": N}` | After work_request DB write commits |
| `pinecone_write_failed` | `{"job_id": N, "error": "..."}` | When Pinecone upsert fails |
| `gpt_call_failed` | `{"error_type": "...", "attempts": N}` | When tenacity exhausts retries |

### Unknown Message Reply Text
Exact constant in `src/extraction/constants.py`:
```python
UNKNOWN_REPLY_TEXT = (
    "Hi from Vici! We didn't understand your message. "
    "Text us a job (include pay, location, time) or your earnings goal "
    "(e.g., 'I need $200 today')."
)
```

### Confirmation SMS Format (STR-03 — sent in Phase 4)
Format: `"Got it: [desc, max 30 chars]..., [datetime] [timezone abbrev], [location], $[pay] [pay_type], ~[duration]hrs. Reply EDIT to correct."`

Example: `"Got it: mover needed downtown..., Sunday 9am CT, downtown Chicago, $30/hr flat, ~3hrs. Reply EDIT to correct."`

- Description truncated to 30 chars with `...` if longer
- `inferred_timezone` used to display local time (e.g., "9am CT" not "3:00 PM UTC")
- `pay_type` displayed as 'flat' or 'hr' suffix
- If `pay_rate` is null: omit pay from summary
- Allowed to be multi-segment SMS (up to 3 segments / ~480 chars)
- EDIT keyword handling deferred to Phase 4

### Worker SMS (Phase 4)
- Worker goal acknowledgment SMS deferred to Phase 4
- On match: send results directly; no intermediate "Searching..." message needed in Phase 2
- If no matches: send graceful no-match reply (Phase 4)

### Testing Approach
- **Integration tests**: Real PostgreSQL in CI (Docker) + mocked OpenAI + mocked Pinecone
- `pytest tests/extraction/` with Docker-based PostgreSQL for DB constraint validation (TIMESTAMPTZ, nullable checks, pinecone_sync_queue writes)
- OpenAI `client.beta.chat.completions.parse` mocked via `AsyncMock` (research `make_mock_openai_client` pattern)
- Pinecone `PineconeAsyncio` / `IndexAsyncio` mocked via `AsyncMock` context manager protocol

### Claude's Discretion
- Exact prompt wording (field definitions, examples, instruction structure)
- Tenacity retry configuration (stop_after_attempt, wait_random_exponential params — research defaults apply)
- `pinecone_sync_queue` Inngest cron implementation details (retry limit, max attempts before marking 'failed')
- Braintrust `init_logger` singleton pattern details

</decisions>

<specifics>
## Specific Ideas

- Phase 1 CONTEXT.md note: `message.message_type` is NULL at creation; Phase 2 updates it atomically with the job/work_request write. NULL = "not yet processed".
- Phase 1 CONTEXT.md note: `job.ideal_datetime` stores TIMESTAMPTZ when parseable; NULL when GPT cannot resolve. `raw_datetime_text` stores the original expression.
- The Pinecone index `vici-dev` already exists with `llama-text-embed-v2` (1024-dim) — no index creation needed in Wave 0.
- `BRAINTRUST_API_KEY` not yet in `.env` — must be added to `Settings` and `.env.example` in Wave 0.
- `PINECONE_API_KEY` and `PINECONE_INDEX_HOST` not yet in `.env` — add to `Settings` and `.env.example` in Wave 0.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/config.py` — `Settings(BaseSettings)` with `@lru_cache`; add `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`, `BRAINTRUST_API_KEY` here
- `src/database.py` — async SQLAlchemy session factory; all repository writes use this pattern
- `src/jobs/models.py` — `Job` SQLModel exists; Phase 2 migration adds columns to it
- `src/workers/models.py` — `Worker` SQLModel (may need rename to `WorkRequest` per Phase 1 schema)
- `src/main.py` — FastAPI lifespan already exists; `ExtractionService` singleton added here
- `tests/conftest.py` — `_auto_mock_inngest_send` autouse fixture; SQLite session fixtures reusable

### Established Patterns
- Domain-based `src/` structure — `src/extraction/` follows same layout as `src/sms/`, `src/jobs/`
- SQLModel for table definitions, Pydantic `BaseModel` for non-table schemas
- `expire_on_commit=False` on async_sessionmaker — required for async SQLAlchemy
- structlog with auto-injected `trace_id`/`span_id` from active OTel span
- AGENTS.md is the authoritative FastAPI style guide — async routes, dependency chaining, ruff linting

### Integration Points
- Inngest `process-message` function calls `ExtractionService.process()` — this is the entry point for Phase 2 work
- `message` table row already exists when `process-message` fires (created in Phase 1 webhook handler)
- `audit_log` table already exists; Phase 2 adds new `event` values to it
- Docker Compose: PostgreSQL + Inngest Dev Server + Jaeger all running; no new services for Phase 2

</code_context>

<deferred>
## Deferred Ideas

- **EDIT keyword handling**: Reply EDIT to confirmation SMS — deferred to Phase 4 (with STOP/START and other keyword commands)
- **Worker acknowledgment SMS**: Brief "Got it: $200 goal. Searching jobs..." before match results — deferred to Phase 4
- **Worker no-match reply**: "No jobs match right now — check back later" — deferred to Phase 4
- **HELP keyword**: Reply HELP for examples — deferred to v1 backlog (mentioned in reply text was removed for now)
- **Datetime normalization for v2**: Full timezone-aware datetime math for relative expressions deferred to v2

</deferred>

---

*Phase: 02-gpt-extraction-service*
*Context gathered: 2026-03-07*
