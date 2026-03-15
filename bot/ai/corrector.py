from bot.ai._agent import _get_agent
from bot.config import get_settings

_CORRECTION_SYSTEM_PROMPT = (
    "You are a transcript corrector. Given a podcast transcript that may contain ASR"
    " (automatic speech recognition) errors, correct misspelled words, misheard terms,"
    " and obvious errors using the provided episode context (podcast title, episode title,"
    " description). Preserve the original meaning and structure."
    " Return only the corrected transcript text, nothing else."
)


async def correct_transcript(
    text: str,
    podcast_title: str,
    episode_title: str,
    description: str,
) -> str:
    model = get_settings().corrector_model
    agent = _get_agent(model, _CORRECTION_SYSTEM_PROMPT)
    prompt = f"Podcast: {podcast_title}\nEpisode: {episode_title}\nDescription: {description}\n\nTranscript:\n{text}"
    result = await agent.run(prompt)
    return result.output
