import pytest

import bot.database as db_module
from bot.database import init_db


@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", path)
    await init_db()
    yield path


async def async_gen(*chunks):
    for c in chunks:
        yield c
