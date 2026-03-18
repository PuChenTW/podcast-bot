## What Lives Here

`core/` is the shared business logic layer. It has no Telegram dependency and is imported by both `bot/` and `web/`.

| Module | Role |
|--------|------|
| `config.py` | `Settings` dataclass from `.env`; `get_settings()` singleton |
| `database.py` | Async PostgreSQL via asyncpg; all DB read/write functions |
| `feed.py` | RSS parsing, transcript URL resolution, audio download, episode content waterfall |
| `ai/summarizer.py` | `summarize_episode(title, content, custom_prompt?)` → Markdown str |
| `ai/chat.py` | `chat_with_episode(...)` → multi-turn conversation |
| `ai/corrector.py` | `correct_transcript(text, podcast_title, ep_title, description)` |
| `ai/prompt_engineer.py` | `generate_prompt_from_description()`, `refine_prompt()` |
| `ai/condenser.py` | `condense_transcript(...)` → ~10 K chars for chat context |
| `ai/_agent.py` | LRU-cached `Agent` factory keyed on `(model, system_prompt)` |
| `transcribers/` | Whisper + Groq backends + `AudioPipeline` + `TranscriberPipeline` fallback |

## Database schema

```
users(id ULID, telegram_user_id, chat_id, language, created_at)
podcasts(id ULID, rss_url UNIQUE, title, created_at)
subscriptions(id ULID, user_id→users, podcast_id→podcasts, custom_prompt, created_at)
episodes(id ULID, podcast_id→podcasts, episode_guid, title, published_at, transcript, condensed_transcript, description)
  UNIQUE(podcast_id, episode_guid)  -- shared across users
user_episodes(id ULID, user_id→users, episode_id→episodes, summary, notified_at)
  UNIQUE(user_id, episode_id)  -- per-user delivery record
```

Schema source of truth is `migrations/NNN_up.sql`. `init_db()` applies pending migrations via the `migrate` module's low-level helpers — there is no `_SCHEMA` constant.

## asyncpg testing

Tests must patch `_get_pool` in `core.database` or set `DATABASE_URL` to a real test PostgreSQL instance. Mock the pool at the module level — asyncpg does not support in-memory databases.

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
| `get_episode_condensed_transcript` | `(podcast_id, guid)` | Returns condensed transcript string or None |
| `save_episode_condensed_transcript` | `(podcast_id, guid, condensed_transcript)` | Writes condensed transcript |

`podcast_id` comes from `Subscription.podcast_id`, populated via JOIN in all `get_subscription*` calls.

## feedparser FeedParserDict

`dict(entry)` silently drops virtual attributes including `enclosures`. Always extract explicitly:
```python
{**dict(e), "enclosures": list(e.get("enclosures", []))}
```

## Content limits

- Transcripts: hard cap at 500 KB / 100 K chars (whichever is smaller); chunked at 12 000 chars for parallel ASR correction
- Audio downloads: hard cap at 200 MB

## Error recovery

The scheduler marks an episode as seen even when processing fails. This is intentional — prevents infinite retry loops on bad episodes.

## Settings in tests

`tests/conftest.py` manually constructs a `Settings(...)` instance from `core.config`. Any new field added to `Settings` must also be added to the fixture — it will fail at collection time otherwise.

## AI module pattern

All AI ops read model names from `get_settings()` and use `_get_agent(model, system_prompt)` (LRU-cached). They return plain strings, not structured objects.

## Transcriber wiring

`TranscriberPipeline` has no knowledge of which backends to use — wiring happens in `main.py` via `_build_transcriber()`. `core.transcribers` exports: `AudioPipeline`, `ChunkTranscriber`, `Transcriber`, `WhisperTranscriber`, `GroqTranscriber`, `TranscriberPipeline`.
