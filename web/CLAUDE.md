## What This Is

FastAPI web UI for managing podcast subscriptions and browsing episode summaries. Runs independently of the Telegram bot — shares the same SQLite DB.

## Folder Structure

```
web/
  app.py          # FastAPI app factory; mounts routers + static dir
  auth.py         # get_current_user() dependency — Phase 1: env var; Phase 2: Telegram Login Widget
  jobs.py         # In-memory async job store (ULID-keyed); used for long-running tasks
  routers/
    subscriptions.py  # CRUD for subscriptions + prompt updates
    episodes.py       # Episode list (paginated) + episode detail
    jobs.py           # Trigger regenerate-summary job; poll job status
  static/
    index.html    # Single-page frontend
    app.js        # Vanilla JS; talks to /api/* endpoints
    style.css     # Styles
web_main.py       # ASGI entry point: `from web.app import create_app`
```

## API Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/subscriptions` | List user's subscriptions |
| POST | `/api/subscriptions` | Subscribe to RSS URL (marks existing episodes seen — no backlog flood); returns 422 if URL is not a valid RSS feed (`feed.bozo and not feed.entries`) |
| DELETE | `/api/subscriptions/{sub_id}` | Unsubscribe |
| PUT | `/api/subscriptions/{sub_id}/prompt` | Update custom summarization prompt |
| POST | `/api/subscriptions/{sub_id}/refresh` | Fetch RSS, upsert new episodes, return `{new_count}` |
| GET | `/api/subscriptions/{sub_id}/episodes` | Paginated episode list (`?page=N`, page size 20) |
| GET | `/api/podcasts/{podcast_id}/episodes/{guid}/detail` | Full episode detail (transcript + summary) |
| POST | `/api/podcasts/{podcast_id}/episodes/{guid}/regenerate` | Queue summary regeneration → returns `{job_id}` |
| GET | `/api/jobs/{job_id}` | Poll job status (`pending`/`running`/`done`/`error`) |

## Dev

```bash
make web-run     # uvicorn web_main:app --reload --port 8000
```

Required env vars (in addition to `GEMINI_API_KEY`):

| Variable | Notes |
|----------|-------|
| `WEB_USER_TELEGRAM_ID` | Telegram user ID; web UI auth resolves this to a DB user |

## Auth

`get_current_user(request) → user_id (ULID)` is an injectable FastAPI dependency. Phase 1 always resolves to `WEB_USER_TELEGRAM_ID`. Signature must stay `Request → str` for the planned Phase 2 Telegram Login Widget upgrade.

Web-originated users are created with `chat_id=0` — a sentinel that causes the bot scheduler to skip Telegram delivery for those rows.

## New Endpoint Pattern

All `{sub_id}` endpoints: `get_subscription_by_id` → 404 if None → 403 if `sub.user_id != user_id` → do work.

`db.mark_episode_seen` is an UPSERT — safe to call unconditionally, no duplicates. Use `db.is_episode_seen` to check existence beforehand if you need to count new entries.

## Job Store

`web/jobs.py` is an in-memory store. Jobs are lost on restart. Only used for `regenerate` which is fire-and-forget; clients poll `/api/jobs/{id}` until `done` or `error`.

## Frontend DOM Updates

`app.js` does in-place DOM mutations for subscribe/unsubscribe — no `location.hash` reload. Subscribe success appends a new card directly to the grid (or creates the grid if first subscription); unsubscribe removes the card and shows empty-state if the grid is now empty. This avoids the hashchange no-op when already on `#/`.

## RSS Description

`entry.get("summary")` is feedparser's field for RSS `<description>` content. It often contains HTML markup — render with `innerHTML`, not `textContent`/escaped.
