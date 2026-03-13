# podcast-bot

Telegram bot that monitors podcast RSS feeds and delivers AI-generated summaries.

## Features

- Subscribe to podcast RSS feeds per user
- Auto-polls all subscriptions every 6 hours for new episodes
- Transcribes episodes via waterfall: transcript URL → Whisper audio → description fallback
- Summarizes with Google Gemini; supports per-podcast custom prompts
- On-demand digest: pick a podcast and episode for immediate summary
- Custom prompt refinement: iteratively tweak prompts via natural language conversation
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
| `/digest` | On-demand: pick a podcast → pick an episode → get a summary |
| `/transcript` | Download episode transcript as a `.md` file |
| `/setprompt` | Set a custom prompt for a podcast (manual, AI auto-generate, or iterative refinement) |
| `/language` | Switch UI language (English / 繁體中文) |
| `/reload` | Pull latest code and restart (admin only) |

## Configuration

All configuration is via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | required | Bot API token from @BotFather |
| `TELEGRAM_CHAT_ID` | required | Chat ID to send auto-summaries to |
| `GEMINI_API_KEY` | required | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model for summarization |
| `WHISPER_MODEL` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
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
| `bot/feed.py` | RSS parsing, transcript/audio fetching, Whisper transcription |
| `bot/summarizer.py` | Pydantic AI (Gemini) agent returning plain Markdown |
| `bot/scheduler.py` | Polls subscriptions on interval; marks episodes seen even on error |
| `bot/handlers/` | Telegram command handlers: `subscribe.py`, `digest.py`, `setprompt.py` |
| `bot/formatting.py` | Converts Gemini Markdown to Telegram HTML |
| `bot/database.py` | Async SQLite (aiosqlite). Tables: `users`, `subscriptions`, `episodes` |

## Development

```bash
uv sync --group dev  # install dev dependencies
make test            # run tests
```

## Notes

**Schema changes require a DB reset.** There is no migration logic — delete `podcast_bot.db` and restart.

**Whisper model tradeoffs:** Larger models (`medium`, `large-v3`) are more accurate but significantly slower and use more memory. `base` is a good default for most use cases.
