## What This Bot Does

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries to a Telegram chat. It:

- **Subscribes** to podcast RSS feeds per user
- **Auto-polls** all subscriptions every 6 hours for new episodes
- **Transcribes** episodes via 3-strategy waterfall: transcript URL → audio transcription (Whisper or Groq w/ fallback) → description fallback
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
make lint                    # run ruff linter
make format                  # run ruff formatter
make migrate-up              # apply all pending DB migrations
make migrate-down version=0  # roll back to target version
make migrate-status          # show applied/pending migration state
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
| `bot/feed.py` | RSS parsing, transcript/audio fetching; delegates transcription via injected `Transcriber` |
| `bot/transcribers/` | `Transcriber` protocol; `ChunkTranscriber` protocol; `WhisperTranscriber` (local faster-whisper); `GroqTranscriber` (Groq API); `AudioPipeline` (format conversion + splitting); `TranscriberPipeline` fallback orchestrator |
| `bot/summarizer.py` | Pydantic AI (Gemini) agent returning `str` (plain Markdown) |
| `bot/scheduler.py` | `AsyncScheduler` polls subscriptions every `POLL_INTERVAL_SECONDS`; marks episodes seen even on error |
| `bot/handlers/` | Telegram command handlers split into `subscribe.py`, `digest.py`, `setprompt.py`, `language.py`; `/digest` is two-step inline-keyboard: pick podcast → pick episode |
| `bot/handlers/language.py` | `/language` command: inline-keyboard for selecting UI language; persists to `users.language` in DB |
| `bot/handlers/admin.py` | `/reload` command (admin-only); `@admin_only` decorator checks `settings.admin_user_id` |
| `bot/i18n.py` | `gettext(lang, key, **kwargs)` — translation strings for `en`/`zh-TW`; unknown lang falls back to `zh-tw` |
| `bot/formatting.py` | Converts Gemini Markdown → Telegram HTML; `format_summary()` and `send_html()` helpers |
| `bot/database.py` | Async SQLite (aiosqlite). Tables: `users`, `podcasts`, `subscriptions`, `episodes`, `user_episodes`. ULIDs for IDs |
| `migrate/` | DB migration package; `python -m migrate [up\|down <version>\|status]` |
| `migrations/` | SQL migration files: `NNN_up.sql` / `NNN_down.sql` |

## Configuration (`.env`)

| Variable | Default | Notes |
|----------|---------|-------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token |
| `TELEGRAM_CHAT_ID` | required | Auto-summary destination |
| `GEMINI_API_KEY` | required | Google Gemini key |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Summarization model |
| `TRANSCRIBER` | `whisper` | Transcription backend: `whisper` or `groq` |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `GROQ_API_KEY` | — | Required when `TRANSCRIBER=groq` |
| `POLL_INTERVAL_SECONDS` | `21600` | 6 hours |
| `ADMIN_USER_ID` | required | Telegram user ID for `/reload` admin command |

## Database Schema

```
users(id ULID, telegram_user_id, chat_id, language, created_at)
podcasts(id ULID, rss_url UNIQUE, title, created_at)
subscriptions(id ULID, user_id→users, podcast_id→podcasts, custom_prompt, created_at)
episodes(id ULID, podcast_id→podcasts, episode_guid, title, published_at, transcript)
  UNIQUE(podcast_id, episode_guid)  -- shared across users
user_episodes(id ULID, user_id→users, episode_id→episodes, summary, notified_at)
  UNIQUE(user_id, episode_id)  -- per-user delivery record
```

## Code Style

**Ruff line limit is 200.** Long string literals (e.g. prompt constants in `bot/summarizer.py`) must use implicit string concatenation across lines — not triple-quoted single-liners.

## Key Patterns & Gotchas

**Docker hot-reload (`/reload` command):** Source is mounted from host (`.:/app`), not baked in — `.git` exists because the host dir is mounted. Requires `openssh-client` in image + `~/.ssh:/root/.ssh:ro` volume for SSH remotes. Anonymous volume `/app/.venv` prevents host mount from shadowing the in-image venv.

**feedparser `FeedParserDict`:** `dict(entry)` drops virtual attributes like `enclosures`. Always extract explicitly:
```python
{**dict(e), "enclosures": list(e.get("enclosures", []))}
```

