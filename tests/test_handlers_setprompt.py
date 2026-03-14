from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update
from telegram.ext import ConversationHandler

from bot.handlers import setprompt_conv, subscribe_conv
from bot.handlers.setprompt import (
    SETPROMPT_CHOOSE_POD,
    cmd_setprompt,
    setprompt_save_manual,
)
from bot.handlers.subscribe import (
    SUBSCRIBE_WAITING_URL,
    cmd_subscribe,
    subscribe_url_received,
)


def make_message_update(text: str):
    message = AsyncMock(spec=Message)
    message.text = text
    update = MagicMock(spec=Update)
    update.message = message
    update.effective_user = MagicMock(id=12345)
    update.effective_chat = MagicMock(id=67890)
    return update, message


def make_context(user_data: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data
    return ctx


@pytest.mark.asyncio
async def test_manual_mode_saves_prompt():
    update, message = make_message_update("My custom prompt text")
    ctx = make_context({"setprompt": {"subscription_id": "sub-123"}})

    with patch(
        "bot.handlers.setprompt.db.set_subscription_prompt", new_callable=AsyncMock
    ) as mock_save:
        result = await setprompt_save_manual(update, ctx)

    mock_save.assert_awaited_once_with("sub-123", "My custom prompt text")
    assert "setprompt" not in ctx.user_data
    message.reply_text.assert_awaited_once_with("已儲存 ✓")
    assert result == ConversationHandler.END


@pytest.mark.asyncio
async def test_cmd_subscribe_returns_waiting_url_state():
    update, message = make_message_update("")
    ctx = make_context({})

    result = await cmd_subscribe(update, ctx)

    assert result == SUBSCRIBE_WAITING_URL
    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_cmd_setprompt_returns_choose_pod_state():
    update, message = make_message_update("")
    ctx = make_context({})

    fake_sub = MagicMock()
    fake_sub.id = "sub-999"
    fake_sub.podcast_title = "Test Podcast"

    with patch(
        "bot.handlers.setprompt.db.get_or_create_user",
        new_callable=AsyncMock,
        return_value="user-1",
    ):
        with patch(
            "bot.handlers.setprompt.db.get_subscriptions",
            new_callable=AsyncMock,
            return_value=[fake_sub],
        ):
            result = await cmd_setprompt(update, ctx)

    assert result == SETPROMPT_CHOOSE_POD
    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_url_received_returns_end_on_bad_url():
    update, message = make_message_update("not-a-valid-url")
    ctx = make_context({})

    sent_msg = AsyncMock()
    message.reply_text.return_value = sent_msg

    with patch(
        "bot.handlers.subscribe.resolve_rss_url",
        new_callable=AsyncMock,
        side_effect=ValueError("Bad URL"),
    ):
        result = await subscribe_url_received(update, ctx)

    assert result == ConversationHandler.END


def test_subscribe_conv_is_conversation_handler():
    from telegram.ext import ConversationHandler as CH

    assert isinstance(subscribe_conv, CH)


def test_setprompt_conv_is_conversation_handler():
    from telegram.ext import ConversationHandler as CH

    assert isinstance(setprompt_conv, CH)


def test_subscribe_and_setprompt_are_independent_conversations():
    """Each flow is its own ConversationHandler — no shared state management needed."""
    assert subscribe_conv is not setprompt_conv
