import asyncio
import logging
import os
from collections.abc import MutableMapping
from contextlib import asynccontextmanager, suppress
from functools import partial
from typing import Any

import structlog
from braintrust import init_logger, wrap_openai
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from twilio.rest import Client as TwilioClient

from src.config import get_settings
from src.database import get_engine, get_sessionmaker
from src.extraction.constants import OPENAI_MAX_RETRIES
from src.extraction.repository import PineconeSyncQueueRepository
from src.extraction.service import ExtractionService
from src.extraction.utils import write_job_embedding
from src.jobs.repository import JobRepository
from src.matches.repository import MatchRepository
from src.matches.service import MatchService
from src.metrics import pinecone_sync_queue_depth
from src.pipeline.handlers.job_posting import JobPostingHandler
from src.pipeline.handlers.unknown import UnknownMessageHandler
from src.pipeline.handlers.work_goal import WorkGoalHandler
from src.pipeline.orchestrator import PipelineOrchestrator
from src.sms.audit_repository import AuditLogRepository
from src.sms.error_handlers import (
    early_return_handler,
    twilio_signature_invalid_handler,
)
from src.sms.exceptions import EarlyReturn, TwilioSignatureInvalid
from src.sms.repository import MessageRepository
from src.sms.router import router as sms_router
from src.temporal.constants import WORKER_SHUTDOWN_TIMEOUT_SECONDS
from src.temporal.worker import get_temporal_client, run_worker, start_cron_if_needed
from src.work_goals.repository import WorkGoalRepository

_GAUGE_POLL_INTERVAL_SECONDS: int = 15
_GAUGE_MAX_CONSECUTIVE_FAILURES: int = 5
_GAUGE_SHUTDOWN_TIMEOUT_SECONDS: float = 5.0
_READYZ_DB_TIMEOUT_SECONDS: float = 2.0
_OTEL_FORCE_FLUSH_TIMEOUT_MILLIS: int = 5000

SHOW_DOCS_ENVIRONMENT: tuple[str, ...] = ("local", "development", "staging")


