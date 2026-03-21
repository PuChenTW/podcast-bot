from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage

from core.ai._agent import _get_agent
from core.config import get_settings

_CHAT_SYSTEM_PROMPT = (
    "You are a knowledgeable podcast discussion partner. Help the user explore, understand, and discuss the episode in depth.\n\n"
    "Podcast: {podcast_title}\nEpisode: {episode_title}\n\n"
    "{context_section}"
    "Respond conversationally. The user's UI language is {lang} but respond in whatever language the user writes in."
)
_CHAT_CUSTOM_SYSTEM_PROMPT = (
    "{custom_system_prompt}\n\n"
    "Podcast: {podcast_title}\nEpisode: {episode_title}\n\n"
    "{context_section}"
    "Respond conversationally. The user's UI language is {lang} but respond in whatever language the user writes in."
)
_CHAT_CONTEXT_FULL = "Episode summary:\n{summary}\n\nEpisode transcript (condensed if long):\n{transcript}\n\n"
_CHAT_CONTEXT_SUMMARY_ONLY = "Episode summary:\n{summary}\n\nNote: full transcript unavailable.\n\n"
_CHAT_CONTEXT_NONE = "Note: no transcript or summary available — discuss based on title.\n\n"

_CHAT_TRANSCRIPT_LIMIT = 12_000


async def chat_with_episode(
    user_message: str,
    episode_title: str,
    podcast_title: str,
    transcript: str,
    summary: str | None,
    history: list[ModelMessage],
    lang: str,
    custom_system_prompt: str | None = None,
) -> tuple[str, list[ModelMessage]]:
    model = get_settings().chat_model
    if transcript and summary:
        context_section = _CHAT_CONTEXT_FULL.format(summary=summary, transcript=transcript[:_CHAT_TRANSCRIPT_LIMIT])
    elif summary:
        context_section = _CHAT_CONTEXT_SUMMARY_ONLY.format(summary=summary)
    else:
        context_section = _CHAT_CONTEXT_NONE

    template = _CHAT_CUSTOM_SYSTEM_PROMPT if custom_system_prompt else _CHAT_SYSTEM_PROMPT
    system_prompt = template.format(
        custom_system_prompt=custom_system_prompt or "",
        podcast_title=podcast_title,
        episode_title=episode_title,
        context_section=context_section,
        lang=lang,
    )
    agent = _get_agent(model, system_prompt)
    result = await agent.run(user_message, message_history=history or None)
    return result.output, list(result.all_messages())


async def chat_with_episode_stream(
    user_message: str,
    episode_title: str,
    podcast_title: str,
    transcript: str,
    summary: str | None,
    history: list[ModelMessage],
    lang: str,
    custom_system_prompt: str | None = None,
) -> AsyncIterator[tuple[str, list[ModelMessage] | None]]:
    """Yield (text_delta, None) for each streamed chunk, then ("", all_messages) at the end."""
    model = get_settings().chat_model
    if transcript and summary:
        context_section = _CHAT_CONTEXT_FULL.format(summary=summary, transcript=transcript[:_CHAT_TRANSCRIPT_LIMIT])
    elif summary:
        context_section = _CHAT_CONTEXT_SUMMARY_ONLY.format(summary=summary)
    else:
        context_section = _CHAT_CONTEXT_NONE

    template = _CHAT_CUSTOM_SYSTEM_PROMPT if custom_system_prompt else _CHAT_SYSTEM_PROMPT
    system_prompt = template.format(
        custom_system_prompt=custom_system_prompt or "",
        podcast_title=podcast_title,
        episode_title=episode_title,
        context_section=context_section,
        lang=lang,
    )
    agent = _get_agent(model, system_prompt)
    async with agent.run_stream(user_message, message_history=history or None) as result:
        async for chunk in result.stream_text(delta=True):
            yield chunk, None
        yield "", list(result.all_messages())  # inside async with — result still valid
