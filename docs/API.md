<!-- generated-by: gsd-doc-writer -->
# API Reference

Vici exposes a small HTTP surface built on FastAPI. The public API is intentionally narrow: one webhook endpoint for inbound Twilio SMS traffic, plus operational endpoints for liveness, readiness, and Prometheus metrics. All business logic is driven asynchronously through Temporal workflows after the webhook persists the inbound message.

- **Framework**: FastAPI (`src/main.py`)
- **Primary domain router**: `src/sms/router.py` (mounted via `app.include_router(sms_router)`)
- **Operational routes**: declared inline in `create_app()` in `src/main.py`
- **Metrics**: exposed by `prometheus-fastapi-instrumentator` (`Instrumentator().instrument(app).expose(app)` in `src/main.py`)

## Authentication

Vici does not use API keys, JWTs, OAuth, or session cookies. Instead, the only externally reachable endpoint that mutates state — `POST /webhook/sms` — authenticates inbound requests using **Twilio request signature validation**:

- Twilio signs every webhook request with the account auth token (`TWILIO_AUTH_TOKEN`) and sends the signature in the `X-Twilio-Signature` header.
- `validate_twilio_request` in `src/sms/dependencies.py` reconstructs the canonical public URL from `WEBHOOK_BASE_URL` (see `CONFIGURATION.md`), then calls `twilio.request_validator.RequestValidator.validate(url, form_data, signature)`.
- If validation fails, the dependency raises `TwilioSignatureInvalid`, which the exception handler registered in `src/main.py` converts to an **HTTP 403** JSON response: `{"detail": "Invalid Twilio signature"}` (`src/exceptions.py`).
- In `env == "development"`, signature validation is bypassed to simplify local testing with tunneled webhooks. All other environments enforce validation.

The `/health`, `/readyz`, and `/metrics` endpoints are unauthenticated and intended to be consumed by orchestrators (Kubernetes probes, Prometheus scrapers) on an internal network.

## Endpoints Overview

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/webhook/sms` | Receive an inbound SMS from Twilio, persist it, and emit a Temporal event | Twilio signature (enforced outside `development`) |
| GET | `/health` | Liveness probe — returns `{"status": "ok"}` as long as the process is up | None |
| GET | `/readyz` | Readiness probe — verifies DB connectivity with `SELECT 1` | None |
| GET | `/metrics` | Prometheus text-format metrics exposed by `prometheus-fastapi-instrumentator` | None |

## `POST /webhook/sms`

Defined in `src/sms/router.py` (`receive_sms`). This is the primary entry point for Twilio traffic and is guarded by a chain of FastAPI dependencies that enforce all pre-flight gates before the route body executes.

### Request

- **Content-Type**: `application/x-www-form-urlencoded` (Twilio webhooks are URL-encoded form posts)
- **Headers**:
  - `X-Twilio-Signature` — required in all non-development environments; validated against `WEBHOOK_BASE_URL + request path + query`
- **Form fields**: Twilio sends many fields; Vici reads the following (see `TwilioWebhookPayload` in `src/sms/schemas.py`):

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `MessageSid` | string | `min_length=1`, `max_length=64` | Twilio's unique message ID; used as the idempotency key |
| `From` | string | `min_length=1`, `max_length=20` | Sender phone number in E.164 format |
| `Body` | string | `min_length=0`, `max_length=1600` | The SMS text (may be empty) |
| `AccountSid` | string | `min_length=1`, `max_length=64` | Twilio account SID |

Additional Twilio fields are accepted and logged (`model_config = ConfigDict(extra="allow")`).

### Dependency Chain (Pre-Flight Gates)

The route declares a single `Depends(enforce_rate_limit)` dependency, which transitively invokes four gates in order. All gates are defined in `src/sms/dependencies.py`:

1. **`validate_twilio_request`** — Parses the form body; raises `HTTPException(400, "Missing required fields: MessageSid, From")` if either field is absent. Otherwise validates the Twilio signature (except in `development`).
2. **`check_idempotency`** — Looks up `MessageSid` in the `message` table via `MessageRepository.check_idempotency`. If already seen, raises `DuplicateMessageSid` (a subclass of `EarlyReturn`) and writes a `"duplicate"` audit log entry.
3. **`get_or_create_user`** — Hashes the `From` number with `sms_service.hash_phone` and upserts a row in the `users` table via `UserRepository.get_or_create`.
4. **`enforce_rate_limit`** — Calls `MessageRepository.enforce_rate_limit(session, user.id)`. If the rolling window limit is exceeded, raises `RateLimitExceeded` (a subclass of `EarlyReturn`) and writes a `"rate_limited"` audit log entry.

After the gates pass, the route body:

- Persists the message via `MessageRepository().create(session, message_sid, user.id, body)`
- Writes a `"received"` audit log entry with the full form payload serialized as JSON
- Emits a `message_received` event onto the Temporal workflow via `sms_service.emit_message_received_event`
- Returns an empty TwiML response to Twilio

### Response

- **Success (`200 OK`)**:
  - **Content-Type**: `text/xml`
  - **Body**: `<?xml version="1.0" encoding="UTF-8"?><Response/>` (defined as `EMPTY_TWIML` in `src/sms/exceptions.py`)

- **Duplicate message (`200 OK`)**: `DuplicateMessageSid` is caught by the `early_return_handler` (registered in `src/main.py`) and returned as the same empty TwiML payload. This is intentional — Twilio retries on any 4xx/5xx, so duplicates are acknowledged rather than rejected.

- **Rate limited (`200 OK`)**: `RateLimitExceeded` is handled identically to duplicates — the caller receives empty TwiML so Twilio does not retry.

- **Invalid signature (`403 Forbidden`)**: JSON body `{"detail": "Invalid Twilio signature"}` (`twilio_signature_invalid_handler` in `src/exceptions.py`). This is the one path where Vici deliberately returns a non-200 to Twilio — signature failures indicate tampering or misconfiguration, not a transient error.

- **Missing required fields (`400 Bad Request`)**: JSON body `{"detail": "Missing required fields: MessageSid, From"}`, raised directly by `validate_twilio_request`.

### Example

```bash
curl -X POST https://api.example.com/webhook/sms \
  -H "X-Twilio-Signature: <twilio-generated-signature>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "MessageSid=SM1234567890abcdef" \
  --data-urlencode "From=+15555550123" \
  --data-urlencode "Body=Looking for warehouse work this weekend" \
  --data-urlencode "AccountSid=AC1234567890abcdef"
