"""Tests for src/metrics.py — METRICS-01, METRICS-02, METRICS-03."""

import pytest

# ── Task 1: Registry and singleton tests ────────────────────────────────────


def test_import_metrics_does_not_raise_value_error():
    """Importing src.metrics twice does not raise ValueError (duplicate registration)."""
    # Second import hits module cache — no re-registration, no ValueError
    import src.metrics  # noqa: F401  # noqa: F401, F811


def test_gpt_calls_total_increments():
    from src.metrics import gpt_calls_total
    before = gpt_calls_total.labels(classification_result="job")._value.get()
    gpt_calls_total.labels(classification_result="job").inc()
    after = gpt_calls_total.labels(classification_result="job")._value.get()
    assert after - before == 1.0


def test_gpt_call_duration_seconds_observe():
    from src.metrics import gpt_call_duration_seconds
    # observe() should not raise
    gpt_call_duration_seconds.observe(1.5)


def test_pinecone_sync_queue_depth_settable():
    from src.metrics import pinecone_sync_queue_depth
    pinecone_sync_queue_depth.set(42)
    samples = list(pinecone_sync_queue_depth.collect())[0].samples
    assert any(s.value == 42 for s in samples)


def test_temporal_queue_depth_settable():
    from src.metrics import temporal_queue_depth
    # Should not raise
    temporal_queue_depth.set(0)


# ── Task 2: ExtractionService instrumentation tests ─────────────────────────


@pytest.mark.asyncio
async def test_gpt_calls_total_increments_after_process():
    """After process(), gpt_calls_total increments with classification_result label."""
    from unittest.mock import AsyncMock, MagicMock

    from src.extraction.service import ExtractionService
    from src.metrics import gpt_calls_total

    mock_result = MagicMock()
    mock_result.message_type = "job"
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5

    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.extraction.gpt_model = "gpt-5.3-chat-latest"

    service = ExtractionService(openai_client=mock_client, settings=mock_settings)
    service._call_with_retry = AsyncMock(return_value=(mock_result, mock_usage))

    before = gpt_calls_total.labels(classification_result="job")._value.get()
    await service.process("I need a plumber", "abc123")
    after = gpt_calls_total.labels(classification_result="job")._value.get()

    assert after - before == 1.0


@pytest.mark.asyncio
async def test_gpt_call_duration_seconds_recorded_after_process():
    """After process(), gpt_call_duration_seconds has recorded an observation."""
    from unittest.mock import AsyncMock, MagicMock

    from src.extraction.service import ExtractionService
    from src.metrics import gpt_call_duration_seconds

    mock_result = MagicMock()
    mock_result.message_type = "worker_goal"
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 8
    mock_usage.completion_tokens = 4

    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.extraction.gpt_model = "gpt-5.3-chat-latest"

    service = ExtractionService(openai_client=mock_client, settings=mock_settings)
    service._call_with_retry = AsyncMock(return_value=(mock_result, mock_usage))

    # Get current count before
    before_count = None
    for metric_family in gpt_call_duration_seconds.collect():
        for sample in metric_family.samples:
            if sample.name == "gpt_call_duration_seconds_count":
                before_count = sample.value

    await service.process("I want 500 by Friday", "def456")

    after_count = None
    for metric_family in gpt_call_duration_seconds.collect():
        for sample in metric_family.samples:
            if sample.name == "gpt_call_duration_seconds_count":
                after_count = sample.value

    assert after_count - before_count == 1.0


@pytest.mark.asyncio
async def test_gpt_token_counters_increment_after_process():
    """gpt_input_tokens_total and gpt_output_tokens_total increment by usage counts."""
    from unittest.mock import AsyncMock, MagicMock

    from src.extraction.service import ExtractionService
    from src.metrics import gpt_input_tokens_total, gpt_output_tokens_total

    mock_result = MagicMock()
    mock_result.message_type = "unknown"
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 15
    mock_usage.completion_tokens = 7

    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.extraction.gpt_model = "gpt-5.3-chat-latest"

    service = ExtractionService(openai_client=mock_client, settings=mock_settings)
    service._call_with_retry = AsyncMock(return_value=(mock_result, mock_usage))

    before_in = gpt_input_tokens_total._value.get()
    before_out = gpt_output_tokens_total._value.get()

    await service.process("random text", "ghi789")

    assert gpt_input_tokens_total._value.get() - before_in == 15.0
    assert gpt_output_tokens_total._value.get() - before_out == 7.0


# ── Task 3: Pinecone gauge test ──────────────────────────────────────────────


def test_pinecone_gauge_settable():
    from src.metrics import pinecone_sync_queue_depth
    pinecone_sync_queue_depth.set(7)
    samples = list(pinecone_sync_queue_depth.collect())[0].samples
    assert any(s.value == 7 for s in samples)


# ── Task 4: pipeline_failures_total tests (plan 02.5-04) ────────────────────


def test_pipeline_failures_total_is_counter():
    from prometheus_client import Counter

    from src.metrics import pipeline_failures_total
    assert isinstance(pipeline_failures_total, Counter)


def test_pipeline_failures_total_has_function_label():
    from src.metrics import pipeline_failures_total
    # Calling with label should not raise
    pipeline_failures_total.labels(function="process-message").inc()
