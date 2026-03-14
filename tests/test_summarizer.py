from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.ai.prompt_engineer import refine_prompt


@pytest.mark.asyncio
async def test_refine_prompt_returns_string():
    """refine_prompt calls the agent with current prompt + instruction and returns output."""
    mock_result = MagicMock()
    mock_result.output = "Refined system prompt text"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    with patch("bot.ai.prompt_engineer._get_agent", return_value=mock_agent):
        result = await refine_prompt("old prompt", "make it shorter", "gemini-2.0-flash")

    assert result == "Refined system prompt text"
    mock_agent.run.assert_called_once()
    call_arg = mock_agent.run.call_args[0][0]
    assert "old prompt" in call_arg
    assert "make it shorter" in call_arg


@pytest.mark.asyncio
async def test_refine_prompt_handles_braces_in_current_prompt():
    """refine_prompt must not crash when current_prompt contains { } characters."""
    mock_result = MagicMock()
    mock_result.output = "Refined"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    with patch("bot.ai.prompt_engineer._get_agent", return_value=mock_agent):
        # AI-generated prompts often contain {placeholder} syntax — must not KeyError
        result = await refine_prompt("Format: **{headline}**\n• {point}", "make it shorter", "gemini-2.0-flash")

    assert result == "Refined"
