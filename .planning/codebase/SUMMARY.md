# Codebase Summary

> Last updated: 2026-04-03 | Confidence: HIGH

## One-Liner

SMS-driven job matching platform: workers text earnings goals, GPT classifies/extracts, Temporal orchestrates pipeline, Pinecone stores embeddings, Twilio delivers ranked results.

## Current State

The application is production-ready from infrastructure and domain-logic perspectives. Phases 01 through 02.12 are complete, covering:

- **Inbound SMS pipeline**: Twilio webhook with 5-gate security chain, GPT classification and extraction via discriminated union, handler-based dispatch (Chain of Responsibility pattern)
- **Data persistence**: 3NF PostgreSQL schema (7 tables), async SQLAlchemy with repository pattern
- **Vector search**: Pinecone embeddings for jobs, with retry queue for failed writes
- **Workflow orchestration**: Temporal workflows (replaced Inngest in Phase 02.9) with ProcessMessage (4 retries + failure handler) and SyncPineconeQueue (cron sweep)
- **Observability**: Full stack -- structlog JSON, OpenTelemetry traces to Jaeger v2 (OpenSearch), Prometheus metrics to Grafana, TracingInterceptor on Temporal
- **Production infra**: Multi-stage Dockerfile, render.yaml Blueprint, GitHub Actions CI

## What Remains

- **Phase 03**: MatchService -- earnings math SQL, ranked SMS formatter, empty-match fallback
- **Phase 04**: Outbound SMS for job posters/workers, STOP/START handling, Render.com deploy validation

## Key Architecture Decisions

1. **Temporal replaced Inngest** (02.9): Better workflow semantics, native retry/cron, no external SaaS dependency for dev
2. **Pipeline handler pattern** (02.12): Chain of Responsibility with MessageHandler ABC -- extensible for new message types without modifying orchestrator
3. **TracingInterceptor on client only** (02.10): Worker inherits; avoids duplicate spans
4. **ALWAYS_ON sampler** (02.3): No sampling ambiguity in a service that originates all its traces
5. **Nested Pydantic Settings** (02.1): Flat env vars remapped via model_validator -- no .env format changes
