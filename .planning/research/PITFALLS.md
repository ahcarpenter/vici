# Pitfalls Research

**Domain:** SMS webhook + AI extraction + job matching API (Python/FastAPI)
**Researched:** 2026-03-05
**Confidence:** MEDIUM — web access unavailable; findings from training knowledge (cutoff Aug 2025). All five domains have extensive documented community experience. Flag items marked LOW for phase-specific verification.

---

## Critical Pitfalls

### Pitfall 1: Twilio Signature Validation Bypassed or Broken

**What goes wrong:**
The webhook endpoint accepts POST requests without verifying the `X-Twilio-Signature` header, allowing anyone who discovers the URL to inject fake SMS messages. Alternatively, validation is implemented but breaks silently because the URL used for HMAC computation doesn't exactly match the URL Twilio used — including protocol, port, trailing slash, or query string differences.

**Why it happens:**
Developers validate against `request.url` but forget that behind a reverse proxy (nginx, load balancer, Railway, Render) the URL seen by FastAPI is `http://internal-host/webhook` while Twilio signed against `https://yourdomain.com/webhook`. The HMAC never matches and teams either disable the check or never enable it.

**How to avoid:**
- Use the official `twilio` Python helper library's `RequestValidator.validate()` — it handles the HMAC correctly when given the right URL.
- Configure FastAPI to trust `X-Forwarded-Proto` and `X-Forwarded-Host` headers (via `ProxyHeadersMiddleware` or Uvicorn's `--proxy-headers` flag) so `request.url` reflects the public URL.
- Reconstruct the URL explicitly from config rather than from `request.url` — set `WEBHOOK_BASE_URL` as an environment variable and append the path.
- Reject requests that fail validation with HTTP 403, not 200 (returning 200 to invalid requests tells Twilio "received" for forged messages).
- Test validation in CI by replaying real Twilio test payloads with known signatures.

**Warning signs:**
- Webhook works locally but signature check always fails in staging (proxy header issue).
- Validation is commented out "temporarily" and never re-enabled.
- The WEBHOOK_BASE_URL env var doesn't exist in deployment config.

**Phase to address:** Twilio webhook foundation phase (Phase 1/2 of roadmap — infrastructure setup).

---

### Pitfall 2: Twilio Webhook Response Exceeds 15-Second Timeout

**What goes wrong:**
Twilio expects a webhook response within 15 seconds. If your handler awaits GPT completion before returning, any slow OpenAI API call (cold start, rate limit retry, long prompt) causes Twilio to retry the webhook — delivering the same SMS a second time, triggering duplicate GPT calls, and potentially creating duplicate job listings or sending duplicate SMS replies.

**Why it happens:**
The natural "happy path" implementation is: receive SMS → call GPT → store result → send reply → return 200. This works in development where GPT responds in 2-3 seconds, but fails under load or during OpenAI degradation.

**How to avoid:**
- Return HTTP 200 (empty TwiML response) to Twilio immediately upon receiving the webhook.
- Process GPT extraction and SMS reply in a background task (FastAPI `BackgroundTasks` or a task queue like Celery/ARQ).
- Implement idempotency: store the Twilio `MessageSid` before processing; if the same `MessageSid` arrives again, return 200 and skip reprocessing.
- Add a `processed_messages` table with `message_sid` as a unique key — insert before processing, catch unique constraint violations as "already processed."

**Warning signs:**
- Occasional duplicate job postings in the database from the same phone number at the same timestamp.
- Logs showing the same `MessageSid` processed twice.
- Workers or job posters reporting they received two confirmation SMS messages.
- GPT API p99 latency approaching 10+ seconds.

**Phase to address:** Twilio webhook foundation phase — idempotency must be designed in from the first working endpoint, not retrofitted.

---

### Pitfall 3: Phone Number Recycling Breaks Identity

**What goes wrong:**
Phone numbers as identity means that when a carrier reassigns a previously-used number to a new person, that new person inherits the old user's job history, postings, and matches. This is not a theoretical concern — US carriers recycle numbers aggressively, with recycling windows as short as 45 days for prepaid numbers.

**Why it happens:**
"Phone number = user" feels natural because SMS requires a phone number. Developers skip the identity layer entirely because it's out of scope, not realizing that the number-recycling problem can silently corrupt data from day one.

**How to avoid:**
- Store a `created_at` timestamp on every user record. When processing an inbound message, check if the number has been inactive for more than 90 days — if so, treat as a potential new user and either create a new record or prompt for confirmation ("Are you a new user? Reply YES to start fresh").
- Keep job postings and worker goals soft-linked to user records (foreign key), not directly to phone numbers, so a future identity migration is possible.
- Log the carrier lookup result (Twilio Lookup API can return line type and portability info) for forensics even if you don't act on it in v1.

**Warning signs:**
- A user contacts support saying they received match results for jobs they never posted.
- A new worker receives a "welcome back" message on their first text.
- Sudden change in posting behavior from a long-dormant phone number.

**Phase to address:** Schema design phase — the `users` table must have `created_at` and a soft-delete/reactivation path from the start.

---

### Pitfall 4: GPT Hallucinating Structured Fields

**What goes wrong:**
GPT returns a JSON object where fields appear populated but contain fabricated values. For job extraction, this means a pay rate field might be filled with a plausible number even when the original SMS contained no pay information. A worker then receives matches with incorrect earnings estimates.

**Why it happens:**
GPT is trained to be helpful and will infer or confabulate values rather than return null/absent. Prompts that say "extract pay rate" without explicitly instructing "return null if not mentioned" get filled values. JSON mode (vs. structured outputs) is especially prone because it only enforces valid JSON, not schema constraints.

**How to avoid:**
- Use OpenAI structured outputs (response_format with JSON schema) rather than JSON mode — structured outputs enforce schema shape.
- Make every optional field explicitly nullable in the schema with an instruction like "set to null if not present in the message."
- Add a `confidence` field per extracted field where GPT self-reports certainty — treat confidence below threshold as null.
- For the pay rate field specifically: if extracted value is non-null but no currency/rate language exists in the original SMS text, flag for human review or discard.
- Validate extracted data against business rules: pay rate must be a positive number, timeframe must parse to a valid duration.
- In the confirmation SMS sent to job posters, show the extracted values explicitly so humans catch hallucinations: "I understood: $25/hr, 3 hours, downtown. Reply EDIT to correct."

**Warning signs:**
- Extracted `pay_rate` fields are always populated even for vague SMS messages.
- Job postings in the database that look complete but the original SMS was one sentence with no numbers.
- Workers report receiving match results with pay rates that don't match what posters intended.

**Phase to address:** GPT extraction service phase — schema design and prompt engineering must be done together with validation logic.

---

### Pitfall 5: Skipping the Two-Step Classify-then-Extract Split

**What goes wrong:**
The PROJECT.md states "GPT classifies + extracts in same call." This is a reasonable optimization but introduces a failure mode: if the classifier is wrong, the extractor extracts the wrong schema, and downstream routing sends a job posting to the worker-goal path or vice versa. Because it's a single call, there's no checkpoint to catch the misclassification.

**Why it happens:**
Combining classification and extraction reduces latency and cost. The risk is accepted implicitly rather than managed explicitly.

**How to avoid:**
- Even in a single-call design, the response schema must include a `message_type` field ("job_posting" | "worker_goal" | "unknown") that is validated before extraction fields are used.
- Add an `unknown` / ambiguous category: if GPT isn't sure, send the user a clarifying SMS ("Were you posting a job or looking for work? Reply JOB or WORK").
- Log the raw GPT response alongside the parsed result so misclassifications can be reviewed.
- Write unit tests with edge cases: short messages, messages that could be either type, messages in languages other than English.

**Warning signs:**
- Job posters receive worker-side confirmation messages ("Your earnings goal of...").
- Workers receive job poster confirmation messages.
- High rate of SMS replies that look like "unknown" or fallback paths.

**Phase to address:** GPT extraction service phase — classification logic must be the first thing tested before extraction logic is built.

---

### Pitfall 6: FastAPI Sync Database Calls Inside Async Handlers

**What goes wrong:**
SQLAlchemy's standard (synchronous) session is called from an `async def` endpoint handler. This doesn't immediately crash — it works — but it blocks the event loop on every database call, destroying FastAPI's concurrency benefits. Under any load, all requests queue behind the slowest DB query.

**Why it happens:**
Most SQLAlchemy tutorials still use synchronous patterns. Async SQLAlchemy (`asyncpg` driver, `AsyncSession`) has different syntax and setup. Developers copy synchronous examples into async handlers without realizing the mismatch.

**How to avoid:**
- Use `sqlalchemy[asyncio]` with `asyncpg` driver from day one: `create_async_engine`, `AsyncSession`, `async_sessionmaker`.
- Never use `session.execute()` without `await` in an async handler.
- Use `run_in_executor` only as a last resort for truly unavoidable synchronous calls.
- Database session dependency must be `async def get_db()` yielding an `AsyncSession`.
- Test with multiple concurrent requests early — synchronous blocking shows up immediately under light concurrent load.

**Warning signs:**
- Response times that scale linearly with concurrent requests rather than staying flat.
- Event loop blocking warnings in uvicorn logs.
- Database queries that run fast individually but slow drastically under concurrency.

**Phase to address:** FastAPI infrastructure phase — async database setup must be the foundation, not a refactor item.

---

### Pitfall 7: pgvector Index Not Created Before Production Load

**What goes wrong:**
pgvector without an index does exact nearest-neighbor search (sequential scan over all rows). For the first few hundred job postings this is imperceptible. At a few thousand rows, job-matching queries become noticeably slow. At tens of thousands, the endpoint times out.

**Why it happens:**
pgvector is included in the schema from day one (correctly), but the index creation is deferred because "we don't need semantic search yet." The earnings-math matching query triggers a pgvector distance scan anyway if embeddings are part of a future ORDER BY, and the index doesn't exist.

**How to avoid:**
- Create the `ivfflat` or `hnsw` index in the initial migration, even if it's not used yet: `CREATE INDEX ON job_postings USING hnsw (embedding vector_cosine_ops)`.
- Use `hnsw` over `ivfflat` for this use case: HNSW doesn't require knowing the number of lists upfront and handles incremental inserts better (IVFFlat requires rebuilding the index after significant data growth).
- Add a migration test that verifies the index exists.

**Warning signs:**
- `EXPLAIN ANALYZE` on job queries shows `Seq Scan` on the embeddings column.
- Query time grows linearly with row count.
- pgvector was added to the schema but no corresponding index migration exists.

**Phase to address:** Schema/database foundation phase — index must be in the initial migration.

---

### Pitfall 8: No Rate Limiting on the Webhook Endpoint

**What goes wrong:**
A single phone number (or someone who has discovered the webhook URL) floods the endpoint with thousands of SMS events or forged requests. Each request triggers a GPT API call (cost) and a database write. A sustained attack burns through OpenAI credits and creates tens of thousands of bogus job postings before anyone notices.

**Why it happens:**
Signature validation is treated as sufficient protection. But a valid sender (a real Twilio number) can legitimately send thousands of messages. Rate limiting at the application level is often skipped as "premature optimization."

**How to avoid:**
- Rate limit by `From` phone number: max N messages per minute per number (5-10 is reasonable for SMS humans, 100 is reasonable for automation).
- Use a simple Redis counter or in-memory counter with TTL for rate limiting — no need for complex infrastructure.
- Return TwiML with an error message to rate-limited numbers: "Too many messages. Please wait before trying again."
- Set a hard budget cap in the OpenAI API settings (spend limit) as a backstop.
- Alert on anomalous GPT spend spikes.

**Warning signs:**
- A single phone number appearing dozens of times in the `messages` log within a minute.
- OpenAI API costs spiking unexpectedly.
- Database row count growing at an implausible rate.

**Phase to address:** Twilio webhook foundation phase — rate limiting must be co-located with the endpoint, not a later addition.

---

### Pitfall 9: Earnings Math Matching Without Handling Missing/Zero Values

**What goes wrong:**
The core matching logic is `rate * duration >= worker_goal`. If `duration` is null (poster didn't specify) or `rate` is null (poster didn't specify pay), the SQL comparison silently returns no matches or includes all jobs (depending on how NULL arithmetic is handled). Workers receive empty result sets or inappropriate matches with no indication of why.

**Why it happens:**
The happy path test always uses complete job postings. Edge cases with missing fields aren't tested until real users post incomplete jobs — which happens immediately.

**How to avoid:**
- Define explicit null-handling policy before writing matching SQL: null duration means "unknown" (include in results with a caveat), null rate means "exclude from matches" (can't compute earnings).
- In SQL: `NULLIF(rate, 0) * NULLIF(estimated_hours, 0) >= worker_goal` won't behave intuitively — be explicit with `CASE WHEN rate IS NULL THEN FALSE ELSE ...`.
- In the confirmation SMS to job posters, explicitly request any missing fields: "I didn't catch an hourly rate — can you reply with the pay rate?"
- Write tests for: null rate, null duration, zero rate, zero duration, worker goal of zero.

**Warning signs:**
- Workers with valid goals receiving empty match lists despite available jobs.
- Jobs with null rates appearing in match results.
- SQL query returns unexpectedly large result sets when tested with incomplete data.

**Phase to address:** Job matching logic phase — matching SQL must be written with explicit null handling, tested against incomplete data.

---

### Pitfall 10: Storing Raw GPT Responses Without Audit Trail

**What goes wrong:**
When a job poster disputes what was extracted from their SMS ("that's not what I said"), there's no way to reconstruct what happened. The raw SMS text and the original GPT response are not stored — only the parsed structured data. Debugging misclassifications, hallucinations, or extraction errors is impossible.

**Why it happens:**
Storing raw responses feels like unnecessary storage overhead. Teams store only the "useful" output.

**How to avoid:**
- Store the raw inbound SMS body in a `raw_messages` table linked to the processing result.
- Store the raw GPT response (the full JSON before parsing) alongside the parsed result.
- Store the `MessageSid` from Twilio in the raw message record.
- This is cheap storage: SMS messages are tiny, GPT JSON responses are kilobytes.
- Retention policy can be set later — having the data is always better than not.

**Warning signs:**
- A bug report arrives that can't be reproduced because the original message wasn't stored.
- The confirmation SMS sent to a job poster doesn't match what they texted, but there's no way to know what GPT extracted.

**Phase to address:** Schema/database foundation phase — raw message logging belongs in the initial schema.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip signature validation in dev | Easier local testing with curl | Forgotten in production, creates permanent security hole | Never — use a flag like `SKIP_TWILIO_VALIDATION=true` only in local dev, enforced off in production |
| Synchronous SQLAlchemy in async FastAPI | Faster initial setup, familiar syntax | Blocks event loop, requires full refactor under load | Never for a new project — the async setup cost is ~30 minutes |
| JSON mode instead of structured outputs | Simpler prompt | Hallucinated field values, no schema enforcement | Never for extraction pipelines — structured outputs cost the same |
| No idempotency on webhook | Simpler handler code | Duplicate job postings, duplicate SMS messages under load or retry | Never — Twilio retries are guaranteed to happen |
| ivfflat over hnsw index | Marginally faster index creation | Must rebuild index after significant data growth; requires VACUUM | Only if you know dataset size will be static and small |
| In-memory rate limiting (no Redis) | No Redis dependency | Rate limits reset on process restart, don't work across multiple workers | Acceptable for MVP single-process deployment; must change with horizontal scale |
| Hardcoded phone number format assumptions | Simpler parsing | Breaks when international numbers arrive or Twilio normalizes differently | Never — always use E.164 format from Twilio's `From` field as-is |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Twilio signature validation | Validate against `request.url` which reflects internal proxy URL | Set `WEBHOOK_BASE_URL` env var; reconstruct URL from config; enable Uvicorn `--proxy-headers` |
| Twilio TwiML response | Return JSON `{"status": "ok"}` instead of TwiML | Return `<Response></Response>` or `application/json` with status 200 — Twilio ignores non-TwiML body but logs warnings |
| Twilio reply timing | Send SMS reply inside the webhook handler before returning | Use `BackgroundTasks` — return 200 to Twilio immediately, send reply asynchronously |
| OpenAI structured outputs | Use `response_format={"type": "json_object"}` (JSON mode) | Use `response_format` with a full JSON schema via the `json_schema` type for enforcement |
| OpenAI token limits | Not accounting for the full context: system prompt + message + JSON schema | Calculate token budget: schema alone can be 500-1000 tokens; SMS is small but system prompt adds up |
| asyncpg + SQLAlchemy | Using `psycopg2` connection string with async engine | Use `postgresql+asyncpg://` DSN; asyncpg is a separate driver with different parameter syntax |
| pgvector extension | Forgetting `CREATE EXTENSION IF NOT EXISTS vector` in migration | Include extension creation in the first Alembic migration; check it exists in health endpoint |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| No pgvector index | Job match queries slow, increasing linearly with table size | Create HNSW index in initial migration | ~1,000 rows with no index; ~100,000 rows with IVFFlat if not tuned |
| Calling OpenAI synchronously in async handler | Request queue backs up; p99 latency = GPT latency | Always use `await openai.chat.completions.create()` with async client | Immediately under any concurrent load (2+ simultaneous SMS) |
| Fetching all matching jobs then filtering in Python | Memory spikes, slow at scale | Push filtering logic into SQL WHERE clause | ~10,000 job postings |
| N+1 queries in job result formatting | Each job requires a separate query to fetch poster info | Use SQL JOINs or `selectinload` in SQLAlchemy | ~50 results returned |
| No connection pooling | New DB connection per request; connection exhaustion | Use `asyncpg` pool via SQLAlchemy `pool_size`, `max_overflow` | ~20 concurrent requests |
| Embedding generation in the webhook handler | Adds 200-500ms to every job posting request | Generate embeddings in background task | Immediately if embedding is on request path |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Missing Twilio signature validation | Anyone can forge SMS messages; arbitrary job postings, data corruption | Implement `RequestValidator` in middleware, return 403 on failure, test in CI |
| Phone number spoofing via SMS | Attacker spoofs a known job poster's number to modify or create jobs | Twilio signature validation catches forged webhook calls; SMS spoofing bypasses Twilio entirely only if attacker controls the carrier path — accept this limitation in v1 |
| Number recycling identity theft | New owner of a recycled number accesses previous user's data | Inactivity check: if number unseen for 90+ days, prompt for re-confirmation before granting access to historical data |
| OpenAI API key in version control | Full API access exposed; runaway spend | Use environment variables; add `.env` to `.gitignore`; use a secret manager in production; set OpenAI spend limits |
| Unvalidated phone numbers stored as-is | Malformed phone numbers used as DB keys cause lookup mismatches | Always normalize to E.164 format (Twilio's `From` field is already E.164); validate format before storing |
| GPT prompt injection via SMS | User texts a malicious SMS that hijacks the extraction prompt | Use system prompt isolation; treat SMS body as untrusted user content, never interpolate it into system instructions; structured outputs help contain extraction scope |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Confirmation SMS shows only "received" | Job posters don't know what was extracted; can't catch hallucinations | Confirmation SMS must repeat extracted values: "Got it! Job: lawn mowing, $20/hr, 2 hrs, 2026-03-10. Reply EDIT to correct." |
| Empty match list with no explanation | Worker texts goal, receives silence or empty list; doesn't know if system worked | Reply with "No jobs match $X goal yet. We'll text you when one appears" — not silence |
| SMS truncation (160 char limit) | Long job match lists get truncated by carrier, splitting mid-result | Cap match results at 3-5, keep each entry under 50 chars; use concatenated SMS (Twilio handles splitting) but keep content short |
| Ambiguous extraction field in confirmation | "3 hours" vs "3 days" — duration ambiguity is common | Confirm with explicit unit: "Duration: 3 hours (not days). Reply EDIT to correct." |
| No fallback for unrecognized message | User texts something unclassifiable; system is silent | Always reply: "I didn't understand that. Text your job details OR your earnings goal to get started." |

---

## "Looks Done But Isn't" Checklist

- [ ] **Twilio signature validation:** Often missing in the "fast first deployment" — verify by sending a request with an invalid signature and confirming HTTP 403 is returned.
- [ ] **Idempotency on webhook:** Looks done when the handler runs once in dev — verify by replaying the same `MessageSid` twice and confirming only one DB record is created.
- [ ] **Async database session:** Looks done when queries return results — verify with a concurrency test (10 simultaneous requests) and check event loop blocking warnings.
- [ ] **pgvector HNSW index:** Looks done when `CREATE EXTENSION vector` is in migrations — verify `\d job_postings` shows an index on the embedding column.
- [ ] **Null handling in earnings math:** Looks done when test jobs with complete data match — verify with a job that has null `rate` and null `estimated_hours`.
- [ ] **Rate limiting:** Looks done when the endpoint returns 200 — verify by sending 20 messages from the same number in 10 seconds and confirming throttling kicks in.
- [ ] **Raw message logging:** Looks done when the `jobs` table is populated — verify a separate `raw_messages` table exists with the original SMS body and GPT response.
- [ ] **GPT structured output (not JSON mode):** Looks done when JSON is returned — verify the API call uses `response_format` with a JSON schema, not `{"type": "json_object"}`.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Signature validation never implemented | MEDIUM | Add middleware; test in staging; no data loss but emergency deploy required |
| Duplicate records from missing idempotency | HIGH | Deduplicate records by (phone, created_at, content hash); notify affected users; add idempotency in emergency deploy |
| Sync DB blocking event loop | HIGH | Full refactor to async SQLAlchemy; all queries must be audited; requires significant regression testing |
| pgvector index missing at scale | LOW-MEDIUM | `CREATE INDEX CONCURRENTLY` — can be done online without downtime but takes time on large tables |
| GPT hallucinated pay rates in live data | MEDIUM | Audit all jobs where rate was extracted but source SMS had no numeric content; soft-delete suspect records; add validation retroactively |
| Phone number recycled, wrong user gets data | MEDIUM | Hard to detect retroactively; add inactivity check going forward; communicate to affected users if detected |
| No raw message audit trail | HIGH | Data is gone; no recovery possible — only prevention |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Missing Twilio signature validation | Phase 1: Webhook infrastructure | Send invalid signature; confirm 403 |
| Webhook timeout / duplicate delivery | Phase 1: Webhook infrastructure | Replay same MessageSid; confirm single DB record; mock slow GPT |
| Phone number recycling | Phase 1: Schema design | `users` table has `created_at`, inactivity threshold check in user lookup |
| GPT hallucinating fields | Phase 2: GPT extraction service | Feed SMS with no numeric content; confirm `rate` field is null |
| Missing classification checkpoint | Phase 2: GPT extraction service | Feed ambiguous SMS; confirm `message_type` is validated before extraction fields used |
| Sync DB in async handler | Phase 1: FastAPI infrastructure | Concurrency test with 10 simultaneous requests; no event loop warnings |
| pgvector index missing | Phase 1: Schema design | `\d job_postings` shows HNSW index in migration; EXPLAIN ANALYZE shows index scan |
| No rate limiting | Phase 1: Webhook infrastructure | 20 messages/10s from same number triggers throttle |
| Null handling in earnings math | Phase 3: Job matching logic | Query with null-rate jobs; confirm excluded from results |
| No raw message audit trail | Phase 1: Schema design | `raw_messages` table exists; every processed message has a corresponding raw record |

---

## Sources

- Twilio webhook security documentation (official): https://www.twilio.com/docs/usage/security — signature validation using HMAC-SHA1 with auth token; URL must be exact match. **HIGH confidence** (well-documented official requirement).
- OpenAI structured outputs vs JSON mode: Official OpenAI platform documentation distinguishes schema-enforced structured outputs from JSON mode. **HIGH confidence** (released and documented through training cutoff).
- pgvector HNSW index recommendation: pgvector README recommends HNSW over IVFFlat for most use cases due to better incremental insert handling. **HIGH confidence** (documented in pgvector GitHub README).
- FastAPI async SQLAlchemy: SQLAlchemy async documentation (`sqlalchemy[asyncio]`, `asyncpg`). **HIGH confidence** (documented pattern, core FastAPI/SQLAlchemy ecosystem).
- Twilio 15-second webhook timeout: Documented in Twilio's webhook best practices. **HIGH confidence** (core Twilio operational requirement).
- Phone number recycling: FCC-documented practice; US carriers required to retire numbers for 45+ days before reassignment (NANP guidelines). **HIGH confidence**.
- GPT prompt injection risk: OWASP LLM Top 10, extensively documented. **MEDIUM confidence** — specific behavior depends on model version.
- Rate limiting and OpenAI spend: OpenAI spend limits are configurable in the dashboard. **HIGH confidence**.

*Note: Web access was unavailable during this research session. All findings are from training knowledge (cutoff Aug 2025). Findings marked HIGH confidence reflect well-established, officially-documented behaviors that are unlikely to have changed. Recommend verifying LOW/MEDIUM items during phase-specific research.*

---
*Pitfalls research for: SMS webhook + AI extraction + PostgreSQL job matching API (Vici)*
*Researched: 2026-03-05*
