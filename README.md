# podcast-bot

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries.

## Features

- Subscribe to podcast RSS feeds per user (supports Apple Podcasts URLs via iTunes Lookup API)
- Auto-polls all subscriptions every 6 hours for new episodes
- Transcribes episodes via 3-strategy waterfall: transcript URL → audio transcription (Whisper, Groq, or Nemotron) → description fallback
- Summarizes with Google Gemini; supports 4 per-podcast prompt modes: manual, auto-generate, refine existing, clear
- On-demand digest: paginated episode picker (5/page, ◀/▶ nav) → immediate summary
- Transcript download: same paginated flow, outputs a `.md` file; transcript cached in DB for instant repeat
- Transcript chunking + parallel ASR correction via Gemini for long audio
- Deduplicates episodes to avoid repeated summaries
- Multi-turn AI chat about any episode via `/chat`
- Web UI for managing subscriptions and browsing episode summaries

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- PostgreSQL instance
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API key

## Setup

```bash
git clone <repo-url>
cd podcast-bot
cp .env.example .env        # fill in required vars (see Configuration)
uv sync                     # install dependencies
make migrate-up             # apply DB migrations
make download-nemotron      # optional: only if using TRANSCRIBER=nemotron
make bot-run                # run the bot
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Show available commands |
| `/subscribe` | Subscribe to a podcast RSS feed |
| `/unsubscribe` | Remove a podcast subscription |
| `/list` | List your subscriptions |
| `/digest` | On-demand: pick a podcast → pick an episode (5/page, ◀/▶) → get a summary |
| `/transcript` | Download episode transcript as a `.md` file (same paginated picker as `/digest`) |
| `/setprompt` | Set a per-podcast summarization prompt: manual input, AI auto-generate, refine existing, or clear |
| `/chat` | Pick a podcast → pick an episode → multi-turn AI conversation about the episode; `/end` to exit |
| `/language` | Switch UI language (English / 繁體中文) |

## Configuration

All configuration is via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token from @BotFather |
| `GEMINI_API_KEY` | required | Google Gemini API key |
| `DATABASE_URL` | required | asyncpg connection string (e.g. `postgresql://user:pass@localhost/dbname`) |
| `AI_MODEL` | `google-gla:gemini-flash-lite-latest` | Base model for all AI ops (full `provider:model` string) |
| `SUMMARIZER_MODEL` | `AI_MODEL` | Override model for summarization only |
| `CHAT_MODEL` | `AI_MODEL` | Override model for `/chat` only |
| `CORRECTOR_MODEL` | `AI_MODEL` | Override model for transcript correction only |
| `PROMPT_ENGINEER_MODEL` | `AI_MODEL` | Override model for `/setprompt` AI generation only |
| `CONDENSER_MODEL` | `AI_MODEL` | Override model for transcript condensation only |
| `TRANSCRIBER` | `whisper` | Transcription backend: `whisper` (local), `groq` (API), or `nemotron` (local, multilingual) |
| `WHISPER_MODEL` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` (only when `TRANSCRIBER=whisper`) |
| `GROQ_API_KEY` | — | Required when `TRANSCRIBER=groq` |
| `NEMOTRON_MODEL_DIR` | — | Required when `TRANSCRIBER=nemotron`; sherpa-onnx model dir (run `make download-nemotron`) |
| `NEMOTRON_LANGUAGE` | `auto` | Per-stream language hint: `en`, `zh`, `ja`, … or `auto` |
| `POLL_INTERVAL_SECONDS` | `21600` | How often to poll for new episodes (default: 6 hours) |
| `WEB_USER_TELEGRAM_ID` | required (web) | Telegram user ID for web UI auth |

## Docker

```bash
cp .env.example .env        # fill in required vars
make docker-build           # build the image
make docker-up              # start in background
make docker-logs            # tail logs
make docker-down            # stop
```

Deploys are image-baked — source and dependencies are copied in at build time. To ship a code change: `git pull`, then `make docker-build && make docker-up` (or `docker compose up -d --build`) to rebuild and recreate the containers.

## Architecture

Single-process async bot built on python-telegram-bot and APScheduler. The pipeline is:

```
RSS feed → fetch_new_episodes() → get_transcript() → summarize_episode() → Telegram message
```

| Path | Role |
|------|------|
| `bot_main.py` | Entry point: wires DB init, scheduler, and Telegram handlers |
| `core/config.py` | `Settings` dataclass from `.env`; fails fast on missing vars |
| `core/database.py` | Async PostgreSQL via asyncpg; all DB read/write functions |
| `core/feed.py` | RSS parsing, transcript/audio fetching |
| `core/ai/` | Gemini AI modules: summarizer, chat, transcript corrector, prompt engineer, condenser |
| `core/transcribers/` | Whisper + Groq + Nemotron backends + `AudioPipeline` + `TranscriberPipeline` fallback |
| `bot/scheduler.py` | Polls subscriptions on interval; marks episodes seen even on error |
| `bot/handlers/` | One module per command/flow; shared `episode_picker.py` widget |
| `bot/i18n.py` | `gettext(lang, key, **kwargs)` — translation strings for `en`/`zh-TW` |
| `bot/formatting.py` | Converts Gemini Markdown to Telegram HTML |
| `migrate/` | Migration runner: `python -m migrate [up\|down <version>\|status]` |
| `pg_migrations/` | SQL files: `NNN_up.sql` / `NNN_down.sql` |
| `web/` | FastAPI web UI: REST API + static frontend |
| `web_main.py` | ASGI entry point: `uvicorn web_main:app` |

## Content Pipeline

Episode content is fetched via a 3-strategy waterfall, stopping at the first success:

1. **Transcript URL** — some podcast feeds publish a direct transcript link; fetched as-is
2. **Audio transcription** — downloads the episode audio (hard cap: 200 MB) and transcribes via the configured backend: `TRANSCRIBER=whisper` runs `faster-whisper` locally; `TRANSCRIBER=groq` sends to Groq's Whisper API; `TRANSCRIBER=nemotron` runs NVIDIA Nemotron-3.5 streaming ASR locally via sherpa-onnx (CPU, multilingual, fast). The `groq` and `nemotron` backends fall back to local Whisper on failure. `AudioPipeline` handles format conversion and file splitting for all backends
3. **Description fallback** — uses the RSS `<description>` field when audio/transcript are unavailable

Transcripts are capped at 500 KB / 100 K characters before being sent to Gemini. Long transcripts are chunked and corrected in parallel via Gemini before summarization.

## Database Schema

```
users(id ULID PK, telegram_user_id, chat_id, language, created_at)
podcasts(id ULID PK, rss_url UNIQUE, title, created_at)
subscriptions(id ULID PK, user_id→users, podcast_id→podcasts, custom_prompt, created_at)
episodes(id ULID PK, podcast_id→podcasts, episode_guid, title, published_at, transcript, condensed_transcript, description)
  UNIQUE(podcast_id, episode_guid)  -- shared across users
