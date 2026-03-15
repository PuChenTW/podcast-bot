from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Message, Update, User


def _make_callback_query(data: str, user_id: int = 1) -> tuple[Update, MagicMock]:
    user = MagicMock(spec=User)
    user.id = user_id
    query = MagicMock(spec=CallbackQuery)
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = user
    return update, query


def _make_message_update(text: str, user_id: int = 1) -> tuple[Update, MagicMock]:
    user = MagicMock(spec=User)
    user.id = user_id
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.reply_text = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    update = MagicMock(spec=Update)
    update.message = msg
    update.effective_user = user
    return update, msg


@pytest.mark.asyncio
async def test_setprompt_enter_refine_from_user_data():
    """enter_refine uses user_data generated_prompt when available."""
    from bot.handlers.setprompt import SETPROMPT_REFINE, setprompt_enter_refine

    update, query = _make_callback_query("setprompt:refine:sub123")
    context = MagicMock()
    context.user_data = {"setprompt": {"generated_prompt": "existing prompt", "subscription_id": "sub123"}}

    with patch("bot.handlers.setprompt.db.get_user_language", AsyncMock(return_value="en")):
        result = await setprompt_enter_refine(update, context)

    assert result == SETPROMPT_REFINE
    query.edit_message_text.assert_called_once()
    assert context.user_data["setprompt"]["generated_prompt"] == "existing prompt"


@pytest.mark.asyncio
async def test_setprompt_enter_refine_from_db():
    """enter_refine loads from DB when user_data has no generated_prompt."""
    from bot.handlers.setprompt import SETPROMPT_REFINE, setprompt_enter_refine
    from shared.database import Subscription

    update, query = _make_callback_query("setprompt:refine:sub123")
    context = MagicMock()
    context.user_data = {}

    mock_sub = MagicMock(spec=Subscription)
    mock_sub.custom_prompt = "db stored prompt"

    with (
        patch("bot.handlers.setprompt.db.get_user_language", AsyncMock(return_value="en")),
        patch("bot.handlers.setprompt.db.get_subscription_by_id", AsyncMock(return_value=mock_sub)),
    ):
        result = await setprompt_enter_refine(update, context)

    assert result == SETPROMPT_REFINE
    assert context.user_data["setprompt"]["generated_prompt"] == "db stored prompt"


@pytest.mark.asyncio
async def test_setprompt_refine_apply():
    """refine_apply calls refine_prompt and stays in SETPROMPT_REFINE state."""
    from bot.handlers.setprompt import SETPROMPT_REFINE, setprompt_refine_apply

    update, msg = _make_message_update("make it shorter")
    context = MagicMock()
    context.user_data = {"setprompt": {"generated_prompt": "old prompt", "subscription_id": "sub123"}}

    with (
        patch("bot.handlers.setprompt.db.get_user_language", AsyncMock(return_value="en")),
        patch("bot.handlers.setprompt.refine_prompt", AsyncMock(return_value="refined prompt")),
    ):
        result = await setprompt_refine_apply(update, context)

    assert result == SETPROMPT_REFINE
    assert context.user_data["setprompt"]["generated_prompt"] == "refined prompt"


@pytest.mark.asyncio
async def test_setprompt_refine_save():
    """refine_save writes to DB and ends conversation."""
    from telegram.ext import ConversationHandler

    from bot.handlers.setprompt import setprompt_refine_save

    update, query = _make_callback_query("setprompt:refine_save:sub123")
    context = MagicMock()
    context.user_data = {"setprompt": {"generated_prompt": "final prompt", "subscription_id": "sub123"}}

    with (
        patch("bot.handlers.setprompt.db.get_user_language", AsyncMock(return_value="en")),
        patch("bot.handlers.setprompt.db.set_subscription_prompt", AsyncMock()),
    ):
        result = await setprompt_refine_save(update, context)

    assert result == ConversationHandler.END
    assert "setprompt" not in context.user_data


@pytest.mark.asyncio
async def test_setprompt_refine_apply_empty_instruction():
    """refine_apply with empty instruction should not call refine_prompt."""
    from bot.handlers.setprompt import SETPROMPT_REFINE, setprompt_refine_apply

    update, msg = _make_message_update("   ")  # whitespace only
    context = MagicMock()
    context.user_data = {"setprompt": {"generated_prompt": "old prompt", "subscription_id": "sub123"}}

    with (
        patch("bot.handlers.setprompt.db.get_user_language", AsyncMock(return_value="en")),
        patch("bot.handlers.setprompt.refine_prompt", AsyncMock()) as mock_refine,
    ):
        result = await setprompt_refine_apply(update, context)

    assert result == SETPROMPT_REFINE
    mock_refine.assert_not_called()
