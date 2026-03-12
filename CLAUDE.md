## What This Bot Does

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries to a Telegram chat. It:

- **Subscribes** to podcast RSS feeds per user
- **Auto-polls** all subscriptions every 6 hours for new episodes
- **Transcribes** episodes via 3-strategy waterfall: transcript URL → Whisper audio transcription → description fallback
- **Summarizes** with Google Gemini (Pydantic AI): returns plain Markdown `str`; supports per-podcast `custom_prompt`
- **On-demand digest**: `/digest` lets users pick a podcast → episode for immediate transcription + summary
- **Custom prompts**: `/setprompt` lets users set per-podcast summarization style (manual input or AI auto-generate)
- **Deduplicates** episodes per subscription to avoid repeated summaries

## Commands

```bash
cp .env.example .env         # first run: fill in required vars
uv sync                      # install / sync dependencies
uv run python main.py        # run the bot
uv add <package>             # add a dependency
```

No test suite or linter configured yet.

## Architecture

Single-process async bot (python-telegram-bot + APScheduler).

```
RSS feed → fetch_new_episodes() → get_episode_content() → summarize_episode() → Telegram message
```

**Modules:**

| File | Role |
|------|------|
| `main.py` | Entry point: wires DB init, scheduler, and Telegram handlers |
| `bot/config.py` | `Settings` dataclass from `.env`; fails fast on missing vars |
| `bot/feed.py` | RSS parsing, transcript/audio fetching, Whisper transcription |
| `bot/summarizer.py` | Pydantic AI (Gemini) agent returning `str` (plain Markdown) |
| `bot/scheduler.py` | `AsyncScheduler` polls subscriptions every `POLL_INTERVAL_SECONDS`; marks episodes seen even on error |
| `bot/handlers/` | Telegram command handlers split into `subscribe.py`, `digest.py`, `setprompt.py`; `/digest` is two-step inline-keyboard: pick podcast → pick episode |
| `bot/formatting.py` | Converts Gemini Markdown → Telegram HTML; `format_summary()` and `send_html()` helpers |
| `bot/database.py` | Async SQLite (aiosqlite). Tables: `users`, `subscriptions`, `episodes`. ULIDs for IDs |

## Configuration (`.env`)

| Variable | Default | Notes |
|----------|---------|-------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token |
| `TELEGRAM_CHAT_ID` | required | Auto-summary destination |
| `GEMINI_API_KEY` | required | Google Gemini key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Summarization model |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `POLL_INTERVAL_SECONDS` | `21600` | 6 hours |

## Database Schema

```
users(id ULID, telegram_user_id, chat_id)
subscriptions(id ULID, user_id→users, podcast_title, rss_url, custom_prompt)
episodes(id ULID, subscription_id→subscriptions, episode_guid, title,
         summary, transcript, notified_at)
  UNIQUE(subscription_id, episode_guid)  -- dedup key
```

**Schema changes require DB reset:** No migration logic — delete `podcast_bot.db` and restart.

**`/setprompt` state:** Multi-step flow uses `context.user_data["setprompt"]` dict with `subscription_id`, `mode` (`manual`/`auto`), `description`, `generated_prompt`.

## Key Patterns & Gotchas

**feedparser `FeedParserDict`:** `dict(entry)` drops virtual attributes like `enclosures`. Always extract explicitly:
```python
{**dict(e), "enclosures": list(e.get("enclosures", []))}
```

**Content limits:** transcripts capped at 500KB / 12K chars; audio hard cap 200MB.

**`faster_whisper` is imported lazily** inside `_run_transcription()` to avoid slow module-level load.

**Error recovery:** scheduler marks episodes seen even on failure — prevents infinite retries.

**Digest state:** episode metadata cached in `context.bot_data` during the two-step flow; expires on bot restart.
