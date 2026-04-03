# Architecture

> Last updated: 2026-04-03 | Confidence: HIGH | Source: codebase inspection

## Overview

Vici is an SMS-driven job matching platform. Workers text an earnings goal; job posters text a listing. GPT classifies and extracts structured data. The system matches workers to jobs and replies via Twilio SMS.

## Source Layout

```
src/
├── main.py                        # FastAPI app + lifespan DI graph
├── config.py                      # Nested Pydantic Settings (db, twilio, openai, observability)
├── database.py                    # Async SQLAlchemy engine + sessionmaker
├── models.py                      # Central SQLModel aggregator
├── repository.py                  # Base repository class
├── metrics.py                     # Prometheus metric singletons
├── exceptions.py                  # Custom exceptions + FastAPI handlers
├── sms/                           # Twilio webhook route, MessageRepository, AuditLogRepository
│   ├── router.py                  #   POST /sms/webhook (5-gate security chain)
│   ├── dependencies.py            #   Twilio signature validation, rate limiting, user lookup
│   ├── repository.py              #   MessageRepository (CRUD)
│   ├── audit_repository.py        #   AuditLogRepository (append-only)
│   ├── service.py                 #   hash_phone, emit_message_received_event
│   ├── schemas.py                 #   TwilioWebhookPayload, etc.
│   ├── models.py                  #   Message, RateLimit, AuditLog SQLModels
│   ├── constants.py               #   Rate limit thresholds
│   └── exceptions.py              #   TwilioSignatureInvalid, EarlyReturn
├── extraction/                    # GPT classification + Pinecone embedding
│   ├── service.py                 #   ExtractionService (GPT classify+extract via beta.chat.completions.parse)
│   ├── schemas.py                 #   ExtractionResult discriminated union (JobPosting | WorkerGoal | Unknown)
│   ├── prompts.py                 #   System prompt for GPT classification
│   ├── constants.py               #   Model names, token limits
│   ├── models.py                  #   PineconeSyncQueue SQLModel
│   └── pinecone_client.py         #   write_job_embedding (text-embedding-3-small)
├── pipeline/                      # Message processing pipeline (Chain of Responsibility)
│   ├── orchestrator.py            #   PipelineOrchestrator: classify -> audit -> dispatch to handler
│   ├── context.py                 #   PipelineContext dataclass (session, result, identifiers)
│   └── handlers/                  #   One handler per message type
│       ├── base.py                #   MessageHandler ABC (can_handle + handle)
│       ├── job_posting.py         #   JobPostingHandler: persist job + embed to Pinecone
│       ├── worker_goal.py         #   WorkerGoalHandler: persist work request
│       └── unknown.py             #   UnknownMessageHandler: send SMS reply via Twilio
├── temporal/                      # Temporal workflow orchestration
│   ├── workflows.py              #   ProcessMessageWorkflow, SyncPineconeQueueWorkflow
│   ├── activities.py             #   process_message_activity, sync_pinecone_queue_activity, failure handler
│   └── worker.py                 #   get_temporal_client (TracingInterceptor), run_worker, start_cron_if_needed
├── jobs/                          # Job domain
│   ├── models.py                  #   Job SQLModel
│   ├── repository.py              #   JobRepository
│   └── schemas.py                 #   JobPosting Pydantic schema
├── work_requests/                 # Work request domain
│   ├── models.py                  #   WorkRequest SQLModel
│   ├── repository.py              #   WorkRequestRepository
│   └── schemas.py                 #   WorkerGoal Pydantic schema
├── users/                         # User domain
│   ├── models.py                  #   User SQLModel
│   └── repository.py              #   UserRepository
└── matches/                       # Match domain (Phase 3 - not yet implemented)
    └── models.py                  #   Match SQLModel (placeholder)
```

## DI Graph (lifespan)

```
AsyncOpenAI -> wrap_openai (Braintrust) -> ExtractionService
JobRepository, WorkRequestRepository, AuditLogRepository -> instantiated from sessionmaker
ExtractionService + AuditLogRepository -> PipelineOrchestrator
  PipelineOrchestrator receives handlers list:
    [JobPostingHandler, WorkerGoalHandler, UnknownMessageHandler]
      JobPostingHandler(JobRepository, write_job_embedding, AuditLogRepository)
      WorkerGoalHandler(WorkRequestRepository, AuditLogRepository)
      UnknownMessageHandler(TwilioClient, settings, AuditLogRepository)
PipelineOrchestrator -> stored in app.state for Temporal activities to access
Temporal client (with TracingInterceptor) -> worker task started in lifespan
```

## Request Flow

```
Twilio -> POST /sms/webhook
  -> validate_twilio_request (signature check)
  -> check_rate_limit (rolling window)
  -> register_phone (get-or-create User)
  -> save_message (MessageRepository)
  -> start Temporal workflow (ProcessMessageWorkflow)
    -> process_message_activity
      -> PipelineOrchestrator.run()
        -> ExtractionService.process() (GPT classify+extract)
        -> AuditLogRepository.write() (classification audit)
        -> handler.handle() (persist + side effects)
  -> return TwiML response
```

## Background Jobs (Temporal)

| Workflow | Trigger | Description |
|----------|---------|-------------|
| ProcessMessageWorkflow | Each inbound SMS | Classify, extract, persist, embed. 4 attempts with exponential backoff. on_failure sends error SMS. |
| SyncPineconeQueueWorkflow | Cron (every 5 min) | Sweep PineconeSyncQueue for failed embeddings, retry. RPCError for cron idempotency. |

## Docker Compose (local dev, 9 services)

postgres | opensearch | jaeger-collector | jaeger-query | app | temporal | temporal-ui | prometheus | grafana

## Deployment (production)

Render.com -- render.yaml Blueprint (web service + PostgreSQL 16 basic-256mb)
