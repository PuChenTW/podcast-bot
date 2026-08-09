"""Telegram delivery is decoupled from transcription/summarization.

Muting a subscription must skip only `bot.send_message` — the episode is still
summarized and persisted so it stays readable in the web UI.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot.scheduler import _process_episode


def _sub(*, telegram_delivery=True):
    return SimpleNamespace(
        id="sub-1",
        user_id="user-1",
        podcast_id="pod-1",
        podcast_title="Test Show",
        rss_url="http://example.com/feed.rss",
        custom_prompt=None,
        chat_prompt=None,
        telegram_delivery=telegram_delivery,
        chat_id=555,
    )


def _episode():
    return SimpleNamespace(
        guid="guid-1",
        title="Episode 1",
        content="full content",
        transcript="the transcript",
        description="the description",
        published="2026-01-01",
        transcript_source="feed",
    )


async def _run(sub, chat_id):
    with (
        patch("bot.scheduler.summarize_episode", new_callable=AsyncMock, return_value="a summary") as summarize,
        patch("bot.scheduler.db.mark_episode_seen", new_callable=AsyncMock) as mark_seen,
        patch("bot.scheduler.get_settings") as settings,
    ):
        settings.return_value.google_drive_enabled = False
        bot = AsyncMock()
        sent = await _process_episode(bot, sub, _episode(), chat_id)
    return bot, summarize, mark_seen, sent


@pytest.mark.asyncio
async def test_delivery_enabled_sends_and_persists():
    bot, summarize, mark_seen, sent = await _run(_sub(), 555)

    assert sent is True
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 555
    summarize.assert_awaited_once()
    mark_seen.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_disabled_still_summarizes_and_persists():
    bot, summarize, mark_seen, sent = await _run(_sub(telegram_delivery=False), 555)

    assert sent is False
    bot.send_message.assert_not_awaited()
    # The expensive work still happens; only the push is skipped.
    summarize.assert_awaited_once()
    mark_seen.assert_awaited_once()
    assert mark_seen.await_args.kwargs["summary"] == "a summary"
    assert mark_seen.await_args.kwargs["transcript"] == "the transcript"


@pytest.mark.asyncio
async def test_web_created_user_chat_id_zero_is_not_sent_to():
    bot, _, mark_seen, sent = await _run(_sub(), 0)

    assert sent is False
    bot.send_message.assert_not_awaited()
    mark_seen.assert_awaited_once()
    assert mark_seen.await_args.kwargs["summary"] == "a summary"
