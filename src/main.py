import logging
from contextlib import asynccontextmanager
from typing import Any

import inngest
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
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from src.config import settings
from src.database import AsyncSessionLocal, engine
from src.exceptions import twilio_signature_invalid_handler
from src.sms.exceptions import TwilioSignatureInvalid
from src.sms.router import router as sms_router


# ── Inngest client (module-level — imported by service.py to send events) ──────
inngest_client = inngest.Inngest(
    app_id="vici",
    is_production=not settings.inngest_dev,
)


@inngest_client.create_function(
    fn_id="process-message",
    trigger=inngest.TriggerEvent(event="message.received"),
)
async def process_message(ctx: inngest.Context) -> str:
    """Phase 1 stub. Full pipeline wired in Phase 4."""
    logger = structlog.get_logger()
    logger.info(
        "message.received consumed",
        message_sid=ctx.event.data.get("message_sid"),
    )
    return "ok"


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
            structlog.stdlib.add_logger_name,
            _add_otel_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _configure_otel(app: FastAPI) -> TracerProvider:
    resource = Resource(attributes={"service.name": settings.otel_service_name})
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    FastAPIInstrumentor().instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    return provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_structlog()
    provider = _configure_otel(app)
    yield
    provider.force_flush()


# ── FastAPI app ─────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)

# Prometheus — expose /metrics endpoint
Instrumentator().instrument(app).expose(app)

# Inngest — registers POST /api/inngest for Dev Server
inngest.fast_api.serve(app, inngest_client, [process_message])

# Exception handlers
app.add_exception_handler(TwilioSignatureInvalid, twilio_signature_invalid_handler)

# Routers
app.include_router(sms_router)


@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception:
        return JSONResponse(
            status_code=200,
            content={"status": "degraded", "db": "error"},
        )
