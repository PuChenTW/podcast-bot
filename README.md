# podcast-bot

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries.

## Features

- Subscribe to podcast RSS feeds per user (supports Apple Podcasts URLs via iTunes Lookup API)
- Auto-polls all subscriptions every 6 hours for new episodes
- Transcribes episodes via 3-strategy waterfall: transcript URL → audio transcription (Whisper or Groq) → description fallback
- Summarizes with Google Gemini; supports 4 per-podcast prompt modes: manual, auto-generate, refine existing, clear
- On-demand digest: paginated episode picker (5/page, ◀/▶ nav) → immediate summary
- Transcript download: same paginated flow, outputs a `.md` file; transcript cached in DB for instant repeat
- Transcript chunking + parallel ASR correction via Gemini for long audio
- Deduplicates episodes to avoid repeated summaries

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API key

## Setup

```bash
git clone <repo-url>
cd podcast-bot
cp .env.example .env        # fill in required vars (see Configuration)
uv sync                     # install dependencies
make run                    # run the bot
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
| `/language` | Switch UI language (English / 繁體中文) |
| `/reload` | Pull latest code and restart (admin only) |

## Configuration

All configuration is via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token from @BotFather |
| `TELEGRAM_CHAT_ID` | required | Chat ID to send auto-summaries to |
| `GEMINI_API_KEY` | required | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Gemini model for summarization |
| `TRANSCRIBER` | `whisper` | Transcription backend: `whisper` (local) or `groq` (API) |
| `WHISPER_MODEL` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` (only when `TRANSCRIBER=whisper`) |
| `GROQ_API_KEY` | — | Required when `TRANSCRIBER=groq` |
| `POLL_INTERVAL_SECONDS` | `21600` | How often to poll for new episodes (default: 6 hours) |
| `ADMIN_USER_ID` | required | Your Telegram user ID — find via [@userinfobot](https://t.me/userinfobot) |

## Docker

```bash
cp .env.example .env        # fill in required vars
make docker-build           # build the image
make docker-up              # start in background
make docker-logs            # tail logs
make docker-down            # stop
```

The entire project directory is bind-mounted into the container, so `.git` is available for `/reload`. The in-image `.venv` is protected via an anonymous volume so the host mount doesn't shadow it.

## Architecture

Single-process async bot built on python-telegram-bot and APScheduler. The pipeline is:

```
RSS feed → fetch_new_episodes() → get_episode_content() → summarize_episode() → Telegram message
```

| File | Role |
|------|------|
| `main.py` | Entry point: wires DB init, scheduler, and Telegram handlers |
| `bot/config.py` | `Settings` dataclass from `.env`; fails fast on missing vars |
| `bot/feed.py` | RSS parsing, transcript/audio fetching, lazy-loaded Whisper transcription |
| `bot/summarizer.py` | Pydantic AI (Gemini) agent returning plain Markdown; prompt generation and refinement |
| `bot/scheduler.py` | Polls subscriptions on interval; marks episodes seen even on error |
| `bot/handlers/` | 7 handler modules: `subscribe.py`, `digest.py`, `transcript.py`, `setprompt.py`, `language.py`, `admin.py`, `callbacks.py` |
| `bot/handlers/callbacks.py` | Pydantic models for typed inline-keyboard callback data |
| `bot/formatting.py` | Converts Gemini Markdown to Telegram HTML |
| `bot/i18n.py` | `gettext(lang, key, **kwargs)` — translation strings for `en`/`zh-TW`; unknown lang falls back to `zh-TW` |
| `bot/database.py` | Async SQLite (aiosqlite). Tables: `users`, `podcasts`, `subscriptions`, `episodes`, `user_episodes` (ULID primary keys) |

## Content Pipeline

Episode content is fetched via a 3-strategy waterfall, stopping at the first success:

1. **Transcript URL** — some podcast feeds publish a direct transcript link; fetched as-is
2. **Audio transcription** — downloads the episode audio (hard cap: 200 MB) and transcribes via the configured backend (`TRANSCRIBER=whisper` runs `faster-whisper` locally; `TRANSCRIBER=groq` sends to Groq's Whisper API, splitting files >20 MB into parallel chunks automatically)
3. **Description fallback** — uses the RSS `<description>` field when audio/transcript are unavailable

Transcripts are capped at 500 KB / 100 K characters before being sent to Gemini. Long transcripts are chunked and corrected in parallel via Gemini before summarization.

## Handler Design Pattern

Multi-step flows (`/subscribe`, `/digest`, `/transcript`, `/setprompt`, `/unsubscribe`) are implemented as PTB `ConversationHandler` state machines. Each state is expressed as a handler function, not a `user_data` dict key.

- Each `ConversationHandler` instance lives at the bottom of its own module
- Per-user `user_data` is keyed by flow (e.g. `"digest_eps"` vs `"transcript_eps"`) to prevent cross-flow data leakage
- Inline-keyboard callback data is structured via Pydantic models in `bot/handlers/callbacks.py`, avoiding string parsing in handler logic

## Database Schema

```
users(id ULID PK, telegram_user_id, chat_id, language, created_at)
podcasts(id ULID PK, rss_url UNIQUE, title, created_at)
subscriptions(id ULID PK, user_id→users, podcast_id→podcasts, custom_prompt, created_at)
episodes(id ULID PK, podcast_id→podcasts, episode_guid, title, published_at, transcript)
  UNIQUE(podcast_id, episode_guid)  -- shared across users
user_episodes(id ULID PK, user_id→users, episode_id→episodes, summary, notified_at)
  UNIQUE(user_id, episode_id)  -- per-user delivery record
```

## Database Migrations

Schema migrations live in `migrations/` and are run via the `migrate` package:

```bash
make migrate-up              # apply all pending migrations
make migrate-down version=0  # roll back to target version
make migrate-status          # show applied/pending state
```

Or directly: `uv run python -m migrate [up|down <version>|status]`

## Development

```bash
uv sync --group dev  # install dev dependencies
make test            # run tests
```

## Notes

**Whisper model tradeoffs:** Larger models (`medium`, `large-v3`) are more accurate but significantly slower and use more memory. `base` is a good default for most use cases.
