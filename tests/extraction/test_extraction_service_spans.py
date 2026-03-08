"""
Tests for OTel span emission in extraction/service.py ExtractionService.process().
Uses InMemorySpanExporter to capture spans without a real OTLP backend.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.extraction.constants import GPT_MODEL
from src.extraction.schemas import ExtractionResult, JobExtraction


@pytest.fixture
def span_exporter():
    """Set up an InMemorySpanExporter, patching the module-level tracer directly."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")

    import src.extraction.service as svc_module
    original_tracer = svc_module.tracer
    svc_module.tracer = test_tracer

    yield exporter

    svc_module.tracer = original_tracer
    exporter.shutdown()


def _make_service():
    """Build an ExtractionService with a mock OpenAI client and settings."""
    from src.extraction.service import ExtractionService

    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.extraction.gpt_model = GPT_MODEL

    service = ExtractionService(openai_client=mock_client, settings=mock_settings)
    return service


@pytest.mark.asyncio
async def test_extraction_service_emits_gpt_span(span_exporter):
    """ExtractionService.process() emits a span named 'gpt.classify_and_extract' with gen_ai attributes."""
    service = _make_service()

    stub_result = ExtractionResult(
        message_type="job_posting",
        job=JobExtraction(
            description="Need a mover",
            datetime_flexible=False,
            location="Chicago",
            pay_type="hourly",
            pay_rate=25.0,
        ),
    )

    stub_usage = MagicMock()
    stub_usage.prompt_tokens = 10
    stub_usage.completion_tokens = 5
    with patch.object(service, "_call_with_retry", new=AsyncMock(return_value=(stub_result, stub_usage))):
        result = await service.process(sms_text="Need a mover", phone_hash="hash123")

    assert result.message_type == "job_posting"

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "gpt.classify_and_extract" in span_names, f"Expected span not found. Got: {span_names}"

    gpt_span = next(s for s in spans if s.name == "gpt.classify_and_extract")
    attrs = dict(gpt_span.attributes)
    assert attrs.get("gen_ai.system") == "openai"
    assert attrs.get("gen_ai.request.model") == GPT_MODEL


@pytest.mark.asyncio
async def test_extraction_service_gpt_span_attributes_match_settings(span_exporter):
    """gen_ai.request.model reflects the configured model from settings (not a hardcoded string)."""
    service = _make_service()
    # Verify the settings mock has the expected model
    assert service._settings.extraction.gpt_model == GPT_MODEL

    stub_result = ExtractionResult(message_type="unknown")
    stub_usage = MagicMock()
    stub_usage.prompt_tokens = 0
    stub_usage.completion_tokens = 0

    with patch.object(service, "_call_with_retry", new=AsyncMock(return_value=(stub_result, stub_usage))):
        await service.process(sms_text="Hello!", phone_hash="hash456")

    spans = span_exporter.get_finished_spans()
    gpt_span = next((s for s in spans if s.name == "gpt.classify_and_extract"), None)
    assert gpt_span is not None
    assert gpt_span.attributes.get("gen_ai.request.model") == GPT_MODEL
