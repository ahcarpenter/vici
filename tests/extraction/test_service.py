from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import RateLimitError

from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    UnknownMessage,
    WorkerExtraction,
)
from src.extraction.service import ExtractionService
from tests.extraction.conftest import make_mock_openai_client


class MockExtractionSettings:
    openai_api_key = "test-key"
    gpt_model = "gpt-5.3-chat-latest"


class MockObservabilitySettings:
    braintrust_api_key = "test-bt-key"


class MockSettings:
    extraction = MockExtractionSettings()
    observability = MockObservabilitySettings()
    openai_api_key = "test-key"
    braintrust_api_key = "test-bt-key"


def _make_service(mock_client):
    """Construct ExtractionService with a pre-built mock client."""
    return ExtractionService(openai_client=mock_client, settings=MockSettings())


@pytest.mark.asyncio
async def test_classify_job():
    job = JobExtraction(
        description="Need a mover for Saturday",
        datetime_flexible=False,
        location="downtown Chicago",
        pay_type="hourly",
        pay_rate=25.0,
    )
    expected = ExtractionResult(message_type="job_posting", job=job)
    mock_client = make_mock_openai_client(expected)

    service = _make_service(mock_client)
    result = await service.process(
        "Need a mover for Saturday downtown Chicago", "hash123"
    )

    assert result.message_type == "job_posting"
    assert result.job is not None


@pytest.mark.asyncio
async def test_classify_worker():
    worker = WorkerExtraction(target_earnings=200.0, target_timeframe="today")
    expected = ExtractionResult(message_type="worker_goal", worker=worker)
    mock_client = make_mock_openai_client(expected)

    service = _make_service(mock_client)
    result = await service.process("I need $200 today", "hash123")

    assert result.message_type == "worker_goal"
    assert result.worker is not None
    assert result.worker.target_earnings == 200.0


@pytest.mark.asyncio
async def test_classify_unknown():
    unknown = UnknownMessage(
        reason="Message is a greeting with no job or goal information"
    )
    expected = ExtractionResult(message_type="unknown", unknown=unknown)
    mock_client = make_mock_openai_client(expected)

    service = _make_service(mock_client)
    result = await service.process("Hello", "hash123")

    assert result.message_type == "unknown"
    assert result.unknown is not None
    assert result.unknown.reason != ""


def test_braintrust_instrumentation():
    """ExtractionService accepts a pre-wrapped client (wrapping happens in caller)."""
    wrapped = AsyncMock()
    service = ExtractionService(openai_client=wrapped, settings=MockSettings())
    assert service._client is wrapped


@pytest.mark.asyncio
async def test_tenacity_retry_on_rate_limit():
    job = JobExtraction(
        description="Moving job",
        datetime_flexible=False,
        location="Chicago",
        pay_type="flat",
    )
    expected = ExtractionResult(message_type="job_posting", job=job)

    mock_message = MagicMock()
    mock_message.parsed = expected
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = mock_usage

    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=MagicMock(status_code=429, headers={}),
        body={
            "error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}
        },
    )

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(
        side_effect=[rate_limit_error, mock_completion]
    )

    service = _make_service(mock_client)
    # Should not raise — tenacity retries transparently
    result = await service.process("Moving job in Chicago", "hash123")

    assert result.message_type == "job_posting"
    assert mock_client.beta.chat.completions.parse.call_count == 2