**Content limits:** transcripts capped at 500KB / 12K chars; audio hard cap 200MB.

**Groq transcriber** (`bot/transcribers/groq.py`): `MAX_GROQ_BYTES = 20_000_000` (not 25MB) — multipart HTTP overhead causes 413 at the nominal limit. Files exceeding this are split via ffmpeg before sending; chunks are transcribed in parallel with `asyncio.gather`.

**ffmpeg audio splitting:** Chunk temp files must use a real format extension (`.mp3`, `.ogg`, etc.), not `.audio` — ffmpeg cannot mux without a known container. Detect format via `ffprobe -show_entries format=format_name` and map to extension.

**`faster_whisper` is imported lazily** inside `WhisperTranscriber._run()` (`bot/transcribers/whisper.py`) to avoid slow module-level load.

**TranscriberPipeline fallback:** When `TRANSCRIBER=groq`, `_build_transcriber()` in `main.py` returns `TranscriberPipeline([GroqTranscriber, WhisperTranscriber])` — Groq is tried first; on failure or `None` result it falls back to local Whisper automatically.

**Error recovery:** scheduler marks episodes seen even on failure — prevents infinite retries.

**Digest state:** episode metadata cached in `context.user_data["digest_eps"]` (not `bot_data`) — per-user isolation prevents cross-user data leakage; expires on bot restart.

**Sending files:** `context.bot.send_document(chat_id=..., document=InputFile(io.BytesIO(content.encode()), filename=...), caption=...)` — see `bot/handlers/transcript.py`. Use distinct `user_data` keys per flow (e.g. `"transcript_eps"` vs `"digest_eps"`).

**aiosqlite testing:** Use a temp file path, NOT `:memory:` — each `aiosqlite.connect()` call opens a new connection, so `:memory:` gives each call a fresh empty DB. Tests use `monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))`.

**DB functions — episode lookup:** `is_episode_seen(user_id, podcast_id, guid)`, `mark_episode_seen(user_id, podcast_id, guid, ...)`, `get_episode_transcript(podcast_id, guid)`, `get_episode_summary(user_id, episode_id)` — episode_id is the episodes row ULID; use `get_episode_id(podcast_id, guid)` to resolve it. Get `podcast_id` from `Subscription.podcast_id` (populated via JOIN in all `get_subscription*` calls).

**`init_db()`** runs pending migrations via `migrate` module's low-level helpers — schema source of truth is `migrations/NNN_up.sql`, not a `_SCHEMA` constant.

## Design Philosophy

**High cohesion:** Each workflow or pipeline should be fully self-contained in its own module. `main.py` should only wire things together — one handler registration per feature, no scattered logic.

## Handler Architecture

- Multi-step flows use `ConversationHandler` (PTB v20) — state is expressed as handler function identity, not `user_data` dicts
- Each `ConversationHandler` instance lives at the **bottom of its own module** (`subscribe_conv`, `unsubscribe_conv` in `subscribe.py`; `digest_conv` in `digest.py`; `setprompt_conv` in `setprompt.py`)
- `bot/handlers/__init__.py` is **pure imports only** — no logic or handler construction
- PTBUserWarning about `per_message=False` with `CallbackQueryHandler` in `ConversationHandler` is expected/informational, not a bug; suppress in pytest via `filterwarnings = ["ignore::telegram.warnings.PTBUserWarning"]` in `[tool.pytest.ini_options]`
- **PTB handler order in states:** `CallbackQueryHandler` patterns are matched in registration order — register more-specific patterns before catch-all ones within the same state list (e.g. `digest:nav:` before `digest:ep:`)
- **`/setprompt` state:** uses `context.user_data["setprompt"]` dict with `subscription_id`, `description`, `generated_prompt` (`mode` is no longer stored — derived from ConversationHandler state)
- **`/setprompt` refinement flow:** `SETPROMPT_REFINE` (state 5) is entered from `SETPROMPT_CHOOSE_MODE` (when `custom_prompt` exists) or `SETPROMPT_AUTO_REVIEW` (via Refine button). User types natural language instructions; `refine_prompt()` in `bot/summarizer.py` applies them via Gemini. Loops until user presses Save. Uses `setdefault().update()` on `user_data["setprompt"]` to preserve `description` across state transitions.