```

Successful response:

```xml
<?xml version="1.0" encoding="UTF-8"?><Response/>
```

## `GET /health`

Defined inline in `create_app()` in `src/main.py`. Liveness probe — does not touch the database or any external service. Always returns 200 as long as the FastAPI process is up.

### Response

- **Status**: `200 OK`
- **Content-Type**: `application/json`
- **Body**:

  ```json
  {"status": "ok"}
  ```

### Example

```bash
curl https://api.example.com/health
# {"status":"ok"}
```

## `GET /readyz`

Defined inline in `create_app()` in `src/main.py`. Readiness probe used by orchestrators (e.g. Kubernetes) to decide whether to route traffic. Opens a database session from `get_sessionmaker()()` and executes `SELECT 1`.

### Response

- **Ready (`200 OK`)**:

  ```json
  {"status": "ok", "db": "connected"}
  ```

- **Degraded (`503 Service Unavailable`)**: Returned when the `SELECT 1` raises any exception.

  ```json
  {"status": "degraded", "db": "error"}
  ```

### Example

```bash
curl -i https://api.example.com/readyz
```

## `GET /metrics`

Exposed by `prometheus-fastapi-instrumentator` via `Instrumentator().instrument(app).expose(app)` in `src/main.py`. Returns Prometheus text-format metrics, including the default HTTP instrumentator metrics (request counts, latency histograms, etc.) plus the custom `pinecone_sync_queue_depth` gauge updated every 15 seconds by the `_update_gauges` background task (see `src/metrics.py` and `src/main.py`).

### Response

- **Status**: `200 OK`
- **Content-Type**: `text/plain; version=0.0.4; charset=utf-8` (Prometheus exposition format)

### Example

```bash
curl https://api.example.com/metrics
```

## Error Codes

Vici intentionally uses a narrow set of HTTP status codes. The Twilio webhook path is especially constrained: because Twilio retries on any 4xx/5xx response, almost all error conditions are converted to `200 OK` with empty TwiML so they are not retried.

| Status | When returned | Response shape |
|--------|--------------|----------------|
| `200 OK` | Successful webhook ingestion; duplicate `MessageSid`; rate limit exceeded | `EMPTY_TWIML` (`text/xml`) |
| `200 OK` | `/health` success | `{"status": "ok"}` |
| `200 OK` | `/readyz` success | `{"status": "ok", "db": "connected"}` |
| `200 OK` | `/metrics` success | Prometheus text format |
| `400 Bad Request` | Missing `MessageSid` or `From` on the webhook | `{"detail": "Missing required fields: MessageSid, From"}` |
| `403 Forbidden` | Twilio signature validation failed (non-development only) | `{"detail": "Invalid Twilio signature"}` |
| `503 Service Unavailable` | `/readyz` database probe failed | `{"status": "degraded", "db": "error"}` |

### `EarlyReturn` Pattern

`src/sms/exceptions.py` defines an `EarlyReturn` exception hierarchy specifically for the Twilio webhook. Any dependency that wants to short-circuit processing with an empty-TwiML 200 raises a subclass of `EarlyReturn`. The `early_return_handler` (registered in `src/main.py`) catches all subclasses and returns the same empty TwiML response. Current subclasses:

- `DuplicateMessageSid` — raised by `check_idempotency` in `src/sms/dependencies.py`
- `RateLimitExceeded` — raised by `enforce_rate_limit` in `src/sms/dependencies.py`

New gates that need to short-circuit the webhook should subclass `EarlyReturn` rather than raising `HTTPException`, to preserve the invariant that Twilio never receives a retry-triggering status for operational conditions.

## Rate Limits

Rate limiting is enforced only on `POST /webhook/sms`, and applies per user (keyed by the hashed `From` phone number). The limit is a rolling window enforced at the database level by `MessageRepository.enforce_rate_limit` (`src/sms/repository.py`), using the `rate_limit` table.

- **Window**: 60 seconds (`RATE_LIMIT_WINDOW_SECONDS` in `src/sms/constants.py`)
- **Max messages per window**: 5 (`MAX_MESSAGES_PER_WINDOW` in `src/sms/constants.py`)

These constants have matching defaults in `SmsSettings` (`src/config.py`): `rate_limit_window_seconds=60`, `rate_limit_max=5`.

When the limit is exceeded, the dependency raises `RateLimitExceeded`, a `"rate_limited"` audit log row is written, and Twilio receives the standard empty TwiML 200 response. The system does not return a `429 Too Many Requests` on this path because Twilio would retry and compound the problem.

The operational endpoints (`/health`, `/readyz`, `/metrics`) are not rate limited — they are expected to be called frequently by orchestrators and scrapers.
