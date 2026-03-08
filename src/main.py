import logging
from contextlib import asynccontextmanager
from typing import Any

import inngest.fast_api
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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

from braintrust import wrap_openai
from openai import AsyncOpenAI
from twilio.rest import Client as TwilioClient

from src.config import get_settings
from src.database import get_engine, get_sessionmaker
from src.exceptions import twilio_signature_invalid_handler
from src.extraction.orchestrator import PipelineOrchestrator
from src.extraction.pinecone_client import write_job_embedding
from src.extraction.service import ExtractionService
from src.inngest_client import get_inngest_client, process_message, sync_pinecone_queue
from src.jobs.repository import JobRepository
from src.sms.audit_repository import AuditLogRepository
from src.sms.exceptions import TwilioSignatureInvalid
from src.sms.repository import MessageRepository
from src.sms.router import router as sms_router
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
    resource = Resource(attributes={
        "service.name": settings.observability.otel_service_name,
        "deployment.environment": "development" if settings.inngest_dev else "production",
        "service.version": settings.observability.service_version,
    })
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
    extraction_service = ExtractionService(openai_client=openai_client, settings=settings)
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

    # Inject orchestrator into inngest_client module
    import src.inngest_client as ic
    ic._orchestrator = orchestrator

    yield
    provider.force_flush()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # Prometheus — expose /metrics endpoint
    Instrumentator().instrument(app).expose(app)

    # Inngest — registers POST /api/inngest for Dev Server
    inngest.fast_api.serve(
        app, get_inngest_client(), [process_message, sync_pinecone_queue]
    )

    # Exception handlers
    app.add_exception_handler(
        TwilioSignatureInvalid,
        twilio_signature_invalid_handler,
    )

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
