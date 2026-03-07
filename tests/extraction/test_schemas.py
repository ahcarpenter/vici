import pytest
from pydantic import ValidationError

from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    UnknownMessage,
    WorkerExtraction,
)


def test_job_extraction_schema():
    job = JobExtraction(
        description="x",
        datetime_flexible=False,
        location="y",
        pay_type="hourly",
    )
    assert job.description == "x"
    assert job.datetime_flexible is False
    assert job.location == "y"
    assert job.pay_type == "hourly"
    # Optional fields default to None
    assert job.ideal_datetime is None
    assert job.raw_datetime_text is None
    assert job.inferred_timezone is None
    assert job.estimated_duration_hours is None
    assert job.raw_duration_text is None
    assert job.pay_rate is None


def test_job_extraction_rejects_default_on_required():
    with pytest.raises(ValidationError):
        JobExtraction()


def test_worker_extraction_schema():
    worker = WorkerExtraction(target_earnings=200.0, target_timeframe="today")
    assert worker.target_earnings == 200.0
    assert worker.target_timeframe == "today"


def test_unknown_message_schema():
    unknown = UnknownMessage(reason="unclear")
    assert unknown.reason == "unclear"


def test_extraction_result_job_branch():
    job = JobExtraction(
        description="Need a mover",
        datetime_flexible=True,
        location="downtown Chicago",
        pay_type="hourly",
    )
    result = ExtractionResult(message_type="job_posting", job=job)
    assert result.message_type == "job_posting"
    assert result.job is not None
    assert result.worker is None
    assert result.unknown is None
