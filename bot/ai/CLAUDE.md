## Module overview

| Module | Entry point | Purpose |
|--------|-------------|---------|
| `_agent.py` | `_get_agent(model, system_prompt)` | LRU-cached pydantic-ai `Agent` factory; keyed on `(model, system_prompt)` pair |
| `summarizer.py` | `summarize_episode()` | Returns plain Markdown `str` |
| `chat.py` | `chat_with_episode()` | Multi-turn chat; returns `(reply_str, updated_history)` |
| `corrector.py` | `correct_transcript()` | ASR error correction; first arg is `model` so callers can `partial`-bind it |
| `prompt_engineer.py` | `refine_prompt()` | Rewrites a prompt per natural-language instruction; does NOT persist |

## Summarizer return type

`summarize_episode()` returns a plain Markdown `str`, not a structured object. The Pydantic AI agent is configured to return `str` directly.

## Long prompt strings

Prompt string constants must use implicit string concatenation across lines, NOT triple-quoted single-liners. Ruff line limit is 200 — triple-quoted blocks that exceed it cannot be split.

## refine_prompt()

`refine_prompt(existing_prompt, user_instruction)` sends the existing prompt + natural-language instruction to Gemini and returns a revised prompt string. It does not persist anything — callers in `bot/handlers/setprompt.py` handle persistence.
