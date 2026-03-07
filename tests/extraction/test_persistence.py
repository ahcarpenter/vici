"""
Tests for Plan 02-02: persistence layer for extraction results.
Tests: JobRepository.create, WorkRequestRepository.create, ExtractionService.process() with storage.
"""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    WorkerExtraction,
    UnknownMessage,
)
from src.extraction.service import ExtractionService
from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.jobs.repository import JobRepository
from src.work_requests.schemas import WorkRequestCreate
from src.work_requests.repository import WorkRequestRepository
from src.sms.models import Message
from src.users.models import User
from tests.extraction.conftest import make_mock_openai_client


class MockSettings:
    openai_api_key = "test-key"
    braintrust_api_key = "test-bt-key"
    pinecone_api_key = "test-pc-key"
    pinecone_index_host = "https://test.svc.pinecone.io"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def user_and_message(async_session, request):
    """Create a User + Message row for FK references, unique per test."""
    # Use request node name to generate unique identifiers per test
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
        user_id=user.id,
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
    assert job.user_id == user.id
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
        user_id=user.id,
        message_id=msg2.id,
        target_earnings=200.0,
        target_timeframe="today",
        raw_sms="I need $200 today",
    )
    wr = await WorkRequestRepository.create(async_session, wr_create)

    assert wr.id is not None
    assert wr.target_earnings == 200.0
    assert wr.target_timeframe == "today"
    assert wr.user_id == user.id
    assert wr.message_id == msg2.id


# ── Task 2 tests: ExtractionService with storage wired ───────────────────────


@pytest.mark.asyncio
async def test_pinecone_upsert(async_session, user_and_message):
    """ExtractionService.process() attempts Pinecone upsert after job commit."""
    user, msg = user_and_message

    # Need a fresh message for this test
    msg3 = Message(
        message_sid=f"SM{hashlib.md5(b'pinecone_upsert_msg3').hexdigest()[:10]}",
        user_id=user.id,
        body="Moving job on Friday $30/hr",
    )
    async_session.add(msg3)
    await async_session.flush()

    job = JobExtraction(
        description="Moving job on Friday",
        datetime_flexible=False,
        location="Chicago",
        pay_type="hourly",
        pay_rate=30.0,
    )
    expected = ExtractionResult(message_type="job_posting", job=job)
    mock_client = make_mock_openai_client(expected)

    with (
        patch("src.extraction.service.wrap_openai", return_value=mock_client),
        patch("src.extraction.pinecone_client.PineconeAsyncio") as mock_pc,
    ):
        # Set up PineconeAsyncio async context manager
        mock_pc_instance = AsyncMock()
        mock_pc_instance.__aenter__ = AsyncMock(return_value=mock_pc_instance)
        mock_pc_instance.__aexit__ = AsyncMock(return_value=None)
        mock_index = AsyncMock()
        mock_index.__aenter__ = AsyncMock(return_value=mock_index)
        mock_index.__aexit__ = AsyncMock(return_value=None)
        mock_pc_instance.IndexAsyncio = MagicMock(return_value=mock_index)
        mock_pc.return_value = mock_pc_instance

        service = ExtractionService(MockSettings())
        service._client = mock_client
        result = await service.process(
            sms_text="Moving job on Friday $30/hr",
            phone_hash=user.phone_hash,
            message_id=msg3.id,
            user_id=user.id,
            session=async_session,
        )

    assert result.message_type == "job_posting"
    # Verify Pinecone upsert was called
    mock_index.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_pinecone_failure_enqueues_sync(async_session, user_and_message):
    """On Pinecone failure, ExtractionService logs error and writes pinecone_sync_queue row."""
    user, msg = user_and_message

    msg4 = Message(
        message_sid=f"SM{hashlib.md5(b'pinecone_failure_msg4').hexdigest()[:10]}",
        user_id=user.id,
        body="Painting job downtown $500 flat",
    )
    async_session.add(msg4)
    await async_session.flush()

    job = JobExtraction(
        description="Painting job downtown",
        datetime_flexible=True,
        location="downtown",
        pay_type="flat",
        pay_rate=500.0,
    )
    expected = ExtractionResult(message_type="job_posting", job=job)
    mock_client = make_mock_openai_client(expected)

    with (
        patch("src.extraction.service.wrap_openai", return_value=mock_client),
        patch(
            "src.extraction.pinecone_client.PineconeAsyncio",
            side_effect=Exception("Pinecone unavailable"),
        ),
    ):
        service = ExtractionService(MockSettings())
        service._client = mock_client
        result = await service.process(
            sms_text="Painting job downtown $500 flat",
            phone_hash=user.phone_hash,
            message_id=msg4.id,
            user_id=user.id,
            session=async_session,
        )

    assert result.message_type == "job_posting"
    # Verify pinecone_sync_queue row was created
    from sqlalchemy import text as sa_text
    row = await async_session.execute(
        sa_text("SELECT * FROM pinecone_sync_queue WHERE status = 'pending'")
    )
    rows = row.fetchall()
    assert len(rows) >= 1
