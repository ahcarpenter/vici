import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from unittest.mock import AsyncMock, patch

from src.database import get_session
from src.main import app

DATABASE_URL_TEST = "sqlite+aiosqlite:///./test.db"


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
async def client(async_session):
    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def mock_twilio_validator():
    with patch("twilio.request_validator.RequestValidator.validate", return_value=True) as m:
        yield m


@pytest.fixture
def mock_inngest_client():
    with patch("src.main.inngest_client.send", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture(autouse=True)
def _auto_mock_inngest_send():
    """Auto-mock inngest_client.send for all tests to prevent real HTTP calls."""
    with patch("src.main.inngest_client.send", new_callable=AsyncMock):
        yield
