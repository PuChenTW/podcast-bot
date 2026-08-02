import asyncio

import asyncpg
import pytest
from pytest_mock_resources import PostgresConfig, create_postgres_fixture

import core.config as _config
import core.database as db_module
from core.config import Settings
from core.database import init_db

# session-scoped: one DB per xdist worker, not one per test.
# This avoids concurrent CREATE DATABASE calls that crash the PMR container.
_postgres = create_postgres_fixture(scope="session")
_TABLES = ["api_jobs", "user_episodes", "episodes", "subscriptions", "podcasts", "users"]


@pytest.fixture(scope="session")
def pmr_postgres_config(worker_id):
    base_port = 6544
    offset = 0 if worker_id == "master" else int(worker_id[2:]) + 1
    return PostgresConfig(port=base_port + offset)


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    fake = Settings(
        telegram_bot_token="fake-token",
        gemini_api_key="fake-gemini-key",
        ai_model="google-gla:gemini-flash-lite-latest",
        whisper_model="base",
        nemotron_model_dir=None,
        nemotron_language="auto",
        poll_interval_seconds=21600,
        groq_api_key=None,
        transcriber_backend="whisper",
        summarizer_model="google-gla:gemini-flash-lite-latest",
        chat_model="google-gla:gemini-flash-lite-latest",
        corrector_model="google-gla:gemini-flash-lite-latest",
        prompt_engineer_model="google-gla:gemini-flash-lite-latest",
        condenser_model="google-gla:gemini-flash-lite-latest",
        database_url="postgresql://fake@localhost/fake",
        google_drive_enabled=True,
        google_drive_token_path=None,
        google_drive_folder_id=None,
    )
    monkeypatch.setattr(_config, "_settings", fake)


@pytest.fixture(scope="session")
def _session_dsn(_postgres):
    """Return the DSN for the session-scoped PMR database."""
    creds = _postgres.pmr_credentials
    return f"postgresql://{creds.username}:{creds.password}@{creds.host}:{creds.port}/{creds.database}"


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(_session_dsn):
    """Apply migrations once per worker session using a short-lived event loop."""

    async def _run():
        pool = await asyncpg.create_pool(_session_dsn)
        db_module._pool = pool
        await init_db()
        await pool.close()
        db_module._pool = None

    asyncio.run(_run())


@pytest.fixture
async def tmp_db(monkeypatch, _session_dsn, _apply_migrations):
    """Fixture: fresh tables (truncated) with a new per-test pool."""
    pool = await asyncpg.create_pool(_session_dsn)
    monkeypatch.setattr(db_module, "_pool", pool)
    async with pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    yield
    await pool.close()
    monkeypatch.setattr(db_module, "_pool", None)


@pytest.fixture
async def pg_fresh_db(monkeypatch, _session_dsn, _apply_migrations):
    """Fixture: fresh tables with a new per-test pool.
    Use for tests that call init_db() themselves (e.g. web tests via app lifespan)."""
    pool = await asyncpg.create_pool(_session_dsn)
    monkeypatch.setattr(db_module, "_pool", pool)
    async with pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    yield
    await pool.close()
    monkeypatch.setattr(db_module, "_pool", None)


async def async_gen(*chunks):
    for c in chunks:
        yield c
