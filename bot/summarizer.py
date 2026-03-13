from functools import lru_cache

from pydantic_ai import Agent

_DEFAULT_SYSTEM_PROMPT = """You are a podcast summarizer. Given transcript or description text from a podcast episode, produce a concise summary in Markdown. Ignore any sponsored content or advertisements.

Format your response as:
**{punchy one-sentence headline}**

• key point 1
• key point 2
• key point 3
(up to 5 key points)

**Takeaway:** one actionable sentence
"""

_META_PROMPT = """You are a prompt engineer. Given a user's description of a podcast and their desired summary style, write a system prompt for an AI podcast summarizer that matches the user's expectations. Do not impose any fixed output format — let the user's description dictate the style and depth.

User's description: {user_description}

Output only the system prompt text, nothing else."""

_REFINE_PROMPT_PREFIX = """You are a prompt engineer. You have an existing system prompt for an AI podcast summarizer. Apply the user's refinement instruction to improve it.

Existing prompt:
"""
_REFINE_PROMPT_SUFFIX = "\n\nOutput only the revised system prompt text, nothing else."

_CORRECTION_SYSTEM_PROMPT = """You are a transcript corrector. Given a podcast transcript that may contain ASR (automatic speech recognition) errors, correct misspelled words, misheard terms, and obvious errors using the provided episode context (podcast title, episode title, description). Preserve the original meaning and structure. Return only the corrected transcript text, nothing else."""


@lru_cache(maxsize=16)
def _get_agent(model: str, system_prompt: str) -> Agent:
    """Return a cached Agent for a given (model, system_prompt) pair."""
    return Agent(f"google-gla:{model}", instructions=system_prompt)


async def summarize_episode(
    title: str, content: str, model: str, custom_prompt: str | None = None
) -> str:
    prompt_text = custom_prompt or _DEFAULT_SYSTEM_PROMPT
    agent = _get_agent(model, prompt_text)
    result = await agent.run(f"Episode title: {title}\n\n{content}")
    return result.output


async def generate_prompt_from_description(description: str, model: str) -> str:
    """Use Gemini to expand a user's plain-text description into a full system prompt."""
    agent = _get_agent(model, "You are a helpful assistant.")
    result = await agent.run(_META_PROMPT.format(user_description=description))
    return result.output


async def refine_prompt(current_prompt: str, instruction: str, model: str) -> str:
    """Apply a natural-language instruction to refine an existing system prompt."""
    agent = _get_agent(model, "You are a helpful assistant.")
    msg = (
        _REFINE_PROMPT_PREFIX
        + current_prompt
        + f"\n\nRefinement instruction: {instruction}"
        + _REFINE_PROMPT_SUFFIX
    )
    result = await agent.run(msg)
    return result.output


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
