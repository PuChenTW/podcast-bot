import asyncio

from core.ai._agent import _get_agent
from core.config import get_settings

CORRECTION_CHUNK_CHARS = 12_000

_CORRECTION_SYSTEM_PROMPT = (
    "You are a transcript corrector. Given a podcast transcript that may contain ASR"
    " (automatic speech recognition) errors, correct misspelled words, misheard terms,"
    " and obvious errors using the provided episode context (podcast title, episode title,"
    " description). Organize the text into logical, readable paragraphs based on semantics."
    " Return only the corrected transcript text, nothing else."
)


def _split_chunks(text: str, max_chars: int) -> list[str]:
    """Split text at paragraph boundaries into chunks of at most max_chars."""
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        # Hard-cut oversized single paragraph
        while len(para) > max_chars:
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        sep = "\n\n" if current else ""
        if current_len + len(sep) + len(para) > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(sep) + len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


async def _correct_single_chunk(
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


async def correct_transcript(
    text: str,
    podcast_title: str,
    episode_title: str,
    description: str,
) -> str:
    chunks = _split_chunks(text, CORRECTION_CHUNK_CHARS)
    if len(chunks) == 1:
        return await _correct_single_chunk(text, podcast_title, episode_title, description)
    results = await asyncio.gather(*[_correct_single_chunk(chunk, podcast_title, episode_title, description) for chunk in chunks])
    return "\n\n".join(results)
