from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core import database as db
from web.app import create_app


@pytest.mark.asyncio
async def test_chat_with_episode_stream_yields_deltas():
    """chat_with_episode_stream should yield text deltas then final messages."""
    from core.ai.chat import chat_with_episode_stream

    fake_chunks = ["Hello", " world", "!"]
    fake_messages = []  # simplified — we just check the final yield is a list

    # Mock StreamedRunResult — stream_text must return an async iterable
    async def fake_text_stream():
        for c in fake_chunks:
            yield c

    mock_result = MagicMock()
    mock_result.stream_text = MagicMock(return_value=fake_text_stream())
    mock_result.all_messages = MagicMock(return_value=fake_messages)

    # Mock agent.run_stream context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_result)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_agent = MagicMock()
    mock_agent.run_stream = MagicMock(return_value=mock_cm)

    with patch("core.ai.chat._get_agent", return_value=mock_agent):
        results = []
        async for chunk, msgs in chat_with_episode_stream(
            user_message="test",
            episode_title="Ep",
            podcast_title="Pod",
            transcript="transcript text",
            summary="summary text",
            history=[],
            lang="zh-TW",
        ):
            results.append((chunk, msgs))

    # Last item should be ("", list) — the final history yield
    assert results[-1][0] == ""
    assert isinstance(results[-1][1], list)
    # All other items should be text deltas
    deltas = [r[0] for r in results[:-1]]
    assert deltas == fake_chunks


async def _setup_episode(pg_fresh_db, monkeypatch):
    """Create user, podcast, subscription, and one episode."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    user_id = await db.get_or_create_user(8888, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://ep-test.com/feed.rss", "Ep Test Pod")
    sub_id = await db.add_subscription(user_id, "Ep Test Pod", "http://ep-test.com/feed.rss")
    await db.mark_episode_seen(user_id, podcast_id, "ep-x", title="Episode X", published_at="2024-03-01", summary="Summary X", transcript="Transcript X")
    episode_id = await db.get_episode_id(podcast_id, "ep-x")
    return sub_id, podcast_id, "ep-x", episode_id


@pytest.mark.asyncio
async def test_episode_list(pg_fresh_db, monkeypatch):
    sub_id, _, guid, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/subscriptions/{sub_id}/episodes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 0
    assert data["has_prev"] is False
    assert data["has_next"] is False
    assert len(data["episodes"]) == 1
    assert data["episodes"][0]["id"] == episode_id
    assert data["episodes"][0]["episode_guid"] == guid
    assert data["episodes"][0]["has_summary"] == 1


@pytest.mark.asyncio
async def test_episode_list_unknown_sub(pg_fresh_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/subscriptions/not-a-real-sub/episodes")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_episode_detail(pg_fresh_db, monkeypatch):
    _, _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/episodes/{episode_id}/detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Episode X"
    assert data["summary"] == "Summary X"
    assert data["transcript"] == "Transcript X"
    assert data["condensed_transcript"] is None


@pytest.mark.asyncio
async def test_episode_detail_not_found(pg_fresh_db, monkeypatch):
    await _setup_episode(pg_fresh_db, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/episodes/no-such-episode/detail")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_episode_detail_no_subscription_returns_403(pg_fresh_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    await db.get_or_create_user(8888, chat_id=0)
    other_user_id = await db.get_or_create_user(9999, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://other.com/feed.rss", "Other Pod")
    await db.mark_episode_seen(other_user_id, podcast_id, "other-guid", title="Other Episode")
    episode_id = await db.get_episode_id(podcast_id, "other-guid")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/episodes/{episode_id}/detail")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_episode_detail_with_guid_containing_slash(pg_fresh_db, monkeypatch):
    sub_id, podcast_id, _, _ = await _setup_episode(pg_fresh_db, monkeypatch)
    user_id = (await db.get_subscription_by_id(sub_id)).user_id
    guid = "tag:soundcloud,2010:tracks/2365547081"
    await db.mark_episode_seen(user_id, podcast_id, guid, title="SoundCloud Episode", transcript="Transcript")
    episode_id = await db.get_episode_id(podcast_id, guid)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/episodes/{episode_id}/detail")

    assert resp.status_code == 200
    assert resp.json()["title"] == "SoundCloud Episode"


@pytest.mark.asyncio
async def test_chat_endpoint_invalid_message_too_long(pg_fresh_db, monkeypatch):
    """message > 4000 chars → 400."""
    _, _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            f"/api/episodes/{episode_id}/chat",
            json={"message": "x" * 4001, "history": ""},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chat_endpoint_invalid_history(pg_fresh_db, monkeypatch):
    """Malformed history JSON → 400."""
    _, _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            f"/api/episodes/{episode_id}/chat",
            json={"message": "hello", "history": "not-valid-json[[["},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chat_endpoint_no_subscription_returns_403(pg_fresh_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    await db.get_or_create_user(8888, chat_id=0)
    other_user_id = await db.get_or_create_user(9999, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://chat-other.com/feed.rss", "Other Pod")
    await db.mark_episode_seen(other_user_id, podcast_id, "other-guid", title="Other Episode")
    episode_id = await db.get_episode_id(podcast_id, "other-guid")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            f"/api/episodes/{episode_id}/chat",
            json={"message": "hello", "history": ""},
        )
    assert resp.status_code == 403
