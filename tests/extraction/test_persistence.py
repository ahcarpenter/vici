"""
Tests for Plan 02-02: persistence layer for extraction results.
Tests: JobRepository.create, WorkRequestRepository.create.

Note: Pinecone integration tests have moved to tests/test_pipeline_orchestrator.py
as PipelineOrchestrator now owns all storage orchestration.
"""
import hashlib

import pytest
import pytest_asyncio

from src.jobs.repository import JobRepository
from src.jobs.schemas import JobCreate
from src.sms.models import Message
from src.users.models import User
from src.work_requests.repository import WorkRequestRepository
from src.work_requests.schemas import WorkRequestCreate

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def user_and_message(async_session, request):
    """Create a User + Message row for FK references, unique per test."""
    unique_seed = request.node.name.encode()
    phone_hash = hashlib.sha256(unique_seed).hexdigest()
    msg_sid = f"SM{hashlib.md5(unique_seed).hexdigest()[:10]}"

    user = User(phone_hash=phone_hash)
    async_session.add(user)
    await async_session.flush()

    msg = Message(
        message_sid=msg_sid,
        user_id=user.id,
        body="Need a mover for Saturday",
    )
    async_session.add(msg)
    await async_session.flush()
    return user, msg


# ── Task 1 tests: repositories ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_persistence(async_session, user_and_message):
    """JobRepository.create inserts a job row and returns Job with id populated."""
    user, msg = user_and_message

    job_create = JobCreate(
        message_id=msg.id,
        description="Need a mover for Saturday",
        location="downtown Chicago",
        pay_rate=25.0,
        pay_type="hourly",
        datetime_flexible=False,
        raw_sms="Need a mover for Saturday downtown Chicago $25/hr",
    )
    job = await JobRepository.create(async_session, job_create)

    assert job.id is not None
    assert job.description == "Need a mover for Saturday"
    assert job.pay_type == "hourly"
    assert job.message_id == msg.id


@pytest.mark.asyncio
async def test_worker_persistence(async_session, user_and_message):
    """WorkRequestRepository.create inserts a work_request row and returns it with id."""
    user, msg = user_and_message

    # Need a separate message for work_request (message_id has unique constraint)
    msg2 = Message(
        message_sid=f"SM{hashlib.md5(b'worker_persistence_msg2').hexdigest()[:10]}",
        user_id=user.id,
        body="I need $200 today",
    )
    async_session.add(msg2)
    await async_session.flush()

    wr_create = WorkRequestCreate(
        message_id=msg2.id,
        target_earnings=200.0,
        target_timeframe="today",
        raw_sms="I need $200 today",
    )
    wr = await WorkRequestRepository.create(async_session, wr_create)

    assert wr.id is not None
    assert wr.target_earnings == 200.0
    assert wr.target_timeframe == "today"
    assert wr.message_id == msg2.id
