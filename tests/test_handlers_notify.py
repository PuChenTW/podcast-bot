from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Message, Update
from telegram.ext import ConversationHandler

from bot.handlers.callbacks import NotifyCallback
from bot.handlers.notify import NOTIFY_CHOOSE_POD, cmd_notify, notify_cancel, notify_selected


def _sub(sub_id: str, title: str, *, telegram_delivery: bool):
    return SimpleNamespace(
        id=sub_id,
        user_id="user-1",
        podcast_id="pod-" + sub_id,
        podcast_title=title,
        rss_url="http://example.com/feed.rss",
        custom_prompt=None,
        chat_prompt=None,
        telegram_delivery=telegram_delivery,
    )


def make_message_update():
    message = AsyncMock(spec=Message)
    update = MagicMock(spec=Update)
    update.message = message
    update.effective_user = MagicMock(id=12345)
    update.effective_chat = MagicMock(id=67890)
    return update, message


def make_callback_update(data: str):
    query = AsyncMock(spec=CallbackQuery)
    query.data = data
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = MagicMock(id=12345)
    update.effective_chat = MagicMock(id=67890)
    return update, query


@pytest.mark.asyncio
async def test_no_subscriptions_ends_conversation():
    update, message = make_message_update()

    with (
        patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"),
        patch("bot.handlers.notify.db.get_or_create_user", new_callable=AsyncMock, return_value="user-1"),
        patch("bot.handlers.notify.db.get_subscriptions", new_callable=AsyncMock, return_value=[]),
    ):
        result = await cmd_notify(update, MagicMock())

    assert result == ConversationHandler.END
    message.reply_text.assert_awaited_once_with("目前沒有任何訂閱。")


@pytest.mark.asyncio
async def test_keyboard_shows_current_state_per_podcast():
    update, message = make_message_update()
    subs = [_sub("s1", "Loud Show", telegram_delivery=True), _sub("s2", "Quiet Show", telegram_delivery=False)]

    with (
        patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"),
        patch("bot.handlers.notify.db.get_or_create_user", new_callable=AsyncMock, return_value="user-1"),
        patch("bot.handlers.notify.db.get_subscriptions", new_callable=AsyncMock, return_value=subs),
    ):
        result = await cmd_notify(update, MagicMock())

    assert result == NOTIFY_CHOOSE_POD
    keyboard = message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert keyboard[0][0].text == "🔔 Loud Show"
    assert keyboard[1][0].text == "🔕 Quiet Show"
    assert keyboard[0][0].callback_data == "notify:s1"


@pytest.mark.asyncio
async def test_selecting_enabled_podcast_mutes_it():
    update, query = make_callback_update("notify:s1")
    muted = _sub("s1", "Loud Show", telegram_delivery=False)

    with (
        patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"),
        patch("bot.handlers.notify.db.get_or_create_user", new_callable=AsyncMock, return_value="user-1"),
        patch("bot.handlers.notify.db.get_subscription_by_id", new_callable=AsyncMock, return_value=_sub("s1", "Loud Show", telegram_delivery=True)),
        patch("bot.handlers.notify.db.set_subscription_telegram_delivery", new_callable=AsyncMock) as mock_set,
        patch("bot.handlers.notify.db.get_subscriptions", new_callable=AsyncMock, return_value=[muted]),
    ):
        result = await notify_selected(update, MagicMock())

    mock_set.assert_awaited_once_with("s1", False)
    # Stays in the same state so several podcasts can be toggled in one go.
    assert result == NOTIFY_CHOOSE_POD
    assert "已關閉" in query.edit_message_text.await_args.args[0]
    assert query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "🔕 Loud Show"


@pytest.mark.asyncio
async def test_selecting_muted_podcast_unmutes_it():
    update, _ = make_callback_update("notify:s2")
    unmuted = _sub("s2", "Quiet Show", telegram_delivery=True)

    with (
        patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"),
        patch("bot.handlers.notify.db.get_or_create_user", new_callable=AsyncMock, return_value="user-1"),
        patch("bot.handlers.notify.db.get_subscription_by_id", new_callable=AsyncMock, return_value=_sub("s2", "Quiet Show", telegram_delivery=False)),
        patch("bot.handlers.notify.db.set_subscription_telegram_delivery", new_callable=AsyncMock) as mock_set,
        patch("bot.handlers.notify.db.get_subscriptions", new_callable=AsyncMock, return_value=[unmuted]),
    ):
        await notify_selected(update, MagicMock())

    mock_set.assert_awaited_once_with("s2", True)


@pytest.mark.asyncio
async def test_missing_subscription_ends_conversation():
    update, query = make_callback_update("notify:gone")

    with (
        patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"),
        patch("bot.handlers.notify.db.get_subscription_by_id", new_callable=AsyncMock, return_value=None),
        patch("bot.handlers.notify.db.set_subscription_telegram_delivery", new_callable=AsyncMock) as mock_set,
    ):
        result = await notify_selected(update, MagicMock())

    assert result == ConversationHandler.END
    mock_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_ends_conversation():
    update, query = make_callback_update("notify:cancel")

    with patch("bot.handlers.notify.db.get_user_language", new_callable=AsyncMock, return_value="zh-tw"):
        result = await notify_cancel(update, MagicMock())

    assert result == ConversationHandler.END
    query.edit_message_text.assert_awaited_once_with("完成。")


def test_callback_roundtrip():
    assert NotifyCallback(subscription_id="abc").serialize() == "notify:abc"
    assert NotifyCallback(subscription_id=None).serialize() == "notify:cancel"
    assert NotifyCallback.parse("notify:abc").subscription_id == "abc"
    assert NotifyCallback.parse("notify:cancel").subscription_id is None
