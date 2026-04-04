import hashlib
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import src.models  # noqa: F401 — ensure all SQLModel tables registered before create_all
from src.config import get_settings
from src.database import get_engine, get_session
from src.jobs.models import Job
from src.main import create_app
from src.sms.models import Message
from src.users.models import User
from src.work_goals.models import WorkGoal

DATABASE_URL_TEST = "sqlite+aiosqlite:///:memory:"

# Remove stale test.db if it exists on disk
if os.path.exists("test.db"):
    os.remove("test.db")


@pytest.fixture(autouse=True, scope="session")
def _prometheus_registry_isolation():
    """Prevent duplicate metric registration errors across test session.

    src/metrics.py uses module-level singletons registered on import.
    This fixture is a no-op sentinel — the real protection is that metrics.py
    registers once at module import time (session scope prevents re-import).
    If tests see ValueError: Duplicated timeseries, add unregister logic here.
    """
    yield


@pytest.fixture(scope="session", autouse=True)
def _test_env():
    # Ensure cached settings see consistent values for the full test session.
    os.environ.setdefault("DATABASE_URL", DATABASE_URL_TEST)
    os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_twilio_auth_token")
    os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_test")
    os.environ.setdefault("WEBHOOK_BASE_URL", "http://localhost:8000")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test")
    os.environ.setdefault("PINECONE_API_KEY", "pc-test")
    os.environ.setdefault("TEMPORAL_ADDRESS", "localhost:7233")
    os.environ.setdefault("ENV", "test")

    # Clear caches in case tests are re-run in-process.
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(DATABASE_URL_TEST, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(async_session, app):
    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _auto_mock_temporal_client(app):
    """Auto-mock temporal client on app.state for all tests."""
    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(return_value="wf-run-id")
    app.state.temporal_client = mock_client
    yield mock_client


@pytest.fixture
def mock_twilio_validator():
    with patch(
        "twilio.request_validator.RequestValidator.validate",
        return_value=True,
    ) as m:
        yield m


@pytest_asyncio.fixture
async def make_user(async_session):
    _counter = {"n": 0}

    async def _factory(phone_hash: str | None = None, phone_e164: str | None = None) -> User:
        if phone_hash is None:
            _counter["n"] += 1
            phone_hash = hashlib.sha256(f"phone_{_counter['n']}".encode()).hexdigest()
        user = User(phone_hash=phone_hash, phone_e164=phone_e164)
        async_session.add(user)
        await async_session.flush()
        return user

    return _factory


@pytest_asyncio.fixture
async def make_message(async_session, make_user):
    async def _factory(**kwargs) -> Message:
        user = kwargs.pop("user", None)
        if user is None:
            user = await make_user()
        message = Message(
            message_sid=kwargs.get("message_sid", "test-sid-" + str(id(kwargs))),
            user_id=kwargs.get("user_id", user.id),
            body=kwargs.get("body", "test body"),
        )
        async_session.add(message)
        await async_session.flush()
        return message

    return _factory


@pytest_asyncio.fixture
async def make_job(async_session, make_user, make_message):
    async def _factory(**kwargs) -> Job:
        user = kwargs.pop("user", None)
        if user is None:
            user = await make_user()
        message = kwargs.pop("message", None)
        if message is None:
            message = await make_message(user=user)
        job = Job(
            message_id=kwargs.get("message_id", message.id),
            description=kwargs.get("description", "Test job description"),
            location=kwargs.get("location", None),
            pay_rate=kwargs.get("pay_rate", 25.0),
            pay_type=kwargs.get("pay_type", "hourly"),
            estimated_duration_hours=kwargs.get("estimated_duration_hours", None),
            ideal_datetime=kwargs.get("ideal_datetime", None),
            datetime_flexible=kwargs.get("datetime_flexible", None),
            status=kwargs.get("status", "available"),
        )
        async_session.add(job)
        await async_session.flush()
        return job

    return _factory


@pytest_asyncio.fixture
async def make_work_goal(async_session, make_user, make_message):
    async def _factory(**kwargs) -> WorkGoal:
        user = kwargs.pop("user", None)
        if user is None:
            user = await make_user()
        message = kwargs.pop("message", None)
        if message is None:
            message = await make_message(user=user)
        work_goal = WorkGoal(
            message_id=kwargs.get("message_id", message.id),
            target_earnings=kwargs.get("target_earnings", 500.0),
            target_timeframe=kwargs.get("target_timeframe", "this week"),
        )
        async_session.add(work_goal)
        await async_session.flush()
        return work_goal

    return _factory
