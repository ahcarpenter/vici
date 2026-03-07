import hashlib
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from src.config import get_settings
from src.database import get_engine, get_session
from src.inngest_client import get_inngest_client
from src.main import create_app
from src.users.models import User

DATABASE_URL_TEST = "sqlite+aiosqlite:///:memory:"

# Remove stale test.db if it exists on disk
if os.path.exists("test.db"):
    os.remove("test.db")


@pytest.fixture(scope="session", autouse=True)
def _test_env():
    # Ensure cached settings see consistent values for the full test session.
    os.environ.setdefault("DATABASE_URL", DATABASE_URL_TEST)
    os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_twilio_auth_token")
    os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_test")
    os.environ.setdefault("WEBHOOK_BASE_URL", "http://localhost:8000")

    # Clear caches in case tests are re-run in-process.
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_inngest_client.cache_clear()


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


@pytest.fixture
def mock_twilio_validator():
    with patch(
        "twilio.request_validator.RequestValidator.validate",
        return_value=True,
    ) as m:
        yield m


@pytest.fixture
def mock_inngest_client():
    with patch.object(get_inngest_client(), "send", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture(autouse=True)
def _auto_mock_inngest_send():
    """Auto-mock inngest_client.send for all tests to prevent real HTTP calls."""
    with patch.object(get_inngest_client(), "send", new_callable=AsyncMock):
        yield


@pytest_asyncio.fixture
async def make_user(async_session):
    async def _factory(phone_hash: str | None = None) -> User:
        if phone_hash is None:
            phone_hash = hashlib.sha256(b"default_phone").hexdigest()
        user = User(phone_hash=phone_hash)
        async_session.add(user)
        await async_session.flush()
        return user

    return _factory
