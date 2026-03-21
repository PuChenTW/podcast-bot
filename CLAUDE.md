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
uv sync --all-extras         # install / sync dependencies
uv sync --group dev --all-extras         # include pytest + pytest-asyncio
uv run python main.py        # run the bot (or: make run)
make web-run                 # run web UI (uvicorn, port 8000)
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

`docker-compose.yml` mounts `.env` as a bind mount — secrets stay on host. Database is PostgreSQL (external); configure `DATABASE_URL` in `.env`.

**Hot-reload (`/reload` command):** source is mounted from host (`.:/app`). Requires `openssh-client` in image + `~/.ssh:/root/.ssh:ro` volume for SSH remotes. Anonymous volume `/app/.venv` prevents the host mount from shadowing the in-image venv.

## Architecture

Single-process async bot (python-telegram-bot + APScheduler).

```
RSS feed → fetch_new_episodes() → get_transcript() → summarize_episode() → Telegram message
```

| Path | Role |
|------|------|
| `main.py` | Entry point: wires DB init, scheduler, Telegram handlers |
| `core/config.py` | `Settings` dataclass from `.env`; fails fast on missing vars |
| `core/database.py` | Async PostgreSQL via asyncpg — see `core/CLAUDE.md` |
| `core/feed.py` | RSS parsing, transcript/audio fetching |
| `core/ai/` | Gemini AI: summarizer, chat, transcript corrector, prompt engineer, condenser — see `core/CLAUDE.md` |
| `core/transcribers/` | Whisper + Groq backends, fallback pipeline — see `core/CLAUDE.md` |
| `bot/scheduler.py` | Polls subscriptions every `POLL_INTERVAL_SECONDS` |
| `bot/handlers/` | Telegram command handlers — see `bot/handlers/CLAUDE.md` |
| `bot/i18n.py` | `gettext(lang, key, **kwargs)`; unknown lang falls back to `zh-TW` |
| `bot/formatting.py` | Markdown → Telegram HTML conversion |
| `migrate/` | Migration runner: `python -m migrate [up\|down <version>\|status]` |
| `pg_migrations/` | SQL files: `NNN_up.sql` / `NNN_down.sql` |
| `web/` | FastAPI web UI: REST API + static frontend for managing subscriptions/episodes — see `web/CLAUDE.md` |
| `web_main.py` | ASGI entry point: `uvicorn web_main:app` |

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
| `CONDENSER_MODEL` | `AI_MODEL` | Override model for transcript condensation only |
| `TRANSCRIBER` | `whisper` | `whisper` or `groq` |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `GROQ_API_KEY` | — | Required when `TRANSCRIBER=groq` |
| `DATABASE_URL` | required | asyncpg connection string (e.g. `postgresql://user:pass@localhost/dbname`) |
| `POLL_INTERVAL_SECONDS` | `21600` | 6 hours |
| `ADMIN_USER_ID` | required | Telegram user ID for `/reload` |
| `WEB_USER_TELEGRAM_ID` | required (web) | Telegram user ID for web UI auth |

## Testing

Tests use `pytest-mock-resources` for PostgreSQL fixtures. Key design:

- `_postgres` is `scope="session"` — one DB per xdist worker, migrations applied once via `asyncio.run()` at session start. Avoids concurrent `CREATE DATABASE` storms under `-n auto`.
- `tmp_db` / `pg_fresh_db` fixtures create a fresh per-test asyncpg pool and `TRUNCATE` all tables instead of cloning a new DB each time.
- `test_migrate.py` uses its own `_migrate_postgres = create_postgres_fixture()` (function-scoped) because migration tests need a clean `schema_migrations` table, which the shared session DB already has populated.

## Code Style

**Ruff line limit is 200.** Long string literals must use implicit string concatenation across lines — not triple-quoted single-liners.

## Design Philosophy

High cohesion: each workflow is fully self-contained in its own module. `main.py` only wires things together — one handler registration per feature, no scattered logic.

