from bot.ai._agent import _get_agent
from bot.config import get_settings

_META_PROMPT = (
    "You are a prompt engineer. Given a user's description of a podcast and their desired summary style,"
    " write a system prompt for an AI podcast summarizer that matches the user's expectations."
    " Do not impose any fixed output format — let the user's description dictate the style and depth.\n"
    "\nUser's description: {user_description}\n"
    "\nOutput only the system prompt text, nothing else."
)

_REFINE_PROMPT_PREFIX = """You are a prompt engineer. You have an existing system prompt for an AI podcast summarizer. Apply the user's refinement instruction to improve it.

Existing prompt:
"""
_REFINE_PROMPT_SUFFIX = "\n\nOutput only the revised system prompt text, nothing else."


async def generate_prompt_from_description(description: str) -> str:
    """Use AI to expand a user's plain-text description into a full system prompt."""
    model = get_settings().prompt_engineer_model
    agent = _get_agent(model, "You are a helpful assistant.")
    result = await agent.run(_META_PROMPT.format(user_description=description))
    return result.output


async def refine_prompt(current_prompt: str, instruction: str) -> str:
    """Apply a natural-language instruction to refine an existing system prompt."""
    model = get_settings().prompt_engineer_model
    agent = _get_agent(model, "You are a helpful assistant.")
    msg = _REFINE_PROMPT_PREFIX + current_prompt + f"\n\nRefinement instruction: {instruction}" + _REFINE_PROMPT_SUFFIX
    result = await agent.run(msg)
    return result.output
