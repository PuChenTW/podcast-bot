## What Lives Here

`bot/` is the Telegram layer. It depends on `core/` but has no web dependency.

| Module | Role |
|--------|------|
| `scheduler.py` | APScheduler job: polls all subscriptions every `POLL_INTERVAL_SECONDS`; marks episode seen even on failure (prevents retry loops) |
| `handlers/` | One module per command/flow — see `bot/handlers/CLAUDE.md` |
| `i18n.py` | `gettext(lang, key, **kwargs)`; unknown lang falls back to `zh-TW` |
| `formatting.py` | Markdown → Telegram HTML conversion |

## Application wiring

`main.py` is the only place that registers handlers and builds the `Application`. One `add_handler` call per feature — no logic lives in `main.py`.

## i18n

All user-visible strings go through `gettext(lang, key, **kwargs)`. The `lang` value comes from `context.user_data` or the DB. Never hardcode display strings in handlers.
