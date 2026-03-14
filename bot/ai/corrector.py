from bot.ai._agent import _get_agent

_CORRECTION_SYSTEM_PROMPT = (
    "You are a transcript corrector. Given a podcast transcript that may contain ASR"
    " (automatic speech recognition) errors, correct misspelled words, misheard terms,"
    " and obvious errors using the provided episode context (podcast title, episode title,"
    " description). Preserve the original meaning and structure."
    " Return only the corrected transcript text, nothing else."
)


async def correct_transcript(
    model: str,
    text: str,
    podcast_title: str,
    episode_title: str,
    description: str,
) -> str:
    """Correct ASR errors in a transcript using the given model.

    `model` is the first arg so callers can bind it via functools.partial:
        corrector = partial(correct_transcript, settings.ai_model)
    """
    agent = _get_agent(model, _CORRECTION_SYSTEM_PROMPT)
    prompt = f"Podcast: {podcast_title}\nEpisode: {episode_title}\nDescription: {description}\n\nTranscript:\n{text}"
    result = await agent.run(prompt)
    return result.output
