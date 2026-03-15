from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared import database as db
from web.app import create_app


@pytest.mark.asyncio
async def test_get_subscriptions_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/subscriptions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_post_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")
    await db.init_db()
    app = create_app()

    mock_feed = MagicMock()
    mock_feed.feed.title = "Test Podcast"
    mock_feed.entries = []

    with patch("bot.feed.resolve_rss_url", new_callable=AsyncMock, return_value="http://example.com/feed.rss"), patch("bot.feed.fetch_feed", new_callable=AsyncMock, return_value=mock_feed):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/subscriptions", json={"rss_url": "http://example.com/feed.rss"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["podcast_title"] == "Test Podcast"
    assert "id" in data


@pytest.mark.asyncio
async def test_delete_subscription_success(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")
    await db.init_db()
    app = create_app()

    mock_feed = MagicMock()
    mock_feed.feed.title = "Del Test"
    mock_feed.entries = []

    with patch("bot.feed.resolve_rss_url", new_callable=AsyncMock, return_value="http://del.com/feed.rss"), patch("bot.feed.fetch_feed", new_callable=AsyncMock, return_value=mock_feed):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            create_resp = await c.post("/api/subscriptions", json={"rss_url": "http://del.com/feed.rss"})
            sub_id = create_resp.json()["id"]
            del_resp = await c.delete(f"/api/subscriptions/{sub_id}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_subscription_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/subscriptions/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")
    await db.init_db()
    app = create_app()

    mock_feed = MagicMock()
    mock_feed.feed.title = "Prompt Test"
    mock_feed.entries = []

    with patch("bot.feed.resolve_rss_url", new_callable=AsyncMock, return_value="http://prompt.com/feed.rss"), patch("bot.feed.fetch_feed", new_callable=AsyncMock, return_value=mock_feed):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            create_resp = await c.post("/api/subscriptions", json={"rss_url": "http://prompt.com/feed.rss"})
            sub_id = create_resp.json()["id"]
            put_resp = await c.put(f"/api/subscriptions/{sub_id}/prompt", json={"prompt": "Focus on tech topics"})
            assert put_resp.status_code == 200
            # Verify GET reflects the saved prompt
            list_resp = await c.get("/api/subscriptions")
            saved = next(s for s in list_resp.json() if s["id"] == sub_id)
            assert saved["custom_prompt"] == "Focus on tech topics"
