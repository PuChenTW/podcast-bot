## What This Bot Does

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries to a Telegram chat. It:

- **Subscribes** to podcast RSS feeds per user
- **Auto-polls** all subscriptions every 6 hours for new episodes
- **Transcribes** episodes via 3-strategy waterfall: transcript URL → Whisper audio transcription → description fallback
- **Summarizes** with Google Gemini (Pydantic AI): returns plain Markdown `str`; supports per-podcast `custom_prompt`
- **On-demand digest**: `/digest` lets users pick a podcast → episode for immediate transcription + summary
- **Custom prompts**: `/setprompt` lets users set per-podcast summarization style (manual input, AI auto-generate, or iterative refinement via natural language conversation)
- **Deduplicates** episodes per subscription to avoid repeated summaries
- **Unsubscribes** from podcasts: `/unsubscribe` lets users remove a subscription via inline keyboard
- **Language selection**: `/language` lets users switch between supported UI languages (en/zh-TW)
- **Transcript download**: `/transcript` mirrors `/digest` two-step flow but outputs a `.md` file (title, summary, raw transcript); transcript cached in DB — repeat selection is instant

## Commands

```bash
cp .env.example .env         # first run: fill in required vars
uv sync                      # install / sync dependencies
uv sync --group dev          # include pytest + pytest-asyncio
uv run python main.py        # run the bot (or: make run)
uv add <package>             # add a dependency
make test                    # run pytest (or: uv run pytest tests/ -v)
make docker-build            # build Docker image
make docker-up               # start bot in background (docker compose up -d)
make docker-logs             # tail container logs
```

## Docker

`docker-compose.yml` mounts `.env` and `podcast_bot.db` as bind mounts — secrets and data stay on host.
`podcast_bot.db` is auto-created on first run; no manual setup needed.

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
| `bot/handlers/` | Telegram command handlers split into `subscribe.py`, `digest.py`, `setprompt.py`, `language.py`; `/digest` is two-step inline-keyboard: pick podcast → pick episode |
| `bot/handlers/language.py` | `/language` command: inline-keyboard for selecting UI language; persists to `users.language` in DB |
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
users(id ULID, telegram_user_id, chat_id, language, created_at)
subscriptions(id ULID, user_id→users, podcast_title, rss_url, custom_prompt, created_at)
episodes(id ULID, subscription_id→subscriptions, episode_guid, title, published_at,
         summary, transcript, notified_at)
  UNIQUE(subscription_id, episode_guid)  -- dedup key
```

## Key Patterns & Gotchas

**Docker hot-reload (`/reload` command):** Source is mounted from host (`.:/app`), not baked in — `.git` exists because the host dir is mounted. Requires `openssh-client` in image + `~/.ssh:/root/.ssh:ro` volume for SSH remotes. Anonymous volume `/app/.venv` prevents host mount from shadowing the in-image venv.

**feedparser `FeedParserDict`:** `dict(entry)` drops virtual attributes like `enclosures`. Always extract explicitly:
```python
{**dict(e), "enclosures": list(e.get("enclosures", []))}
```

**Content limits:** transcripts capped at 500KB / 12K chars; audio hard cap 200MB.

**`faster_whisper` is imported lazily** inside `_run_transcription()` to avoid slow module-level load.

**Error recovery:** scheduler marks episodes seen even on failure — prevents infinite retries.

**Digest state:** episode metadata cached in `context.user_data["digest_eps"]` (not `bot_data`) — per-user isolation prevents cross-user data leakage; expires on bot restart.

**Sending files:** `context.bot.send_document(chat_id=..., document=InputFile(io.BytesIO(content.encode()), filename=...), caption=...)` — see `bot/handlers/transcript.py`. Use distinct `user_data` keys per flow (e.g. `"transcript_eps"` vs `"digest_eps"`).

**aiosqlite testing:** Use a temp file path, NOT `:memory:` — each `aiosqlite.connect()` call opens a new connection, so `:memory:` gives each call a fresh empty DB. Tests use `monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))`.

## Design Philosophy

**High cohesion:** Each workflow or pipeline should be fully self-contained in its own module. `main.py` should only wire things together — one handler registration per feature, no scattered logic.

## Handler Architecture

- Multi-step flows use `ConversationHandler` (PTB v20) — state is expressed as handler function identity, not `user_data` dicts
- Each `ConversationHandler` instance lives at the **bottom of its own module** (`subscribe_conv`, `unsubscribe_conv` in `subscribe.py`; `digest_conv` in `digest.py`; `setprompt_conv` in `setprompt.py`)
- `bot/handlers/__init__.py` is **pure imports only** — no logic or handler construction
- PTBUserWarning about `per_message=False` with `CallbackQueryHandler` in `ConversationHandler` is expected/informational, not a bug; suppress in pytest via `filterwarnings = ["ignore::telegram.warnings.PTBUserWarning"]` in `[tool.pytest.ini_options]`
- **`/setprompt` state:** uses `context.user_data["setprompt"]` dict with `subscription_id`, `description`, `generated_prompt` (`mode` is no longer stored — derived from ConversationHandler state)
- **`/setprompt` refinement flow:** `SETPROMPT_REFINE` (state 5) is entered from `SETPROMPT_CHOOSE_MODE` (when `custom_prompt` exists) or `SETPROMPT_AUTO_REVIEW` (via Refine button). User types natural language instructions; `refine_prompt()` in `bot/summarizer.py` applies them via Gemini. Loops until user presses Save. Uses `setdefault().update()` on `user_data["setprompt"]` to preserve `description` across state transitions.
