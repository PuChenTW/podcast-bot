import asyncpg
import pytest
from pytest_mock_resources import create_postgres_fixture

import core.config as _config
import core.database as db_module
from core.config import Settings
from core.database import init_db

# Module-level pmr fixture definition — the pmr pattern.
# scope="function" (default): each test gets a fresh DB via template cloning.
_postgres = create_postgres_fixture()


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    fake = Settings(
        telegram_bot_token="fake-token",
        gemini_api_key="fake-gemini-key",
        ai_model="google-gla:gemini-flash-lite-latest",
        whisper_model="base",
        poll_interval_seconds=21600,
        admin_user_id=123,
        groq_api_key=None,
        transcriber_backend="whisper",
        summarizer_model="google-gla:gemini-flash-lite-latest",
        chat_model="google-gla:gemini-flash-lite-latest",
        corrector_model="google-gla:gemini-flash-lite-latest",
        prompt_engineer_model="google-gla:gemini-flash-lite-latest",
        condenser_model="google-gla:gemini-flash-lite-latest",
        database_url="postgresql://fake@localhost/fake",
    )
    monkeypatch.setattr(_config, "_settings", fake)


@pytest.fixture
async def tmp_db(monkeypatch, _postgres):
    """Fixture: fresh PostgreSQL database with all migrations applied. Patches db._pool."""
    creds = _postgres.pmr_credentials
    dsn = f"postgresql://{creds.username}:{creds.password}@{creds.host}:{creds.port}/{creds.database}"
    pool = await asyncpg.create_pool(dsn)
    monkeypatch.setattr(db_module, "_pool", pool)
    await init_db()
    yield dsn
    await pool.close()
    monkeypatch.setattr(db_module, "_pool", None)


@pytest.fixture
async def pg_fresh_db(monkeypatch, _postgres):
    """Fixture: fresh PostgreSQL database WITHOUT migrations applied. Patches db._pool.
    Use for tests that call init_db() themselves (e.g. web tests via app lifespan)."""
    creds = _postgres.pmr_credentials
    dsn = f"postgresql://{creds.username}:{creds.password}@{creds.host}:{creds.port}/{creds.database}"
    pool = await asyncpg.create_pool(dsn)
    monkeypatch.setattr(db_module, "_pool", pool)
    yield dsn
    await pool.close()
    monkeypatch.setattr(db_module, "_pool", None)


async def async_gen(*chunks):
    for c in chunks:
        yield c
