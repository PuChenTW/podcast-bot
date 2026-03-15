from bot.ai._agent import _get_agent
from bot.config import get_settings

_DEFAULT_SYSTEM_PROMPT = (
    "You are a podcast summarizer. Given transcript or description text from a podcast episode,"
    " produce a concise summary in Markdown. Ignore any sponsored content or advertisements.\n"
    "\nFormat your response as:\n"
    "**{punchy one-sentence headline}**\n"
    "\n• key point 1\n• key point 2\n• key point 3\n(up to 5 key points)\n"
    "\n**Takeaway:** one actionable sentence\n"
)


async def summarize_episode(title: str, content: str, custom_prompt: str | None = None) -> str:
    model = get_settings().summarizer_model
    prompt_text = custom_prompt or _DEFAULT_SYSTEM_PROMPT
    agent = _get_agent(model, prompt_text)
    result = await agent.run(f"Episode title: {title}\n\n{content}")
    return result.output
