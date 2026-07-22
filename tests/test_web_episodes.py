from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core import database as db
from web.app import create_app


async def _setup_episode(pg_fresh_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    user_id = await db.get_or_create_user(8888, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://ep-test.com/feed.rss", "Ep Test Pod")
    await db.add_subscription(user_id, "Ep Test Pod", "http://ep-test.com/feed.rss")
    await db.mark_episode_seen(
        user_id,
        podcast_id,
        "ep-x",
        title="Episode X",
        published_at="2024-03-01",
        summary="Summary X",
        transcript="Transcript X",
        description="Description X",
    )
    return user_id, podcast_id, await db.get_episode_id(podcast_id, "ep-x")


@pytest.mark.asyncio
async def test_episode_list_uses_cursor_shape(pg_fresh_db, monkeypatch):
    _, podcast_id, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get(f"/api/v1/podcasts/{podcast_id}/episodes")
    assert response.status_code == 200
    assert response.json()["next_cursor"] is None
    assert response.json()["items"] == [
        {
            "id": episode_id,
            "title": "Episode X",
            "published_at": "2024-03-01T00:00:00Z",
            "has_summary": True,
            "has_transcript": True,
        }
    ]


@pytest.mark.asyncio
async def test_episode_cursor_has_no_duplicates(pg_fresh_db, monkeypatch):
    user_id, podcast_id, first_episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    await db.mark_episode_seen(user_id, podcast_id, "ep-y", title="Episode Y", published_at="2024-02-01")
    await db.mark_episode_seen(user_id, podcast_id, "ep-z", title="Episode Z", published_at="2024-01-01")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        first = await client.get(f"/api/v1/podcasts/{podcast_id}/episodes?limit=2")
        cursor = first.json()["next_cursor"]
        second = await client.get(f"/api/v1/podcasts/{podcast_id}/episodes?limit=2&cursor={cursor}")
    first_ids = [item["id"] for item in first.json()["items"]]
    second_ids = [item["id"] for item in second.json()["items"]]
    assert first_episode_id in first_ids
    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert set(first_ids).isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_episode_resources_are_split(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        detail = await client.get(f"/api/v1/episodes/{episode_id}")
        summary = await client.get(f"/api/v1/episodes/{episode_id}/summary")
        transcript = await client.get(f"/api/v1/episodes/{episode_id}/transcript")
    assert detail.json()["description"] == "Description X"
    assert "summary" not in detail.json()
    assert "transcript" not in detail.json()
    assert summary.json() == {"episode_id": episode_id, "content": "Summary X"}
    assert transcript.json()["content"] == "Transcript X"


@pytest.mark.asyncio
async def test_transcript_download_is_markdown_without_summary(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get(f"/api/v1/episodes/{episode_id}/transcript/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in response.headers["content-disposition"]
    assert "Transcript X" in response.text
    assert "Summary X" not in response.text


@pytest.mark.asyncio
async def test_episode_not_found(pg_fresh_db, monkeypatch):
    await _setup_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/v1/episodes/no-such-episode")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_episode_without_subscription_returns_403(pg_fresh_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
    await db.init_db()
    await db.get_or_create_user(8888, chat_id=0)
    other_user_id = await db.get_or_create_user(9999, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://other.com/feed.rss", "Other Pod")
    await db.mark_episode_seen(other_user_id, podcast_id, "other-guid", title="Other Episode")
    episode_id = await db.get_episode_id(podcast_id, "other-guid")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get(f"/api/v1/episodes/{episode_id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_endpoint_rejects_invalid_history(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/episodes/{episode_id}/chat",
            json={"message": "hello", "history": "not-json"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_stream_keeps_existing_protocol():
    from core.ai.chat import chat_with_episode_stream

    async def fake_text_stream():
        for chunk in ["Hello", " world"]:
            yield chunk

    mock_result = MagicMock()
    mock_result.stream_text = MagicMock(return_value=fake_text_stream())
    mock_result.all_messages = MagicMock(return_value=[])
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_result)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_agent = MagicMock()
    mock_agent.run_stream = MagicMock(return_value=mock_cm)
    with patch("core.ai.chat._get_agent", return_value=mock_agent):
        results = [item async for item in chat_with_episode_stream("test", "Ep", "Pod", "text", None, [], "zh-TW")]
    assert [item[0] for item in results[:-1]] == ["Hello", " world"]
