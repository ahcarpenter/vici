# Feature Research

**Domain:** SMS-based job matching API (gig economy / labor marketplace via Twilio)
**Researched:** 2026-03-08
**Confidence:** HIGH — derived from the actual built system (Phases 01–02.5 complete). Source: REQUIREMENTS.md traceability table, STATE.md, PROJECT.md.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features the system must have or the core loop breaks entirely.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Twilio X-Twilio-Signature validation | Every inbound Twilio webhook can be spoofed without this; Twilio docs require it as the baseline security layer | MEDIUM | ✅ Implemented (SEC-01). Must validate HMAC-SHA1 of URL + sorted POST params against Auth Token. FastAPI complicates this because you need the raw body before it is parsed — use `Request.body()` with a custom dependency, not Pydantic directly. HIGH confidence (Twilio security model well-documented). |
| Single-endpoint message classification (job post vs. worker goal) | The entire routing model depends on correctly labeling each inbound message before any downstream action | HIGH | ✅ Implemented (EXT-01). gpt-5.3-chat-latest does classification + extraction in one call per PROJECT.md. Prompt engineering for reliable JSON output is the hard part. Must handle ambiguous messages gracefully (ask for clarification). |
| Structured data extraction from free-text SMS | Workers and job posters use natural language; the system must derive structured fields (rate, duration, location, timeframe) to do any matching | HIGH | ✅ Implemented (EXT-02, EXT-03). LLM extraction — define strict output schema with Pydantic, instruct model to return null fields rather than hallucinate. Test with adversarial SMS samples. |
| Phone number as identity (auto-registration) | No app install, no signup form — the first text from a number creates the record. Users expect frictionless entry | LOW | ✅ Implemented (IDN-01, IDN-02). Extract `From` field from Twilio payload. Store phone numbers normalized to E.164 format (+1XXXXXXXXXX). First-seen creates user row; subsequent messages update last-seen timestamp. HIGH confidence (standard Twilio pattern). |
| SMS confirmation reply to job poster | Job poster needs to know what the system recorded — errors in extraction should surface here so they can correct | LOW | ⏳ Pending Phase 4 (STR-03). Unknown-branch graceful reply is ✅ Implemented (EXT-04). Full confirmation SMS pending. TwiML `<Response><Message>` with extracted fields summarized in plain English. Must fit in 160 chars or clearly chain into multi-part SMS. |
| Ranked job list reply to worker | This is the core value delivery — worker gets an ordered list of jobs that hits their earnings goal | MEDIUM | ⏳ Pending Phase 3 (MATCH-01, MATCH-02). Sort by: (1) earnings math satisfied, (2) soonest available, (3) shortest duration. Must be legible in SMS format. Consider condensed job format (e.g., "1. $25/hr, 4hr shift, Tue 9am, 2mi away"). |
| Idempotency on webhook retries | Twilio retries failed webhooks (up to 11 attempts with exponential backoff). Processing the same message twice creates duplicate job posts or double-sends | MEDIUM | ✅ Implemented (SEC-02). Deduplicate on `MessageSid` (Twilio's unique per-message ID). Store `MessageSid` in a processed-messages table with a unique constraint. On duplicate, return HTTP 200 immediately without reprocessing. HIGH confidence (Twilio retry behavior is documented and consistent). |
| Synchronous HTTP 200 within 10 seconds | Twilio marks a webhook delivery as failed if it does not receive HTTP 200 (or 204) within 15 seconds (often faster in practice). A timeout triggers a retry | HIGH | ✅ Resolved via Inngest (ASYNC-01). Webhook returns HTTP 200 immediately after event emit; all processing in Inngest function outside Twilio's response window. The GPT call is the primary latency risk. Options: (a) respond 200 immediately and process async, then send SMS proactively via Twilio REST API; (b) optimize prompt to reduce latency. Async approach decouples webhook response from processing but requires a background worker or task queue. This is the most architecturally significant constraint. |
| Graceful handling of malformed / unclassifiable SMS | Users will text garbage, test messages, replies to system SMS, opt-out keywords, etc. | MEDIUM | ✅ Implemented (EXT-04). Define a fallback response for unclassifiable messages ("Sorry, I didn't understand that. Text your earnings goal like: 'I want to make $200 today'"). Distinguish from Twilio system keywords (STOP, HELP, START) which must never be intercepted. |
| Rate limiting per phone number | Bad actors (or bugs) can hammer the endpoint. Unconstrained calls = runaway GPT + Twilio costs | MEDIUM | ✅ Implemented (SEC-03). PostgreSQL-backed TTL counters (no Redis). Limit inbound processing per phone number (e.g., max 10 messages/hour). Return a polite SMS if limit hit. Implement at the application layer before GPT is called. |
| HTTPS-only endpoint | Twilio refuses to send webhooks to non-HTTPS URLs in production | LOW | ✅ Infrastructure — Render.com provides TLS. Infrastructure concern, not app code. Twilio validates the certificate. |
| Webhook returns valid TwiML | Twilio expects a TwiML XML response (or empty 200/204). Malformed responses cause delivery failures | LOW | ✅ Resolved differently — webhook returns HTTP 200 (not TwiML); Twilio is satisfied by HTTP 200. The Twilio Python library is used only for outbound SMS and signature validation, not for generating TwiML responses. |

### Differentiators (Competitive Advantage)

Features that go beyond baseline and deliver the core value proposition better.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Earnings math matching (rate x duration >= goal) | Deterministic, user-testable answer to "can I hit my goal?" — most job platforms show hourly rate only, leaving math to the worker | MEDIUM | Core to Vici's value. Must handle: hourly rate (rate x est_duration), flat-pay jobs (pay >= goal), and jobs where duration is unknown (flag as unverifiable). The matching predicate must be transparent enough for workers to understand why they got the results they did. |
| Ranked by shortest time to goal | Workers want to earn $X as fast as possible — sorting by soonest/shortest is the key UX insight | LOW | Secondary sort after earnings math gate. Tiebreak: soonest start > shortest shift. |
| Confirmation flow with correction path | Job poster gets a summary and can reply "wrong" or "fix pay $30/hr" to trigger a correction without resubmitting everything | HIGH | Requires session/conversation state keyed on phone number + recency window. Parser must handle correction commands. Defer to v1.x — correction by resubmitting is acceptable for MVP. |
| Semantic job matching | Workers who text vague goals ("something easy nearby") get semantically matched jobs, not just earnings-math matches | HIGH | Pinecone embedding write implemented (VEC-01). Semantic matching is a v2 feature. Avoids costly schema migrations later. |
| Structured extraction with field-level confidence | LLM returns a confidence score per extracted field; low-confidence fields prompt a clarification SMS rather than silently guessing | HIGH | Requires prompt engineering and handling partial extractions. Significantly improves data quality but adds a conversational turn. High value, medium effort — target v1.x. |
| Time-of-send context inference | "Tomorrow morning" is resolved against the message send timestamp to produce an absolute datetime | MEDIUM | Pass `DateSent` from Twilio payload to the extraction prompt. Instruct GPT to resolve relative time expressions. Store both raw text and resolved datetime. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Async webhook response (respond 200, process later) | Avoids Twilio timeout; enables longer GPT calls | Inngest IS the implemented async pattern. FastAPI BackgroundTasks (the original anti-feature concern) is correctly avoided — Inngest provides better retry, observability, and failure handling than BackgroundTasks. | Inngest event-driven processing — ✅ Implemented (ASYNC-01, ASYNC-03). Return HTTP 200 after event emit; all heavy work in Inngest process-message function. |
| Opt-in / opt-out user management (beyond STOP/START) | Users want to pause notifications or limit job types | STOP/START are mandatory Twilio compliance keywords — handle correctly (pass through, never intercept). Additional opt-out schemes add state management and edge cases before core value is proven. | Honor STOP/START natively (Twilio handles STOP at carrier level). Build custom opt-out only if user research shows demand. |
| Multi-turn conversation / dialog management | "Natural" back-and-forth feels more human | Without a session store and state machine, each message is independently classified. Dialog management is a substantial feature — it couples classification to history and makes the system stateful in ways that are hard to test and debug. | For MVP: stateless per-message classification with clear instructions in the SMS prompt. Add conversation state in v2 only if correction flows prove necessary. |
| Web dashboard for job posters | Posters want to see all their listings | The whole value proposition is no-app. A web UI adds auth, frontend, and a second interaction surface before SMS is validated. | API-only for MVP. Surface job listing data via SMS query commands (e.g., text "MY JOBS" to list active postings). Add dashboard only after SMS channel is validated. |
| Payment processing integration | End-to-end gig platform | Payment adds compliance (PCI), legal (1099/W-2 classification), and significant product complexity. | Rate/pay is informational in v1. Workers and posters handle payment out-of-band. Revisit after product-market fit. |
| Multiple inbound phone numbers | Support different numbers for different job categories | Complicates Twilio configuration and requires routing logic before classification. No user benefit in v1. | Single inbound number; classification handles category assignment. |
| Phone number verification (OTP) | Prevent spoofing | Twilio already validates that the `From` number is a real, reachable number for SMS. Additional OTP adds a two-message onboarding flow that defeats the zero-friction pitch. | Trust Twilio's carrier-level From validation. Add verification only if abuse patterns emerge in production. |

---

## Feature Dependencies

```
[Twilio Signature Validation]
    └──required by──> [Webhook Endpoint] (security gate before any processing)

[Phone Number as Identity]
    └──required by──> [Message Classification]
                          └──required by──> [Job Extraction]
                          └──required by──> [Worker Goal Extraction]

[Job Extraction]
    └──required by──> [Earnings Math Matching]
                          └──required by──> [Ranked Job Reply]

[Worker Goal Extraction]
    └──required by──> [Earnings Math Matching]

[Idempotency (MessageSid dedup)]
    └──required by──> [Webhook Endpoint] (must check before classification)

[Rate Limiting]
    └──required by──> [Webhook Endpoint] (must check before GPT call)

[HTTP 200 within timeout]
    └──constrains──> [Message Classification] (GPT call must complete within budget)

[Pinecone embedding write]
    └──enhances (v2)──> [Earnings Math Matching] (semantic search, if added later)

[Confirmation SMS to poster]
    └──enhances (v1.x)──> [Correction Flow] (requires conversation state)

[Inngest process-message]
    └──required by──> [Earnings Math Matching]
    └──required by──> [SMS reply flows]
```

### Dependency Notes

- **Twilio Signature Validation required before any processing:** An unvalidated webhook can be spoofed to inject arbitrary job listings or spam workers. This must be the first middleware layer — before rate limiting, before classification.
- **Idempotency check required before GPT call:** Twilio retries create duplicate processing. The MessageSid check must happen before the expensive GPT call, not after.
- **Rate limiting required before GPT call:** Same reason — reject rate-limited requests before incurring AI costs.
- **HTTP 200 timeout constrains classification:** The GPT call budget is approximately 8-10 seconds. If this proves insufficient, the async response pattern (anti-feature above) must be revisited, which cascades into needing a task queue.
- **Pinecone embedding enhances matching (future):** Pinecone writes are implemented (VEC-01). Semantic search is a v2 feature.

---

## MVP Definition

### Launch With (v1)

- ✅ **Twilio X-Twilio-Signature validation** (SEC-01)
- ✅ **MessageSid idempotency** (SEC-02)
- ✅ **Rate limiting per phone number** (SEC-03, PostgreSQL-backed)
- ✅ **Phone number as identity (auto-registration)** (IDN-01, IDN-02)
- ✅ **Single-endpoint GPT classification** (EXT-01)
- ✅ **Structured extraction: job fields** (EXT-02 — description, ideal_datetime, flexibility, estimated_duration, location, pay_rate)
- ✅ **Structured extraction: worker goal** (EXT-03 — target_earnings, target_timeframe)
- ✅ **Graceful fallback for unclassifiable messages** (EXT-04 — SMS reply via asyncio.to_thread)
- ⏳ **Earnings math matching** (MATCH-01 — Phase 3)
- ⏳ **SMS confirmation reply to job poster** (STR-03 — Phase 4; graceful unknown reply ✅ done)
- ⏳ **SMS ranked job list reply to worker** (MATCH-02, MATCH-03 — Phase 3)
- ⏳ **STOP/START keyword pass-through** (SEC-05 — Phase 4)
- ✅ **HTTP response within timeout budget** (ASYNC-01 — Inngest event-driven; returns HTTP 200 immediately)

### Add After Validation (v1.x)

- [ ] **Field-level confidence + clarification prompts** — Add when extraction quality data shows which fields are frequently wrong
- [ ] **Time-of-send context inference** — Add when users report confusion from relative time expressions
- [ ] **Correction flow via reply** — Add when posters report correcting bad extractions by resubmitting full messages (friction signal)
- [ ] **SMS query commands** ("MY JOBS", "CANCEL JOB 2") — Add when posters need to manage listings without reposting

### Future Consideration (v2+)

- [ ] **Semantic matching** — Defer until earnings-math matching is validated and vague query patterns emerge (Pinecone embedding write already implemented, VEC-01)
- [ ] **Web dashboard** — Defer until SMS channel is validated and operator tooling needs emerge
- [ ] **Multi-turn conversation state** — Defer unless correction flow proves insufficient

---

## Phase 3: Earnings Math Matching (Next Phase)

**Requirements:** MATCH-01, MATCH-02, MATCH-03

### What Will Be Implemented

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| MATCH-01 | Earnings math SQL query | `JobRepository.find_matching()` — `WHERE pay_rate IS NOT NULL AND estimated_duration IS NOT NULL AND pay_rate * estimated_duration >= :target_earnings ORDER BY ideal_datetime ASC NULLS LAST, estimated_duration ASC NULLS LAST LIMIT 5` |
| MATCH-02 | Ranked SMS formatter | `MatchService.format_sms()` — condensed format: `1. $25/hr 3hr Tue 9am downtown`, 3–5 results, 160-char segment awareness |
| MATCH-03 | Empty match fallback | `"No jobs match your $X goal yet. We'll text you when one is posted."` |

**New module:** `src/matches/service.py` — MatchService. Placeholder `src/matches/` directory already exists with Match SQLModel stub.

**Integration point:** PipelineOrchestrator WorkRequest branch — after `WorkRequestRepository.create()` flush and `session.commit()`, call `MatchService.find_and_format()`, send result via `asyncio.to_thread(twilio_client.messages.create)`.

**NULL handling policy:** jobs with NULL `pay_rate` or NULL `estimated_duration` are excluded from match results (can't verify earnings goal).

---

## Phase 4: Outbound SMS + Production Deploy

**Requirements:** STR-03, SEC-05, DEP-03

### What Will Be Implemented

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| STR-03 | Job poster confirmation SMS | Outbound SMS in PipelineOrchestrator job branch (after Pinecone write). Format: "Got it: $25/hr, 3hr, downtown. Reply again to update." via asyncio.to_thread. |
| SEC-05 | STOP/START pass-through | Classify STOP/START keywords in Inngest process-message function before GPT call — never attempt processing or outbound SMS to STOP-registered number |
| DEP-03 | Render.com production deploy | render.yaml Blueprint exists (PROD-04 complete). First deploy validates: /health returns 200, Inngest Cloud connectivity, Pinecone write, Twilio sig validation with production URL. |

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Twilio signature validation | HIGH | MEDIUM | P1 (✅ done) |
| MessageSid idempotency | HIGH | LOW | P1 (✅ done) |
| Rate limiting per phone | HIGH | MEDIUM | P1 (✅ done) |
| Phone number as identity | HIGH | LOW | P1 (✅ done) |
| Message classification (GPT) | HIGH | HIGH | P1 (✅ done) |
| Job field extraction | HIGH | HIGH | P1 (✅ done) |
| Worker goal extraction | HIGH | MEDIUM | P1 (✅ done) |
| Earnings math matching | HIGH | MEDIUM | P1 (⏳ Phase 3) |
| Confirmation SMS to poster | HIGH | LOW | P1 (⏳ Phase 4) |
| Ranked job list SMS to worker | HIGH | LOW | P1 (⏳ Phase 3) |
| STOP/START pass-through | HIGH | LOW | P1 (⏳ Phase 4) |
| Graceful malformed-message handling | MEDIUM | MEDIUM | P1 (✅ done) |
| Time-of-send inference | MEDIUM | MEDIUM | P2 |
| Field-level confidence + clarification | HIGH | HIGH | P2 |
| Correction flow via reply | MEDIUM | HIGH | P2 |
| SMS query commands | MEDIUM | MEDIUM | P2 |
| Semantic matching (Pinecone) | HIGH | HIGH | P3 |
| Web dashboard | LOW | HIGH | P3 |

---

## Competitor Feature Analysis

Note: True SMS-only job marketplace competitors are rare. Comparison draws from adjacent patterns.

| Feature | Snagajob / Indeed (app-based) | Wonolo / Instawork (app-based gig) | Vici (our approach) |
|---------|-------------------------------|-------------------------------------|----------------------|
| Onboarding | Multi-step signup + profile | App install + identity verification | Zero-friction: first text auto-registers |
| Job discovery | Search + filter UI | Browse feed + apply button | Text earnings goal, get ranked list |
| Earnings transparency | Hourly rate shown | Rate + estimated hours shown | Earnings math explicitly verifies goal achievability |
| Matching | Keyword + location filter | Algorithm + preferences | Earnings math gate + recency sort |
| Identity | Email + password | Phone + government ID | Phone number only |
| Notification | Push + email | Push notifications | SMS reply only |
| Job management | Employer dashboard | Employer app | SMS reply (v1), commands (v1.x) |

---

## Implementation Notes: SMS-Specific Constraints

These are operational realities that affect feature design, not features themselves.

**Message length:** Standard SMS is 160 characters (GSM-7 encoding). Replies containing job lists must be designed for multi-part SMS (concatenated), but conciseness is still critical — long SMS chains are worse UX than a tight 3-job summary.

**Delivery receipt vs. read receipt:** Twilio provides delivery status webhooks (MessageStatus callback) but not read receipts. Do not design features that assume a user has seen a message.

**Carrier filtering:** Carriers filter SMS that look like spam. Job listing replies that contain URLs, dollar signs, or high-frequency sends from a single number can be filtered. Keep reply formatting plain and minimal.

**STOP compliance:** When a user texts STOP, Twilio (and the carrier) suppress all outbound messages to that number. The application must never attempt to send to a STOP-registered number — Twilio will reject it with an error code, but the app should handle this gracefully and not treat it as a processing failure.

**Phone number normalization:** Twilio provides `From` in E.164 format. Store in E.164. Never normalize to local format — international numbers are valid users.

---

## Confidence Assessment by Area

| Area | Confidence | Reason |
|------|------------|--------|
| Twilio webhook security (signature validation, retry behavior) | HIGH | Well-established, stable Twilio feature; consistent across docs versions |
| Idempotency on MessageSid | HIGH | Twilio's MessageSid uniqueness guarantee is a documented contract |
| Rate limiting patterns | HIGH | PostgreSQL-backed TTL counter implemented (SEC-03) |
| Phone-as-identity patterns | HIGH | Standard Twilio SMS pattern, widely implemented |
| LLM extraction reliability/confidence | MEDIUM | gpt-5.3-chat-latest specifics beyond training cutoff; general extraction patterns well-known |
| SMS marketplace feature landscape | MEDIUM | Inferential from adjacent markets (Wonolo, Snagajob); no pure SMS-only competitors to benchmark |
| Earnings math matching correctness | HIGH | Deterministic logic, no external dependencies |
| Carrier filtering behavior | MEDIUM | Carrier policies vary and change; general patterns well-known |

---

## Sources

Sources: REQUIREMENTS.md traceability table, STATE.md, PROJECT.md (HIGH confidence — derived from built system). Updated 2026-03-08.

---

*Feature research for: SMS-based job matching API (Vici)*
*Researched: 2026-03-08*
