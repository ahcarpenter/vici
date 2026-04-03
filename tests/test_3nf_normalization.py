"""Tests for 3NF normalization: user_id removal from Job and WorkRequest models."""

import pytest
from pydantic import ValidationError

from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.work_requests.models import WorkRequest
from src.work_requests.schemas import WorkRequestCreate


class TestUserIdRemoved:
    """Verify user_id field is removed from Job and WorkRequest models and schemas."""

    def test_job_construction_without_user_id(self):
        """Job() construction without user_id kwarg does not raise."""
        job = Job(message_id=1, description="test", pay_rate=10.0)
        assert not hasattr(job, "user_id") or "user_id" not in Job.model_fields

    def test_work_request_construction_without_user_id(self):
        """WorkRequest() construction without user_id kwarg does not raise."""
        wr = WorkRequest(message_id=1, target_earnings=100.0, target_timeframe="week")
        assert not hasattr(wr, "user_id") or "user_id" not in WorkRequest.model_fields

    def test_job_create_rejects_user_id(self):
        """JobCreate(user_id=1, ...) raises ValidationError."""
        with pytest.raises(ValidationError):
            JobCreate(
                user_id=1,
                message_id=1,
                description="test",
                location="here",
                raw_sms="test sms",
            )

    def test_work_request_create_rejects_user_id(self):
        """WorkRequestCreate(user_id=1, ...) raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkRequestCreate(
                user_id=1,
                message_id=1,
                target_earnings=100.0,
                target_timeframe="week",
                raw_sms="test sms",
            )


@pytest.mark.asyncio
class TestFixturesWork:
    """Verify fixtures create entities without user_id."""

    async def test_make_job_flushes(self, make_job):
        """make_job fixture creates a Job that can be flushed without error."""
        job = await make_job()
        assert job.id is not None

    async def test_make_work_request_flushes(self, make_work_request):
        """make_work_request fixture creates a WorkRequest that can be flushed."""
        wr = await make_work_request()
        assert wr.id is not None
