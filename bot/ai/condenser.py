from bot.ai._agent import _get_agent
from bot.config import get_settings

_CONDENSER_SYSTEM_PROMPT = (
    "You are a transcript condenser. Given a full podcast episode transcript, produce a condensed version"
    " that preserves all key information: named entities, factual claims, statistics, direct quotes,"
    " topic segments, arguments, and conclusions. Remove filler words, false starts, repetitive"
    " elaborations, and off-topic tangents. Aim for approximately 10,000 characters in the output."
    " Return only the condensed transcript text, nothing else."
)


async def condense_transcript(transcript: str, podcast_title: str, episode_title: str) -> str:
    model = get_settings().condenser_model
    agent = _get_agent(model, _CONDENSER_SYSTEM_PROMPT)
    prompt = f"Podcast: {podcast_title}\nEpisode: {episode_title}\n\nTranscript:\n{transcript}"
    result = await agent.run(prompt)
    return result.output
