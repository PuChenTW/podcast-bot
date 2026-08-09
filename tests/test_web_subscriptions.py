from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core import database as db
from web.app import create_app


def _env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9999")


def _feed(title: str):
    feed = MagicMock()
    feed.bozo = False
    feed.feed.title = title
    feed.entries = []
    return feed


@pytest.mark.asyncio
async def test_get_podcasts_empty(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/v1/podcasts")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_post_subscription_and_list_podcast(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    with (
        patch("core.feed.resolve_rss_url", new_callable=AsyncMock, return_value="http://example.com/feed.rss"),
        patch("core.feed.fetch_feed", new_callable=AsyncMock, return_value=_feed("Test Podcast")),
    ):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.post("/api/v1/subscriptions", json={"rss_url": "http://example.com/feed.rss"})
            listed = await client.get("/api/v1/podcasts?q=Test")
    assert response.status_code == 201
    assert response.json()["title"] == "Test Podcast"
    assert listed.json()["items"][0]["id"] == response.json()["id"]


@pytest.mark.asyncio
async def test_delete_subscription_success(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    with (
        patch("core.feed.resolve_rss_url", new_callable=AsyncMock, return_value="http://del.com/feed.rss"),
        patch("core.feed.fetch_feed", new_callable=AsyncMock, return_value=_feed("Delete Test")),
    ):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            created = await client.post("/api/v1/subscriptions", json={"rss_url": "http://del.com/feed.rss"})
            response = await client.delete(f"/api/v1/subscriptions/{created.json()['subscription_id']}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_subscription_not_found(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.delete("/api/v1/subscriptions/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_prompts_supports_partial_update_and_clear(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    user_id = await db.get_or_create_user(9999, 0)
    subscription_id = await db.add_subscription(user_id, "Prompt Test", "http://prompt.com/feed.rss")
    await db.set_subscription_chat_prompt(subscription_id, "Keep me")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        updated = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}/prompts",
            json={"summary_prompt": "Focus on tech"},
        )
        cleared = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}/prompts",
            json={"summary_prompt": None},
        )
    assert updated.json() == {"summary_prompt": "Focus on tech", "chat_prompt": "Keep me"}
    assert cleared.json() == {"summary_prompt": None, "chat_prompt": "Keep me"}


@pytest.mark.asyncio
async def test_prompt_draft_does_not_save(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    user_id = await db.get_or_create_user(9999, 0)
    subscription_id = await db.add_subscription(user_id, "Prompt Test", "http://prompt.com/feed.rss")
    with patch("web.routers.v1.prompts.generate_prompt_from_description", new_callable=AsyncMock, return_value="Draft"):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            draft = await client.post(
                f"/api/v1/subscriptions/{subscription_id}/prompt-drafts",
                json={"kind": "summary", "description": "Short"},
            )
            prompts = await client.get(f"/api/v1/subscriptions/{subscription_id}/prompts")
    assert draft.json() == {"prompt": "Draft"}
    assert prompts.json()["summary_prompt"] is None


@pytest.mark.asyncio
async def test_delivery_defaults_enabled_and_toggles(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    user_id = await db.get_or_create_user(9999, 0)
    subscription_id = await db.add_subscription(user_id, "Delivery Test", "http://delivery.com/feed.rss")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        initial = await client.get(f"/api/v1/subscriptions/{subscription_id}/delivery")
        muted = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}/delivery",
            json={"telegram_delivery": False},
        )
        after_mute = await client.get(f"/api/v1/subscriptions/{subscription_id}/delivery")
        unmuted = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}/delivery",
            json={"telegram_delivery": True},
        )
    assert initial.json() == {"telegram_delivery": True}
    assert muted.json() == {"telegram_delivery": False}
    assert after_mute.json() == {"telegram_delivery": False}
    assert unmuted.json() == {"telegram_delivery": True}


@pytest.mark.asyncio
async def test_delivery_state_appears_in_podcast_list(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    user_id = await db.get_or_create_user(9999, 0)
    subscription_id = await db.add_subscription(user_id, "Listed", "http://listed.com/feed.rss")
    await db.set_subscription_telegram_delivery(subscription_id, False)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        listed = await client.get("/api/v1/podcasts")
    assert listed.json()["items"][0]["telegram_delivery"] is False


@pytest.mark.asyncio
async def test_delivery_unknown_subscription_returns_404(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.patch(
            "/api/v1/subscriptions/01JXXXXXXXXXXXXXXXXXXXXXXX/delivery",
            json={"telegram_delivery": False},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delivery_other_users_subscription_returns_403(pg_fresh_db, monkeypatch):
    _env(monkeypatch)
    await db.init_db()
    await db.get_or_create_user(9999, 0)
    other_user = await db.get_or_create_user(1234, 4321)
    foreign_sub = await db.add_subscription(other_user, "Not Mine", "http://foreign.com/feed.rss")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/subscriptions/{foreign_sub}/delivery",
            json={"telegram_delivery": False},
        )
    assert response.status_code == 403
