"""Tests for 3NF normalization: user_id removal from Job and WorkGoal models."""

import pytest

from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.work_goals.models import WorkGoal
from src.work_goals.schemas import WorkGoalCreate


class TestUserIdRemoved:
    """Verify user_id field is removed from Job and WorkGoal models and schemas."""

    def test_job_construction_without_user_id(self):
        """Job() construction without user_id kwarg does not raise."""
        job = Job(message_id=1, description="test", pay_rate=10.0)
        assert not hasattr(job, "user_id") or "user_id" not in Job.model_fields

    def test_work_goal_construction_without_user_id(self):
        """WorkGoal() construction without user_id kwarg does not raise."""
        wg = WorkGoal(message_id=1, target_earnings=100.0, target_timeframe="week")
        assert not hasattr(wg, "user_id") or "user_id" not in WorkGoal.model_fields

    def test_job_create_has_no_user_id_field(self):
        """JobCreate schema has no user_id field defined."""
        assert "user_id" not in JobCreate.model_fields

    def test_work_goal_create_has_no_user_id_field(self):
        """WorkGoalCreate schema has no user_id field defined."""
        assert "user_id" not in WorkGoalCreate.model_fields


@pytest.mark.asyncio
class TestFixturesWork:
    """Verify fixtures create entities without user_id."""

    async def test_make_job_flushes(self, make_job):
        """make_job fixture creates a Job that can be flushed without error."""
        job = await make_job()
        assert job.id is not None

    async def test_make_work_goal_flushes(self, make_work_goal):
        """make_work_goal fixture creates a WorkGoal that can be flushed."""
        wg = await make_work_goal()
        assert wg.id is not None
