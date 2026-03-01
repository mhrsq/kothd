"""
KoTH CTF Platform — Test Configuration & Fixtures

Uses SQLite async in-memory database for fast isolated tests.
All DB state is created fresh per test function.
"""
import asyncio
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Override env BEFORE importing app modules ────────────────────────────────
os.environ.update({
    "POSTGRES_PASSWORD": "testpass",
    "API_SECRET_KEY": "test-secret-key",
    "API_ADMIN_TOKEN": "test-admin-token",
    "REDIS_PASSWORD": "testredis",
    "REGISTRATION_CODE": "TESTCODE",
    "REGISTRATION_ENABLED": "true",
    "POSTGRES_HOST": "localhost",
    "REDIS_HOST": "localhost",
})

from app.config import get_settings  # noqa: E402

# Clear cached settings so our env overrides take effect
get_settings.cache_clear()

from app.database import Base, get_db  # noqa: E402
from app.models import GameConfig  # noqa: E402

# ── Async engine (aiosqlite in-memory) ───────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    engine_test, class_=AsyncSession, expire_on_commit=False
)


# ── Event loop fixture ──────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Database setup per test ──────────────────────────────────────────────────
@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create tables, seed game_config, yield session, then drop."""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        # Seed required game_config rows
        defaults = [
            GameConfig(key="game_status", value="not_started", description="Current game state"),
            GameConfig(key="current_tick", value="0", description="Current tick number"),
            GameConfig(key="tick_interval", value="60", description="Seconds between ticks"),
            GameConfig(key="grace_period", value="300", description="Grace period in seconds"),
            GameConfig(key="game_duration", value="21600", description="Game duration in seconds"),
            GameConfig(key="freeze_before_end", value="1800", description="Freeze scoreboard N seconds before end"),
            GameConfig(key="base_points", value="10", description="Base points per tick"),
            GameConfig(key="first_blood_bonus", value="50", description="First blood bonus points"),
            GameConfig(key="defense_streak_bonus", value="5", description="Defense streak bonus"),
            GameConfig(key="registration_enabled", value="true", description="Registration enabled"),
            GameConfig(key="registration_code", value="TESTCODE", description="Registration code"),
        ]
        session.add_all(defaults)
        await session.commit()

        yield session

    # Teardown — drop all tables
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── FastAPI test client ──────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTPX async client wired to the FastAPI app with DB overridden.
    Mocks Redis and the lifespan to avoid real connections.
    """
    from app.main import app

    # Override the DB dependency
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Mock Redis on app state
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Inject mock redis
        app.state.redis = mock_redis
        yield ac

    app.dependency_overrides.clear()


# ── Convenience fixtures ─────────────────────────────────────────────────────
@pytest.fixture
def admin_headers() -> dict:
    """Headers for admin-authenticated requests."""
    return {"X-Admin-Token": "test-admin-token"}


@pytest.fixture
def registration_payload() -> dict:
    """Default team registration payload."""
    return {
        "name": "TestTeam",
        "display_name": "Test Team",
        "category": "default",
        "registration_code": "TESTCODE",
    }
