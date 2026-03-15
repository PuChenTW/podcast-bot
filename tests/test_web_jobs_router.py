import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared import database as db
from web.app import create_app


async def _setup_with_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "7777")
    await db.init_db()
    user_id = await db.get_or_create_user(7777, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://regen-test.com/feed.rss", "Regen Pod")
    await db.add_subscription(user_id, "Regen Pod", "http://regen-test.com/feed.rss")
    await db.mark_episode_seen(user_id, podcast_id, "ep-r", title="Regen Ep", published_at="2024-04-01", transcript="Some transcript")
    return podcast_id, "ep-r"


@pytest.mark.asyncio
async def test_regenerate_returns_job_id(tmp_path, monkeypatch):
    podcast_id, guid = await _setup_with_episode(tmp_path, monkeypatch)
    app = create_app()

    with patch("bot.ai.summarizer.summarize_episode", new_callable=AsyncMock, return_value="New summary"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/podcasts/{podcast_id}/episodes/{guid}/regenerate")
            assert resp.status_code == 202
            data = resp.json()
            assert "job_id" in data

            # Poll until done (max 10 attempts × 0.1 s = 1 s — mock is instant)
            job_id = data["job_id"]
            for _ in range(10):
                await asyncio.sleep(0.1)
                poll = await c.get(f"/api/jobs/{job_id}")
                if poll.json()["status"] in ("done", "error"):
                    break
            assert poll.json()["status"] == "done"


@pytest.mark.asyncio
async def test_regenerate_no_subscription_returns_403(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test2.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "7777")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/podcasts/fakepod/episodes/fakeguid/regenerate")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_job_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test3.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "7777")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/jobs/no-such-job")
    assert resp.status_code == 404
