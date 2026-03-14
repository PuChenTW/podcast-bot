from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.ext import ConversationHandler

from bot.database import (
    add_subscription,
    get_or_create_user,
    get_subscription_by_id,
    mark_episode_seen,
)
from bot.handlers.transcript import (
    _build_markdown,
    _safe_filename,
    transcript_ep_selected,
)

# --- _safe_filename ---


def test_safe_filename_basic():
    assert _safe_filename("My Podcast", "Episode 1") == "My_Podcast_Episode_1.md"


def test_safe_filename_strips_unsafe_chars():
    result = _safe_filename('Pod: "Name"', "Ep/1")
    assert result == "Pod_Name_Ep1.md"


def test_safe_filename_preserves_cjk():
    result = _safe_filename("科技新聞", "第一集")
    assert result.endswith(".md")
    assert "科技新聞" in result


def test_safe_filename_truncates_long_names():
    long = "A" * 100
    result = _safe_filename(long, long)
    # remove .md, split on first underscore to get both parts
    stem = result[:-3]
    # each part should be at most 50 chars (the _clean function caps at 50)
    parts = stem.split("_")
    assert all(len(p) <= 50 for p in parts)


# --- _build_markdown ---


def test_build_markdown_with_summary():
    md = _build_markdown("My Pod", "Ep 1", "2024-01-01", "Great ep", "Hello world")
    assert "# Ep 1" in md
    assert "**Podcast:** My Pod" in md
    assert "## Summary\nGreat ep" in md
    assert "## Transcript\nHello world" in md


def test_build_markdown_without_summary():
    md = _build_markdown("My Pod", "Ep 1", None, None, "Hello world")
    assert "(not yet generated)" in md
    assert "Unknown" in md


# --- transcript_ep_selected ---


@pytest.mark.asyncio
async def test_transcript_ep_selected_uses_cached_transcript(tmp_db):
    uid = await get_or_create_user(12345, 67890)
    sub_id = await add_subscription(uid, "My Pod", "http://example.com/feed.rss")
    sub = await get_subscription_by_id(sub_id)
    await mark_episode_seen(uid, sub.podcast_id, "guid-abc", transcript="cached transcript text")

    query = AsyncMock()
    query.data = f"transcript:ep:{sub_id}:0"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = MagicMock(id=12345)
    update.effective_chat = MagicMock(id=67890)

    context = MagicMock()
    context.user_data = {
        "transcript_eps": [
            {
                "title": "My Ep",
                "entry": {"id": "guid-abc", "published": "Mon, 01 Jan 2024 00:00:00 +0000"},
                "podcast_title": "My Pod",
                "subscription_id": sub_id,
            }
        ]
    }
    context.bot = AsyncMock()

    with (
        patch("bot.handlers.transcript.db.get_user_language", return_value="en"),
        patch("bot.handlers.transcript.get_episode_content") as mock_fetch,
    ):
        result = await transcript_ep_selected(update, context)

    mock_fetch.assert_not_called()
    context.bot.send_document.assert_awaited_once()
    call_kwargs = context.bot.send_document.call_args.kwargs
    assert call_kwargs["chat_id"] == 67890
    assert call_kwargs["document"].filename.endswith(".md")
    assert result == ConversationHandler.END


@pytest.mark.asyncio
async def test_transcript_ep_selected_fetches_when_missing(tmp_db):
    uid = await get_or_create_user(12345, 67890)
    sub_id = await add_subscription(uid, "My Pod", "http://example.com/feed.rss")

    query = AsyncMock()
    query.data = f"transcript:ep:{sub_id}:0"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = MagicMock(id=12345)
    update.effective_chat = MagicMock(id=67890)

    context = MagicMock()
    context.user_data = {
        "transcript_eps": [
            {
                "title": "My Ep",
                "entry": {"id": "guid-xyz", "published": None},
                "podcast_title": "My Pod",
                "subscription_id": sub_id,
            }
        ]
    }
    context.bot = AsyncMock()

    with (
        patch("bot.handlers.transcript.db.get_user_language", return_value="en"),
        patch(
            "bot.handlers.transcript.get_episode_content",
            new_callable=AsyncMock,
            return_value="fresh transcript",
        ) as mock_fetch,
    ):
        result = await transcript_ep_selected(update, context)

    mock_fetch.assert_awaited_once()
    context.bot.send_document.assert_awaited_once()
    assert result == ConversationHandler.END


@pytest.mark.asyncio
async def test_transcript_ep_selected_expired_data():
    query = AsyncMock()
    query.data = "transcript:ep:sub-123:0"
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = MagicMock(id=12345)

    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.transcript.db.get_user_language", return_value="en"):
        result = await transcript_ep_selected(update, context)

    query.edit_message_text.assert_awaited_once()
    assert result == ConversationHandler.END
