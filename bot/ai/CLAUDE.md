## Module overview

| Module | Entry point | Purpose |
|--------|-------------|---------|
| `_agent.py` | `_get_agent(model, system_prompt)` | LRU-cached pydantic-ai `Agent` factory; keyed on `(model, system_prompt)` pair; `model` is a full `provider:model` string |
| `summarizer.py` | `summarize_episode(title, content, custom_prompt?)` | Returns plain Markdown `str`; reads `summarizer_model` from settings |
| `chat.py` | `chat_with_episode(...)` | Multi-turn chat; returns `(reply_str, updated_history)`; reads `chat_model` from settings |
| `corrector.py` | `correct_transcript(text, podcast_title, episode_title, description)` | ASR error correction; reads `corrector_model` from settings |
| `prompt_engineer.py` | `refine_prompt()`, `generate_prompt_from_description()` | Rewrites prompts per natural-language instruction; reads `prompt_engineer_model` from settings; does NOT persist |

## Summarizer return type

`summarize_episode()` returns a plain Markdown `str`, not a structured object. The Pydantic AI agent is configured to return `str` directly.

## Long prompt strings

Prompt string constants must use implicit string concatenation across lines, NOT triple-quoted single-liners. Ruff line limit is 200 — triple-quoted blocks that exceed it cannot be split.

## refine_prompt()

`refine_prompt(existing_prompt, user_instruction)` sends the existing prompt + natural-language instruction to Gemini and returns a revised prompt string. It does not persist anything — callers in `bot/handlers/setprompt.py` handle persistence.
