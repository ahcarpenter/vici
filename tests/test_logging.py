import structlog
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider


def test_trace_id_in_log():
    """
    Verify that structlog's _add_otel_context processor injects trace_id
    into log output when a span is active.
    """
    # Configure a test TracerProvider (no exporter needed)
    provider = TracerProvider()
    otel_trace.set_tracer_provider(provider)
    tracer = otel_trace.get_tracer("test")

    captured = []

    def capturing_processor(logger, method, event_dict):
        captured.append(dict(event_dict))
        return event_dict

    # Configure structlog with the OTel processor + our capture processor
    from src.main import _add_otel_context  # import the processor function

    structlog.configure(
        processors=[
            _add_otel_context,
            capturing_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    log = structlog.get_logger()

    with tracer.start_as_current_span("test-span"):
        log.info("test event", phone_hash="abc123")

    assert len(captured) == 1
    assert "trace_id" in captured[0], f"trace_id missing from log: {captured[0]}"
    assert len(captured[0]["trace_id"]) == 32  # 128-bit trace_id as 32 hex chars
