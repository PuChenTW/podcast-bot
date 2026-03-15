import pytest

import bot.config as _config
import bot.database as db_module
from bot.config import Settings
from bot.database import init_db


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    fake = Settings(
        telegram_bot_token="fake-token",
        gemini_api_key="fake-gemini-key",
        gemini_model="gemini-flash-lite-latest",
        whisper_model="base",
        poll_interval_seconds=21600,
        admin_user_id=123,
        groq_api_key=None,
        transcriber_backend="whisper",
    )
    monkeypatch.setattr(_config, "_settings", fake)


@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", path)
    await init_db()
    yield path


async def async_gen(*chunks):
    for c in chunks:
        yield c
