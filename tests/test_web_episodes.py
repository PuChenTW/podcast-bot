import pytest
from httpx import ASGITransport, AsyncClient

from shared import database as db
from web.app import create_app


async def _setup_episode(tmp_path, monkeypatch):
    """Helper: create user, podcast, subscription, and one episode. Returns (app, sub_id, podcast_id, guid)."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    user_id = await db.get_or_create_user(8888, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://ep-test.com/feed.rss", "Ep Test Pod")
    sub_id = await db.add_subscription(user_id, "Ep Test Pod", "http://ep-test.com/feed.rss")
    await db.mark_episode_seen(user_id, podcast_id, "ep-x", title="Episode X", published_at="2024-03-01", summary="Summary X", transcript="Transcript X")
    return sub_id, podcast_id, "ep-x"


@pytest.mark.asyncio
async def test_episode_list(tmp_path, monkeypatch):
    sub_id, podcast_id, guid = await _setup_episode(tmp_path, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/subscriptions/{sub_id}/episodes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["episode_guid"] == guid
    assert data[0]["has_summary"] == 1


@pytest.mark.asyncio
async def test_episode_list_unknown_sub(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test2.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/subscriptions/not-a-real-sub/episodes")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_episode_detail(tmp_path, monkeypatch):
    sub_id, podcast_id, guid = await _setup_episode(tmp_path, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/podcasts/{podcast_id}/episodes/{guid}/detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Episode X"
    assert data["summary"] == "Summary X"
    assert data["transcript"] == "Transcript X"
    assert data["condensed_transcript"] is None


@pytest.mark.asyncio
async def test_episode_detail_not_found(tmp_path, monkeypatch):
    # User has a subscription to the podcast but the episode guid doesn't exist → 404
    sub_id, podcast_id, guid = await _setup_episode(tmp_path, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/podcasts/{podcast_id}/episodes/no-such-guid/detail")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_episode_detail_no_subscription_returns_403(tmp_path, monkeypatch):
    # User has no subscription to the podcast → 403
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test3.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/podcasts/unsubscribed-pod/episodes/any-guid/detail")
    assert resp.status_code == 403
