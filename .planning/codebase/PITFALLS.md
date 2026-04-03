# Implementation Pitfalls

> Last updated: 2026-04-03 | Confidence: HIGH | Source: phase decisions, codebase inspection

## Active Pitfalls

### Database / ORM

1. **expire_on_commit=False required on async_sessionmaker** -- async SQLAlchemy cannot lazy-load after commit. Without this, accessing attributes post-commit raises MissingGreenlet.

2. **Rate limit upsert uses ON CONFLICT (user_id, created_at) column list** -- required for SQLite/PG compatibility. Named constraint syntax differs between engines.

3. **Rate limit uses Python datetime.now(UTC) instead of SQL NOW()** -- SQLite does not support NOW() function. Bound parameter ensures test compatibility.

4. **Raw SQL for rate limit SELECT** -- bypasses ORM identity cache to avoid stale reads across multiple calls in same session.

### Temporal

5. **RPCError for cron schedule idempotency** -- SyncPineconeQueueWorkflow uses cron schedule. Temporal raises RPCError if workflow ID already exists with same schedule. Catch and ignore on startup.

6. **TracingInterceptor goes on Client.connect() only** -- worker inherits interceptors from client automatically. Adding interceptor to worker separately causes duplicate spans.

7. **Handler registration happens in lifespan DI** -- handlers must be instantiated with their repositories after sessionmaker is created. Getting the order wrong causes None reference errors.

8. **Temporal worker task must be cancelled on shutdown** -- lifespan yields then cancels the asyncio task. Without explicit cancellation, the process hangs on SIGTERM.

### GPT / Extraction

9. **Patch target for tests is src.extraction.service.wrap_openai** -- not braintrust.wrap_openai. The service module does a direct import, so the module-level reference must be patched.

10. **ExtractionService.process() can return None from GPT** -- added guard in 02.11. If GPT returns None/malformed response, raises structured error instead of AttributeError downstream.

11. **Metrics imported inside process() (not module top)** -- avoids circular imports between metrics.py and service.py.

### Observability

12. **ALWAYS_ON sampler (not ParentBasedTraceIdRatio)** -- parent-based sampling can silently drop traces when no parent context. ALWAYS_ON is unambiguous for a service that originates traces.

13. **OpenSearch replicas=0 for single-node local dev** -- replicas > 0 causes yellow cluster health, which blocks Jaeger health checks in docker-compose.

14. **Twilio span wraps asyncio.to_thread** -- OTel context does not propagate into threads. The span must be created in the async context before the thread call.

15. **Module-level tracer patched in test fixtures** -- provider override warning makes InMemorySpanExporter approach unreliable. Direct module-level patching is the stable pattern.

### Configuration

16. **Settings._validate_required_credentials fires before _build_sub_models** -- both are mode=after validators. Declaration order matters; credential check must come first.

17. **Nested Settings use model_validator(mode=after) remapping flat env vars** -- no .env file changes required; flat TWILIO_AUTH_TOKEN maps to twilio.auth_token via validator.

### SMS / Webhook

18. **Twilio unknown reply uses asyncio.to_thread()** -- Twilio REST client is synchronous. Must be called via to_thread in async handler to avoid blocking event loop.

19. **register_phone raw SQL includes created_at explicitly** -- SQLModel default_factory does not fire for raw SQL inserts.

## Historical (no longer applicable)

20. **[replaced in 02.9] Inngest _orchestrator module-level var** -- was set by lifespan to avoid circular imports. Now replaced by Temporal activities accessing app.state directly.

21. **[replaced in 02.9] autouse _auto_mock_inngest_send fixture** -- prevented real Inngest HTTP calls in tests. Inngest fully removed; Temporal test patterns use mock activities instead.
