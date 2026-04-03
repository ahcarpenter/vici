import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import structlog
from braintrust import wrap_openai
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
from src.exceptions import twilio_signature_invalid_handler
from src.pipeline.handlers.job_posting import JobPostingHandler
from src.pipeline.handlers.unknown import UnknownMessageHandler
from src.pipeline.handlers.worker_goal import WorkerGoalHandler
from src.pipeline.orchestrator import PipelineOrchestrator
from src.extraction.pinecone_client import write_job_embedding
from src.extraction.service import ExtractionService
from src.jobs.repository import JobRepository
from src.sms.audit_repository import AuditLogRepository
from src.sms.exceptions import EarlyReturn, TwilioSignatureInvalid, early_return_handler
from src.sms.repository import MessageRepository
from src.sms.router import router as sms_router
from src.temporal.worker import get_temporal_client, run_worker, start_cron_if_needed
from src.work_requests.repository import WorkRequestRepository


# ── structlog OTel processor ────────────────────────────────────────────────────
def _add_otel_context(logger: Any, method: str, event_dict: dict) -> dict:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_structlog()
    provider = _configure_otel(app)
    settings = get_settings()

    # Build DI graph
    openai_client = wrap_openai(
        AsyncOpenAI(api_key=settings.extraction.openai_api_key, max_retries=0)
    )
    extraction_service = ExtractionService(
        openai_client=openai_client, settings=settings
    )
    pinecone_client = write_job_embedding
    twilio_client = TwilioClient(settings.sms.account_sid, settings.sms.auth_token)

    orchestrator = PipelineOrchestrator(
        extraction_service=extraction_service,
        job_repo=JobRepository,
        work_request_repo=WorkRequestRepository,
        message_repo=MessageRepository,
        audit_repo=AuditLogRepository,
        pinecone_client=pinecone_client,
        twilio_client=twilio_client,
    )

    app.state.orchestrator = orchestrator

    # Connect to Temporal and start the worker
    temporal_client = await get_temporal_client(settings.temporal_address)
    app.state.temporal_client = temporal_client
    _worker_task = asyncio.create_task(
        run_worker(temporal_client, orchestrator, openai_client)
    )
    await start_cron_if_needed(temporal_client)

    # Background gauge updater — polls pinecone_sync_queue every 15s
    from src.metrics import pinecone_sync_queue_depth

    async def _update_gauges():
        consecutive_failures = 0
        while True:
            try:
                async with get_sessionmaker()() as session:
                    result = await session.execute(
                        text(
                            "SELECT COUNT(*) FROM pinecone_sync_queue"
                            " WHERE status = 'pending'"
                        )
                    )
                    pinecone_sync_queue_depth.set(result.scalar_one())
                    consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                if consecutive_failures > 5:
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
            await asyncio.sleep(15)

    _gauge_task = asyncio.create_task(_update_gauges())
    yield
    _worker_task.cancel()
    try:
        await asyncio.wait_for(_worker_task, timeout=10)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    _gauge_task.cancel()
    provider.force_flush()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # Prometheus — expose /metrics endpoint
    Instrumentator().instrument(app).expose(app)

    # Exception handlers
    app.add_exception_handler(
        TwilioSignatureInvalid,
        twilio_signature_invalid_handler,
    )
    app.add_exception_handler(EarlyReturn, early_return_handler)

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
                await session.execute(text("SELECT 1"))
            return {"status": "ok", "db": "connected"}
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "db": "error"},
            )

    return app


app = create_app()
