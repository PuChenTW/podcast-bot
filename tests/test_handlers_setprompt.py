from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler

from bot.handlers.setprompt import cmd_setprompt, setprompt_message_handler
from bot.handlers.subscribe import cmd_subscribe, subscribe_message_handler


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
    ctx = make_context({"setprompt": {"subscription_id": "sub-123", "mode": "manual"}})

    with patch("bot.handlers.setprompt.db.set_subscription_prompt", new_callable=AsyncMock) as mock_save:
        with pytest.raises(ApplicationHandlerStop):
            await setprompt_message_handler(update, ctx)

    mock_save.assert_awaited_once_with("sub-123", "My custom prompt text")
    assert "setprompt" not in ctx.user_data
    message.reply_text.assert_awaited_once_with("已儲存 ✓")


@pytest.mark.asyncio
async def test_no_state_is_ignored():
    update, _ = make_message_update("some text")
    ctx = make_context({})

    with patch("bot.handlers.setprompt.db.set_subscription_prompt", new_callable=AsyncMock) as mock_save:
        result = await setprompt_message_handler(update, ctx)

    assert result is None
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_subscribe_clears_setprompt_state():
    update, message = make_message_update("")
    ctx = make_context({"setprompt": {"subscription_id": "sub-abc", "mode": "manual"}})

    await cmd_subscribe(update, ctx)

    assert "setprompt" not in ctx.user_data
    assert ctx.user_data.get("subscribe") == {"awaiting_url": True}
    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_cmd_setprompt_clears_subscribe_state():
    update, message = make_message_update("")
    ctx = make_context({"subscribe": {"awaiting_url": True}})

    fake_sub = MagicMock()
    fake_sub.id = "sub-999"
    fake_sub.podcast_title = "Test Podcast"

    with patch("bot.handlers.setprompt.db.get_or_create_user", new_callable=AsyncMock, return_value="user-1"):
        with patch("bot.handlers.setprompt.db.get_subscriptions", new_callable=AsyncMock, return_value=[fake_sub]):
            await cmd_setprompt(update, ctx)

    assert "subscribe" not in ctx.user_data
    message.reply_text.assert_awaited_once()


def test_message_handlers_registered_in_separate_groups():
    """subscribe and setprompt message handlers must be in different groups.

    PTB stops processing handlers after the first match within a group,
    so both handlers must be in separate groups to run independently.
    """
    app = Application.builder().token("fake:token").build()

    from main import (
        setprompt_message_handler as sph,
        subscribe_message_handler as smh,
    )

    app.add_handler(MessageHandler(None, smh), group=0)
    app.add_handler(MessageHandler(None, sph), group=1)

    group0_callbacks = [h.callback for h in app.handlers[0]]
    group1_callbacks = [h.callback for h in app.handlers[1]]

    assert smh in group0_callbacks
    assert sph in group1_callbacks
    assert sph not in group0_callbacks, "setprompt handler must NOT share group with subscribe handler"


@pytest.mark.asyncio
async def test_subscribe_message_handler_raises_stop_on_active_state():
    """subscribe_message_handler raises ApplicationHandlerStop when it handles a message."""
    update, message = make_message_update("not-a-valid-url")
    ctx = make_context({"subscribe": {"awaiting_url": True}})

    sent_msg = AsyncMock()
    message.reply_text.return_value = sent_msg

    with patch("bot.handlers.subscribe.resolve_rss_url", new_callable=AsyncMock, side_effect=ValueError("Bad URL")):
        with pytest.raises(ApplicationHandlerStop):
            await subscribe_message_handler(update, ctx)
