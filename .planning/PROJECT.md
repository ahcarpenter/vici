# Vici

## What This Is

A Python/FastAPI API that receives SMS messages via a single Twilio webhook and uses GPT to classify and extract structured data from natural language. Job posters text to create job listings; workers text their earnings goals and receive a ranked list of matching jobs. No app, no signup — just text.

## Core Value

A worker who texts their earnings goal must receive a ranked list of jobs that lets them hit that goal in the shortest possible time.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Single Twilio SMS webhook receives all inbound messages
- [ ] GPT-5.2 classifies each message as a job posting or a worker earnings goal
- [ ] Job posting extracts: description, ideal date/time, date/time flexibility, estimated duration (optional), location, pay/rate
- [ ] Worker goal extracts: target earnings amount, target timeframe
- [ ] Structured job postings stored in PostgreSQL with pgvector embeddings
- [ ] Structured worker goals stored in PostgreSQL
- [ ] Job matching uses earnings math: rate x estimated duration >= worker goal, sorted by soonest available / shortest duration
- [ ] Job poster receives SMS confirmation summarizing extracted job details
- [ ] Worker receives SMS reply with ranked list of matching jobs

### Out of Scope

- User registration or auth flows — phone number is identity, first text auto-registers
- Web UI or dashboard — API only for MVP
- Multiple Twilio phone numbers or routing logic — single inbound number
- Real-time push notifications — SMS reply is the only notification mechanism
- Payment processing — rate/pay is informational only in v1

## Context

- Single Twilio webhook endpoint handles all message classification and routing
- GPT-5.2 handles both classification (job vs. worker goal) and structured extraction in a single call where possible
- pgvector is included from the start to enable semantic job matching in future milestones (v1 uses earnings math only)
- Phone number extracted from Twilio request payload serves as the user identifier
- Enterprise tooling is a first-class requirement, not an afterthought: layered architecture, migrations, Docker, and observability are in scope for the MVP

## Constraints

- **AI Model**: GPT-5.2 (OpenAI) — specified by product owner for extraction and classification
- **Database**: PostgreSQL + pgvector — required for structured storage and future semantic search
- **Framework**: Python + FastAPI — async-ready, strong AI ecosystem
- **Inbound Channel**: Twilio SMS only — no other input channels in v1
- **Identity**: Phone number only — no auth, no user management system

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single webhook endpoint for all message types | Simplifies Twilio config; AI classifier handles routing | — Pending |
| GPT classifies + extracts in same call | Reduces latency and token overhead vs. two-step approach | — Pending |
| Earnings math for v1 matching (not semantic) | Deterministic, testable, and directly answers the worker's question | — Pending |
| pgvector included in v1 schema | Future semantic matching requires embeddings; retrofitting is costly | — Pending |
| Layered architecture from day one | Routes → services → repositories enables team scaling without rewrites | — Pending |

---
*Last updated: 2026-03-05 after initialization*
