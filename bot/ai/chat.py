from pydantic_ai.messages import ModelMessage

from bot.ai._agent import _get_agent

_CHAT_SYSTEM_PROMPT = (
    "You are a knowledgeable podcast discussion partner. Help the user explore, understand, and discuss the episode in depth.\n\n"
    "Podcast: {podcast_title}\nEpisode: {episode_title}\n\n"
    "{context_section}"
    "Respond conversationally. The user's UI language is {lang} but respond in whatever language the user writes in."
)
_CHAT_CONTEXT_FULL = "Episode summary:\n{summary}\n\nEpisode transcript (may be truncated):\n{transcript}\n\n"
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
    model: str,
) -> tuple[str, list[ModelMessage]]:
    if transcript and summary:
        context_section = _CHAT_CONTEXT_FULL.format(summary=summary, transcript=transcript[:_CHAT_TRANSCRIPT_LIMIT])
    elif summary:
        context_section = _CHAT_CONTEXT_SUMMARY_ONLY.format(summary=summary)
    else:
        context_section = _CHAT_CONTEXT_NONE

    system_prompt = _CHAT_SYSTEM_PROMPT.format(
        podcast_title=podcast_title,
        episode_title=episode_title,
        context_section=context_section,
        lang=lang,
    )
    agent = _get_agent(model, system_prompt)
    result = await agent.run(user_message, message_history=history or None)
    return result.output, list(result.all_messages())
