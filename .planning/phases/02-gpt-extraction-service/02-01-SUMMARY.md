---
phase: 02-gpt-extraction-service
plan: 01
subsystem: api
tags: [openai, braintrust, tenacity, pydantic, structlog]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: Settings/config.py base class, structlog setup, async DB session fixture
  - phase: 01.1-apply-revised-3nf-schema-and-propagate-throughout-app
    provides: 3NF model layer; extraction module builds alongside without storage side-effects

provides:
  - ExtractionResult/JobExtraction/WorkerExtraction/UnknownMessage Pydantic schemas
  - ExtractionService with async process(sms_text, phone_hash) method
  - SYSTEM_PROMPT with 5 few-shot examples (2 job, 2 worker, 1 unknown)
  - GPT_MODEL, UNKNOWN_REPLY_TEXT, EMBEDDING_MODEL, EMBEDDING_DIMS constants
  - Full test scaffold (10 tests) for extraction unit tests
  - Phase 2 env vars in Settings (openai_api_key, pinecone_api_key, pinecone_index_host, braintrust_api_key)

affects:
  - 02-02 (storage wiring — will extend ExtractionService.process() signature with message_id and db_session)
  - 03 (Inngest pipeline — ExtractionService injected via app.state)

# Tech tracking
tech-stack:
  added:
    - openai>=1.0.0 (AsyncOpenAI, structured output via beta.chat.completions.parse)
    - braintrust>=0.0.100 (wrap_openai, init_logger for LLM observability)
    - tenacity>=8.0.0 (retry decorator with exponential backoff on RateLimitError/APIStatusError)
  patterns:
    - Pure service class — no FastAPI imports; injectable with mock clients in tests
    - Braintrust wrap_openai applied at __init__ time (module-level init_logger singleton)
    - tenacity @retry decorator on private _call_with_retry method; public process() is undecorated
    - TDD (RED → GREEN): test scaffold committed before implementation

key-files:
  created:
    - src/extraction/__init__.py
    - src/extraction/constants.py
    - src/extraction/schemas.py
    - src/extraction/prompts.py
    - src/extraction/service.py
    - tests/extraction/__init__.py
    - tests/extraction/conftest.py
    - tests/extraction/test_schemas.py
    - tests/extraction/test_service.py
  modified:
    - src/config.py (Phase 2 settings added)
    - .env.example (Phase 2 env vars documented)
    - pyproject.toml (braintrust/openai/tenacity deps added; ruff per-file-ignores for prompts.py)

key-decisions:
  - "patch target is src.extraction.service.wrap_openai (not braintrust.wrap_openai) because service.py uses a direct import"
  - "ruff E501 suppressed only for prompts.py via per-file-ignores — long lines are intentional in LLM prompt strings"
  - "ExtractionService.process() takes only sms_text + phone_hash; message_id and db_session added in Plan 02-02"
  - "Settings fields use str = '' defaults so tests without .env do not fail at import"

patterns-established:
  - "Mock OpenAI client: make_mock_openai_client(parsed_result) factory in tests/extraction/conftest.py"
  - "Patch braintrust at import site: patch('src.extraction.service.wrap_openai')"
  - "TDD: commit test scaffold first (RED ImportError), then implement (GREEN)"

requirements-completed: [EXT-01, EXT-02, EXT-03, EXT-04, OBS-01]

# Metrics
duration: 35min
completed: 2026-03-07
---

# Phase 2 Plan 01: GPT Extraction Service Summary

**ExtractionService with Braintrust-wrapped AsyncOpenAI, tenacity retry, and 5-example structured-output prompt for SMS classification into job_posting/worker_goal/unknown**

## Performance

