from functools import lru_cache

from pydantic_ai import Agent


@lru_cache(maxsize=16)
def _get_agent(model: str, system_prompt: str) -> Agent:
    """Return a cached Agent for a given (model, system_prompt) pair."""
    return Agent(model, instructions=system_prompt)
