from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.ext import ConversationHandler

from bot.handlers.digest import digest_ep_selected
from core.database import add_subscription, get_or_create_user, mark_episode_seen


def _make_update_context(sub_id, guid, uid=12345, chat_id=67890, ep_title="My Ep", podcast_title="My Pod"):
    query = AsyncMock()
    query.data = f"digest:ep:{sub_id}:0"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = MagicMock(id=uid)
    update.effective_chat = MagicMock(id=chat_id)

    context = MagicMock()
    context.user_data = {
        "digest_eps": [
            {
                "title": ep_title,
                "entry": {"id": guid, "published": "Mon, 01 Jan 2024 00:00:00 +0000"},
                "podcast_title": podcast_title,
                "subscription_id": sub_id,
            }
        ]
    }
    context.bot_data = {"transcriber": MagicMock()}
    return update, context


@pytest.mark.asyncio
async def test_digest_ep_selected_uses_cached_summary(tmp_db):
    from core.database import get_subscription_by_id

    uid = await get_or_create_user(12345, 67890)
    sub_id = await add_subscription(uid, "My Pod", "http://example.com/feed.rss")
    sub = await get_subscription_by_id(sub_id)
    await mark_episode_seen(uid, sub.podcast_id, "guid-cached", summary="cached summary text")

    update, context = _make_update_context(sub_id, "guid-cached")

    with (
        patch("bot.handlers.digest.db.get_user_language", return_value="en"),
        patch("bot.handlers.digest.summarize_episode", new_callable=AsyncMock) as mock_summarize,
    ):
        result = await digest_ep_selected(update, context)

    mock_summarize.assert_not_called()
    update.callback_query.edit_message_text.assert_awaited_once()
    call_kwargs = update.callback_query.edit_message_text.call_args
    assert "cached summary text" in call_kwargs.kwargs.get("text", call_kwargs.args[0] if call_kwargs.args else "")
    assert result == ConversationHandler.END


@pytest.mark.asyncio
async def test_digest_ep_selected_generates_when_no_summary(tmp_db):
    uid = await get_or_create_user(12345, 67890)
    sub_id = await add_subscription(uid, "My Pod", "http://example.com/feed.rss")
    # No prior mark_episode_seen — no cached summary

    update, context = _make_update_context(sub_id, "guid-new")

    with (
        patch("bot.handlers.digest.db.get_user_language", return_value="en"),
        patch("bot.handlers.digest.get_or_fetch_transcript", new_callable=AsyncMock, return_value="transcript text"),
        patch("bot.handlers.digest.summarize_episode", new_callable=AsyncMock, return_value="new summary") as mock_summarize,
        patch("bot.handlers.digest.db.mark_episode_seen", new_callable=AsyncMock),
    ):
        result = await digest_ep_selected(update, context)

    mock_summarize.assert_awaited_once()
    assert result == ConversationHandler.END
