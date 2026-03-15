## What This Bot Does

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries to a Telegram chat. Key features:

- **Subscribe/unsubscribe** to podcast RSS feeds per user
- **Auto-polls** every 6 hours for new episodes; transcribes + summarizes automatically
- **Transcription waterfall:** transcript URL → Whisper/Groq audio transcription → description fallback
- **On-demand digest:** `/digest` — pick podcast → pick episode → instant summary
- **Custom prompts:** `/setprompt` — per-podcast summarization style (manual, AI-generated, or iterative refinement)
- **Transcript download:** `/transcript` — outputs `.md` file; transcript cached in DB for instant repeat access
- **Language selection:** `/language` — switches UI between `en` / `zh-TW`
- **Chat:** `/chat` — pick podcast/episode → multi-turn AI conversation about the episode

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

`docker-compose.yml` mounts `.env` and `podcast_bot.db` as bind mounts — secrets and data stay on host. `podcast_bot.db` is auto-created on first run.

**Hot-reload (`/reload` command):** source is mounted from host (`.:/app`). Requires `openssh-client` in image + `~/.ssh:/root/.ssh:ro` volume for SSH remotes. Anonymous volume `/app/.venv` prevents the host mount from shadowing the in-image venv.

## Architecture

Single-process async bot (python-telegram-bot + APScheduler).

```
RSS feed → fetch_new_episodes() → get_episode_content() → summarize_episode() → Telegram message
```

| Path | Role |
|------|------|
| `main.py` | Entry point: wires DB init, scheduler, Telegram handlers |
| `bot/config.py` | `Settings` dataclass from `.env`; fails fast on missing vars |
| `bot/database.py` | Async SQLite via aiosqlite — see `bot/CLAUDE.md` |
| `bot/feed.py` | RSS parsing, transcript/audio fetching |
| `bot/scheduler.py` | Polls subscriptions every `POLL_INTERVAL_SECONDS` |
| `bot/ai/` | Gemini AI: summarizer, chat, transcript corrector, prompt engineer — see `bot/ai/CLAUDE.md` |
| `bot/transcribers/` | Whisper + Groq backends, fallback pipeline — see `bot/transcribers/CLAUDE.md` |
| `bot/handlers/` | Telegram command handlers — see `bot/handlers/CLAUDE.md` |
| `bot/i18n.py` | `gettext(lang, key, **kwargs)`; unknown lang falls back to `zh-TW` |
| `bot/formatting.py` | Markdown → Telegram HTML conversion |
| `migrate/` | Migration runner: `python -m migrate [up\|down <version>\|status]` |
| `migrations/` | SQL files: `NNN_up.sql` / `NNN_down.sql` |

## Configuration (`.env`)

| Variable | Default | Notes |
|----------|---------|-------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token |
| `GEMINI_API_KEY` | required | Google Gemini key |
| `AI_MODEL` | `google-gla:gemini-flash-lite-latest` | Base model for all AI ops (full `provider:model` string) |
| `SUMMARIZER_MODEL` | `AI_MODEL` | Override model for summarization only |
| `CHAT_MODEL` | `AI_MODEL` | Override model for `/chat` only |
| `CORRECTOR_MODEL` | `AI_MODEL` | Override model for transcript correction only |
| `PROMPT_ENGINEER_MODEL` | `AI_MODEL` | Override model for `/setprompt` AI generation only |
| `TRANSCRIBER` | `whisper` | `whisper` or `groq` |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `GROQ_API_KEY` | — | Required when `TRANSCRIBER=groq` |
| `POLL_INTERVAL_SECONDS` | `21600` | 6 hours |
| `ADMIN_USER_ID` | required | Telegram user ID for `/reload` |

## Code Style

**Ruff line limit is 200.** Long string literals must use implicit string concatenation across lines — not triple-quoted single-liners.

## Design Philosophy

High cohesion: each workflow is fully self-contained in its own module. `main.py` only wires things together — one handler registration per feature, no scattered logic.