- **Duration:** 35 min
- **Started:** 2026-03-07T20:05:54Z
- **Completed:** 2026-03-07T20:40:00Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- Pydantic schemas (ExtractionResult discriminated union with JobExtraction, WorkerExtraction, UnknownMessage) with no unsafe defaults
- ExtractionService injecting Braintrust-wrapped AsyncOpenAI, tenacity retry on rate limits (4 attempts), structured output via beta.chat.completions.parse
- SYSTEM_PROMPT with explicit field definitions and 5 few-shot examples covering all classification branches
- Full 10-test suite (5 schema, 5 service) including retry, braintrust instrumentation, and all classification paths — all passing with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Write test scaffold (Wave 0 — RED)** - `65ff552` (test)
2. **Task 2: Implement ExtractionService module — GREEN** - `b333536` (feat)

## Files Created/Modified

- `src/extraction/schemas.py` - ExtractionResult, JobExtraction, WorkerExtraction, UnknownMessage Pydantic models
- `src/extraction/constants.py` - GPT_MODEL="gpt-5.2", UNKNOWN_REPLY_TEXT, EMBEDDING_MODEL, EMBEDDING_DIMS
- `src/extraction/prompts.py` - SYSTEM_PROMPT with 5 few-shot examples
- `src/extraction/service.py` - ExtractionService: wrap_openai init, tenacity retry, async process()
- `src/config.py` - Phase 2 Settings fields (openai_api_key, pinecone_api_key, pinecone_index_host, braintrust_api_key)
- `tests/extraction/conftest.py` - make_mock_openai_client() and mock_pinecone_client() factories
- `tests/extraction/test_schemas.py` - 5 schema validation tests
- `tests/extraction/test_service.py` - 5 service unit tests
- `pyproject.toml` - dependencies added; E501 per-file-ignore for prompts.py
- `.env.example` - Phase 2 env vars documented

## Decisions Made

- Patch target for braintrust is `src.extraction.service.wrap_openai` not `braintrust.wrap_openai` — direct import means the reference lives in service module namespace.
- ruff E501 suppressed for prompts.py only via `per-file-ignores` — LLM prompt strings require long lines for readability.
- ExtractionService.process() signature kept minimal (sms_text, phone_hash) — Plan 02-02 adds message_id and db_session when storage is wired.
- Settings fields default to empty string so imports work in test environments without .env.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock patch target for braintrust.wrap_openai**
- **Found during:** Task 1 verification (GREEN run)
- **Issue:** Test scaffold patched `braintrust.wrap_openai` but service.py imports `wrap_openai` directly; patch had no effect on already-bound name
- **Fix:** Changed all patch targets to `src.extraction.service.wrap_openai`
- **Files modified:** tests/extraction/test_service.py
- **Verification:** test_braintrust_instrumentation passes; mock_wrap.assert_called_once() succeeds
- **Committed in:** b333536 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed ruff linting errors in service.py and test_service.py**
- **Found during:** Task 2 verification (ruff check)
- **Issue:** Import order violations (I001) and one unused variable (F841) flagged by ruff
- **Fix:** Applied `ruff check --fix` for auto-fixable import sorting; removed `service` assignment in test_braintrust_instrumentation
- **Files modified:** src/extraction/service.py, tests/extraction/test_service.py
- **Verification:** `ruff check src/extraction/ tests/extraction/` — All checks passed
- **Committed in:** b333536 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes necessary for correctness and lint compliance. No scope creep.

## Issues Encountered

- openai, braintrust, tenacity were not in pyproject.toml — added via `uv add` before writing any code. Package installation is a prerequisite gap, not a deviation.

## User Setup Required

External services require manual configuration:

- `OPENAI_API_KEY` — platform.openai.com -> API Keys (needed for GPT-5.2 extraction calls)
- `BRAINTRUST_API_KEY` — braintrust.dev -> Settings -> API Keys (needed for LLM observability)

Add these to `.env` before running the live pipeline. Tests mock both services and do not require real keys.

## Next Phase Readiness

- ExtractionService is complete and fully tested as a pure injectable class
- Plan 02-02 extends process() with message_id and db_session for storage side-effects
- make_mock_openai_client() and mock_pinecone_client() fixtures are already scaffolded for 02-02 tests

---
*Phase: 02-gpt-extraction-service*
*Completed: 2026-03-07*