user_episodes(id ULID PK, user_id→users, episode_id→episodes, summary, notified_at)
  UNIQUE(user_id, episode_id)  -- per-user delivery record
```

## Database Migrations

Schema migrations live in `pg_migrations/` and are run via the `migrate` package:

```bash
make migrate-up              # apply all pending migrations
make migrate-down version=0  # roll back to target version
make migrate-status          # show applied/pending state
```

Or directly: `uv run python -m migrate [up|down <version>|status]`

## Development

```bash
make sync                          # install dev dependencies
make test                          # run tests (parallel via pytest-xdist)
make lint                          # ruff linter
make format                        # ruff formatter
make web-run                       # run web UI on port 8888
```

Tests use `pytest-mock-resources` for PostgreSQL. The fixture is `scope="session"` (one DB per xdist worker) to avoid concurrent `CREATE DATABASE` calls crashing the PMR container under `-n auto`. Each test truncates tables instead of cloning a new DB.

## Notes

**Whisper model tradeoffs:** Larger models (`medium`, `large-v3`) are more accurate but significantly slower and use more memory. `base` is a good default for most use cases.

**Nemotron ASR backend:** NVIDIA Nemotron-3.5 streaming ASR runs locally via sherpa-onnx on CPU (incl. Apple Silicon — no CUDA needed), with much higher throughput than Whisper and built-in punctuation/casing across 40 languages. The model (~665 MB) is git-ignored; run `make download-nemotron` to fetch it into `models/`, then set `TRANSCRIBER=nemotron`. Note: Chinese output is **simplified** characters.