# ── structlog OTel processor ────────────────────────────────────────────────────
def _add_otel_context(
    logger: Any, method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            _add_otel_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _configure_otel(app: FastAPI) -> TracerProvider:
    settings = get_settings()
    resource = Resource(
        attributes={
            "service.name": settings.observability.otel_service_name,
            "deployment.environment": (
                "development" if settings.env != "production" else "production"
            ),
            "service.version": settings.observability.service_version,
        }
    )
    exporter = OTLPSpanExporter(endpoint=settings.observability.otel_endpoint)
    provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    FastAPIInstrumentor().instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    return provider


def _configure_braintrust() -> None:
    settings = get_settings()
    if settings.observability.braintrust_api_key:
        init_logger(project="vici")
    else:
        structlog.get_logger().warning(
            "braintrust_logger_disabled",
            reason="BRAINTRUST_API_KEY not set — LLM call observability disabled",
        )


async def _update_gauges() -> None:
    """Poll pinecone_sync_queue every 15 s and update the depth gauge."""
    sync_queue_repo = PineconeSyncQueueRepository()
    consecutive_failures = 0
    while True:
        try:
            async with get_sessionmaker()() as session:
                depth = await sync_queue_repo.count_pending(session)
                pinecone_sync_queue_depth.set(depth)
                consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            if consecutive_failures > _GAUGE_MAX_CONSECUTIVE_FAILURES:
                structlog.get_logger().critical(
                    "gauge_updater: repeated DB failures, metric unreliable",
                    consecutive_failures=consecutive_failures,
                    error=str(exc),
                )
                pinecone_sync_queue_depth.set(-1)
            else:
                structlog.get_logger().warning(
                    "gauge_updater: pinecone_sync_queue depth read failed"
                    " — metric stale",
                    error=str(exc),
                )
        await asyncio.sleep(_GAUGE_POLL_INTERVAL_SECONDS)


def _docs_app_configs(env: str) -> dict[str, Any]:
    """Return FastAPI(**kwargs) needed to hide API docs outside permitted envs.

    Must be applied at FastAPI(...) construction time — setting app.openapi_url
    after __init__ leaves the routes already registered (and /docs 500s because
    its handler concatenates openapi_url into a string).
    """
    if env in SHOW_DOCS_ENVIRONMENT:
        return {}
    return {"openapi_url": None, "docs_url": None, "redoc_url": None}


def _build_orchestrator(
    openai_client: AsyncOpenAI, twilio_client: TwilioClient
) -> PipelineOrchestrator:
    """Assemble the message-processing pipeline's dependency graph."""
    settings = get_settings()
    extraction_service = ExtractionService(
        openai_client=openai_client, settings=settings
    )
    audit_repo = AuditLogRepository()
    # Bind infrastructure into the embedding-writer port here so handlers
    # never touch the OpenAI client or settings.
    job_embedding_writer = partial(
        write_job_embedding, openai_client=openai_client, settings=settings
    )
    match_service = MatchService(job_repo=JobRepository(), match_repo=MatchRepository())
    handlers = [
        JobPostingHandler(
            job_repo=JobRepository(),
            audit_repo=audit_repo,
            job_embedding_writer=job_embedding_writer,
            sync_queue_repo=PineconeSyncQueueRepository(),
        ),
        WorkGoalHandler(
            work_goal_repo=WorkGoalRepository(),
            audit_repo=audit_repo,
            match_service=match_service,
            twilio_client=twilio_client,
            from_number=settings.sms.from_number,
        ),
        UnknownMessageHandler(
            twilio_client=twilio_client,
            from_number=settings.sms.from_number,
        ),
    ]
    return PipelineOrchestrator(
        extraction_service=extraction_service,
        audit_repo=audit_repo,
        message_repo=MessageRepository(),
        handlers=handlers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_structlog()
    provider = _configure_otel(app)
    _configure_braintrust()
    settings = get_settings()

    if settings.sms.disable_twilio_signature_validation:
        structlog.get_logger().warning("twilio_signature_validation_disabled")

    # Build DI graph
    openai_client = wrap_openai(
        AsyncOpenAI(
            api_key=settings.extraction.openai_api_key,
            max_retries=OPENAI_MAX_RETRIES,
        )
    )
    twilio_client = TwilioClient(settings.sms.account_sid, settings.sms.auth_token)
    orchestrator = _build_orchestrator(openai_client, twilio_client)

    app.state.orchestrator = orchestrator

    # Connect to Temporal and start the worker
    temporal_client = await get_temporal_client(settings.temporal.address)
    app.state.temporal_client = temporal_client
    _worker_task = asyncio.create_task(
        run_worker(temporal_client, orchestrator, openai_client)
    )
    await start_cron_if_needed(temporal_client)

    # Background gauge updater — polls pinecone_sync_queue every 15s
    _gauge_task = asyncio.create_task(_update_gauges())
    yield
    _worker_task.cancel()
    with suppress(TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(_worker_task, timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS)
    _gauge_task.cancel()
    with suppress(TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(_gauge_task, timeout=_GAUGE_SHUTDOWN_TIMEOUT_SECONDS)
    provider.force_flush(timeout_millis=_OTEL_FORCE_FLUSH_TIMEOUT_MILLIS)


def create_app() -> FastAPI:
    # Read ENV directly rather than via get_settings() — this runs at module
    # import time (app = create_app()) before conftest fixtures populate the
    # full credentials required by Settings validation.
    env = os.getenv("ENV", "")
    app = FastAPI(lifespan=lifespan, **_docs_app_configs(env))

    # Prometheus — expose /metrics endpoint
    Instrumentator().instrument(app).expose(app)

    # Exception handlers — starlette's stub wants (Request, Exception) rather
    # than the concrete exception subclass, hence the ignores.
    app.add_exception_handler(
        TwilioSignatureInvalid,
        twilio_signature_invalid_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(EarlyReturn, early_return_handler)  # type: ignore[arg-type]

    # Routers
    app.include_router(sms_router)

    @app.get("/health")
    async def health():
        # Liveness: process is up.
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        # Readiness: DB connectivity (used by orchestrators).
        try:
            async with get_sessionmaker()() as session:
                await asyncio.wait_for(
                    session.execute(text("SELECT 1")),
                    timeout=_READYZ_DB_TIMEOUT_SECONDS,
                )
            return {"status": "ok", "db": "connected"}
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "db": "error"},
            )

    return app


app = create_app()
