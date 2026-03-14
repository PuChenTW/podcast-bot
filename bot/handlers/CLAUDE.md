## ConversationHandler placement

Each `ConversationHandler` instance is defined at the **bottom of its own module**: `subscribe_conv` and `unsubscribe_conv` in `subscribe.py`; `digest_conv` in `digest.py`; `setprompt_conv` in `setprompt.py`. Never construct handlers in `__init__.py` or `main.py`.

## __init__.py is pure imports

`bot/handlers/__init__.py` re-exports handler objects only. No logic, no handler construction.

## PTBUserWarning is expected

The warning about `per_message=False` with `CallbackQueryHandler` inside a `ConversationHandler` is informational, not a bug. Suppress it in pytest:
```toml
[tool.pytest.ini_options]
filterwarnings = ["ignore::telegram.warnings.PTBUserWarning"]
```

## CallbackQueryHandler registration order

Within a single state's handler list, register more-specific `CallbackQueryHandler` patterns before catch-all ones. Example: `digest:nav:` before `digest:ep:`.

## user_data key isolation

Episode metadata is stored in `context.user_data`, NOT `context.bot_data` — bot_data is shared across all users. Use distinct keys per flow: `"digest_eps"` for `/digest`, `"transcript_eps"` for `/transcript`. State expires on bot restart.

## /setprompt user_data schema

`context.user_data["setprompt"]` holds a dict with keys: `subscription_id`, `description`, `generated_prompt`. `mode` is NOT stored — it is derived from the current ConversationHandler state. Always use `setdefault().update()` when writing to preserve `description` across state transitions.

## /setprompt refinement flow

`SETPROMPT_REFINE` (state 5) is reachable from two states: `SETPROMPT_CHOOSE_MODE` (when a `custom_prompt` already exists) and `SETPROMPT_AUTO_REVIEW` (via the Refine button). The loop continues until the user presses Save, which persists and ends the conversation.

## /chat user_data schema

`context.user_data["chat_session"]` holds: `episode_title`, `podcast_title`, `transcript`, `summary`, `history` (list of pydantic-ai `ModelMessage`), `lang`. Cleared on `/end` or `chat:end` callback. Keys `"chat_eps"` / `"chat_offset"` are navigation state, cleared after episode selection.

## episode_picker.py

`build_episode_keyboard(eps, offset, subscription_id, lang, EpCallback, NavCallback)` is a shared widget used by `/digest`, `/transcript`, and `/chat`. Pass the handler-specific callback dataclasses as arguments.

## Sending files

Use `context.bot.send_document(chat_id=..., document=InputFile(io.BytesIO(content.encode()), filename=...), caption=...)`. Reference implementation: `bot/handlers/transcript.py`.
