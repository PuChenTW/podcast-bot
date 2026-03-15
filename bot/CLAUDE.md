## Database schema

```
users(id ULID, telegram_user_id, chat_id, language, created_at)
podcasts(id ULID, rss_url UNIQUE, title, created_at)
subscriptions(id ULID, user_id→users, podcast_id→podcasts, custom_prompt, created_at)
episodes(id ULID, podcast_id→podcasts, episode_guid, title, published_at, transcript)
  UNIQUE(podcast_id, episode_guid)  -- shared across users
user_episodes(id ULID, user_id→users, episode_id→episodes, summary, notified_at)
  UNIQUE(user_id, episode_id)  -- per-user delivery record
```

Schema source of truth is `migrations/NNN_up.sql`. `init_db()` applies pending migrations via the `migrate` module's low-level helpers — there is no `_SCHEMA` constant.

## aiosqlite testing

Use a temp file path, NOT `:memory:`. Each `aiosqlite.connect()` call opens a new independent connection; `:memory:` gives each call a fresh empty database. Tests must patch `DB_PATH`:
```python
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

`tests/conftest.py` manually constructs a `Settings(...)` instance. Any new field added to `Settings` must also be added to the fixture — it will fail at collection time otherwise.
