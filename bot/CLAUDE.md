## What Lives Here

`bot/` is the Telegram layer. It depends on `core/` but has no web dependency.

| Module | Role |
|--------|------|
| `scheduler.py` | APScheduler job: polls all subscriptions every `POLL_INTERVAL_SECONDS`; marks episode seen even on failure (prevents retry loops). `_process_episode` returns whether it sent, so the 1s rate-limit pause is skipped for muted subscriptions |
| `handlers/` | One module per command/flow — see `bot/handlers/CLAUDE.md` |
| `i18n.py` | `gettext(lang, key, **kwargs)`; unknown lang falls back to `zh-TW` |
| `formatting.py` | Markdown → Telegram HTML conversion |

## Application wiring

`bot_main.py` is the only place that registers handlers and builds the `Application`. One `add_handler` call per feature — no logic lives in `bot_main.py`.

## Handlers index

| Module | Command |
|--------|---------|
| `subscribe.py` | `/subscribe`, `/unsubscribe` |
| `digest.py` | `/digest` |
| `transcript.py` | `/transcript` |
| `setprompt.py` | `/setprompt` |
| `chat.py` | `/chat` |
| `notify.py` | `/notify` |
| `language.py` | `/language` |
| `episode_picker.py` | Shared paginated picker widget |

## user_data scoping

`context.user_data` is per-user; `context.bot_data` is shared across all users. Always use `user_data` for per-flow state.

## i18n

All user-visible strings go through `gettext(lang, key, **kwargs)`. The `lang` value comes from `context.user_data` or the DB. Never hardcode display strings in handlers.
