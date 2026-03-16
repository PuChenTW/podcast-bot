## What Lives Here

`core/` is the shared business logic layer. It has no Telegram dependency and is imported by both `bot/` and `web/`.

| Module | Role |
|--------|------|
| `config.py` | `Settings` dataclass from `.env`; `get_settings()` singleton |
| `database.py` | Async SQLite via aiosqlite; all DB read/write functions |
| `feed.py` | RSS parsing, transcript URL resolution, audio download, episode content waterfall |
| `ai/summarizer.py` | `summarize_episode(title, content, custom_prompt?)` → Markdown str |
| `ai/chat.py` | `chat_with_episode(...)` → multi-turn conversation |
| `ai/corrector.py` | `correct_transcript(text, podcast_title, ep_title, description)` |
| `ai/prompt_engineer.py` | `generate_prompt_from_description()`, `refine_prompt()` |
| `ai/condenser.py` | `condense_transcript(...)` → ~10 K chars for chat context |
| `ai/_agent.py` | LRU-cached `Agent` factory keyed on `(model, system_prompt)` |
| `transcribers/` | Whisper + Groq backends + `AudioPipeline` + `TranscriberPipeline` fallback |

## aiosqlite testing

Use a temp file path, NOT `:memory:`. Tests must patch `DB_PATH` in `core.database`:
```python
import core.database as db_module
monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
```

## DB functions — episode lookup

| Function | Signature | Notes |
|----------|-----------|-------|
| `is_episode_seen` | `(user_id, podcast_id, guid)` | |
| `mark_episode_seen` | `(user_id, podcast_id, guid, ...)` | |
| `get_episode_transcript` | `(podcast_id, guid)` | |
| `get_episode_summary` | `(user_id, episode_id)` | `episode_id` is the ULID from `episodes` |
| `get_episode_id` | `(podcast_id, guid)` | Resolves guid → ULID |
| `get_podcast` | `(podcast_id)` | Returns podcast row dict or None |
| `update_episode_transcript` | `(podcast_id, guid, transcript)` | Writes transcript to `episodes` row |

## AI module pattern

All AI ops read model names from `get_settings()` and use `_get_agent(model, system_prompt)` (LRU-cached). They return plain strings, not structured objects.

## Transcriber wiring

`TranscriberPipeline` has no knowledge of which backends to use — wiring happens in `main.py` via `_build_transcriber()`. `core.transcribers` exports: `AudioPipeline`, `ChunkTranscriber`, `Transcriber`, `WhisperTranscriber`, `GroqTranscriber`, `TranscriberPipeline`.
