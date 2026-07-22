from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core import database as db
from core.feed import TranscriptResult
from web.app import create_app
from web.jobs import run_next_job


async def _setup_with_episode(pg_fresh_db, monkeypatch, transcript="Some transcript"):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "7777")
    await db.init_db()
    user_id = await db.get_or_create_user(7777, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://regen-test.com/feed.rss", "Regen Pod")
    await db.add_subscription(user_id, "Regen Pod", "http://regen-test.com/feed.rss")
    await db.mark_episode_seen(
        user_id,
        podcast_id,
        "ep-r",
        title="Regen Ep",
        published_at="2024-04-01",
        transcript=transcript,
        description="Description fallback",
    )
    return user_id, podcast_id, await db.get_episode_id(podcast_id, "ep-r")


@pytest.mark.asyncio
async def test_summary_job_is_persisted_and_completed(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch)
    with patch("web.jobs.summarize_episode", new_callable=AsyncMock, return_value="New summary") as summarize:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.post(f"/api/v1/episodes/{episode_id}/summary-jobs")
            assert response.status_code == 202
            assert response.headers["location"].endswith(response.json()["id"])
            await run_next_job()
            job = await client.get(response.headers["location"])
            summary = await client.get(f"/api/v1/episodes/{episode_id}/summary")
    assert job.json()["status"] == "done"
    assert summary.json()["content"] == "New summary"
    assert summarize.await_args.args[1] == "Some transcript"


@pytest.mark.asyncio
async def test_summary_job_uses_description_without_generating_transcript(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch, transcript=None)
    with patch("web.jobs.summarize_episode", new_callable=AsyncMock, return_value="Fallback summary") as summarize:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.post(f"/api/v1/episodes/{episode_id}/summary-jobs")
            await run_next_job()
            transcript = await client.get(f"/api/v1/episodes/{episode_id}/transcript")
    assert response.status_code == 202
    assert summarize.await_args.args[1] == "Description fallback"
    assert transcript.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_active_job_returns_existing_job(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        first = await client.post(f"/api/v1/episodes/{episode_id}/summary-jobs")
        second = await client.post(f"/api/v1/episodes/{episode_id}/summary-jobs")
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_job_is_forbidden_to_another_user(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        created = await client.post(f"/api/v1/episodes/{episode_id}/summary-jobs")
        monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "8888")
        response = await client.get(created.headers["location"])
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_transcript_job_replaces_transcript_and_clears_condensed(pg_fresh_db, monkeypatch):
    user_id, podcast_id, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch)
    await db.save_episode_condensed_transcript(podcast_id, "ep-r", "old condensed")
    feed = MagicMock()
    feed.entries = [{"id": "ep-r", "title": "Regen Ep"}]
    with (
        patch("web.jobs.feed_module.fetch_feed", new_callable=AsyncMock, return_value=feed),
        patch("web.jobs.feed_module.get_transcript_result", new_callable=AsyncMock, return_value=TranscriptResult("fresh transcript", "asr")),
    ):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.post(f"/api/v1/episodes/{episode_id}/transcript-jobs")
            await run_next_job(transcriber=MagicMock())
            job = await client.get(response.headers["location"])
            transcript = await client.get(f"/api/v1/episodes/{episode_id}/transcript")
    detail = await db.get_episode_for_user(user_id, episode_id)
    assert job.json()["status"] == "done"
    assert transcript.json()["content"] == "fresh transcript"
    assert transcript.json()["source"] == "asr"
    assert detail["condensed_transcript"] is None


@pytest.mark.asyncio
async def test_transcript_job_failure_preserves_existing_data(pg_fresh_db, monkeypatch):
    user_id, podcast_id, episode_id = await _setup_with_episode(pg_fresh_db, monkeypatch)
    await db.save_episode_condensed_transcript(podcast_id, "ep-r", "old condensed")
    feed = MagicMock()
    feed.entries = []
    with patch("web.jobs.feed_module.fetch_feed", new_callable=AsyncMock, return_value=feed):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.post(f"/api/v1/episodes/{episode_id}/transcript-jobs")
            await run_next_job(transcriber=MagicMock())
            job = await client.get(response.headers["location"])
    detail = await db.get_episode_for_user(user_id, episode_id)
    assert job.json()["status"] == "error"
    assert job.json()["error_code"] == "episode_source_not_found"
    assert detail["transcript"] == "Some transcript"
    assert detail["condensed_transcript"] == "old condensed"
