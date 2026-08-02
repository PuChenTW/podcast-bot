## What This Is

FastAPI web UI for managing podcast subscriptions and browsing episode summaries. Runs independently of the Telegram bot — shares the same PostgreSQL DB.

## Folder Structure

```
web/
  app.py          # FastAPI app factory; mounts routers + static dir; serves index.html via a route (not StaticFiles) to inject WEB_BASE_PATH into <base href>
  auth.py         # get_current_user() dependency — Phase 1: env var; Phase 2: Telegram Login Widget
  jobs.py         # PostgreSQL-backed worker for summary/transcript jobs
  routers/
    v1/            # Versioned catalog, podcast, episode, transcript, prompt, and job routes
  static/
    index.html    # Single-page frontend; <base href="./"> placeholder rewritten by app.py at request time
    app.js        # ES module entry point — imports modules/router.js
    modules/
      utils.js    # api(), esc(), showError(), setNavCrumb(), pollJob()
      router.js   # Hash-based SPA router; registers hashchange + load listeners on import
      home.js     # renderHome() — subscription list + search/subscribe
      episodes.js # renderEpisodeList(), renderEpisodeDetail(), startRegenerate()
      chat.js     # buildChatPanel(), streamChat() (SSE)
    style.css     # Styles
web_main.py       # ASGI entry point: `from web.app import create_app`
```

## API Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/podcast-catalog/search` | Search Apple Podcasts |
| GET | `/api/v1/podcasts` | Search/list the user's subscribed podcasts |
| POST | `/api/v1/subscriptions` | Subscribe and establish the current feed as the no-backlog baseline |
| DELETE | `/api/v1/subscriptions/{id}` | Unsubscribe |
| POST | `/api/v1/podcasts/{id}/sync` | Refresh feed metadata |
| GET | `/api/v1/podcasts/{id}/episodes` | Cursor-paginated episode list |
| GET | `/api/v1/episodes/{id}` | Lightweight episode metadata |
| GET | `/api/v1/episodes/{id}/summary` | User-specific summary |
| GET | `/api/v1/episodes/{id}/transcript` | Shared transcript and provenance |
| GET | `/api/v1/episodes/{id}/transcript/download` | Download transcript Markdown |
| POST | `/api/v1/episodes/{id}/{summary\|transcript}-jobs` | Queue resource regeneration |
| GET | `/api/v1/jobs/{id}` | Poll durable job state |
| GET/PATCH | `/api/v1/subscriptions/{id}/prompts` | Read/update summary and chat prompts |
| POST | `/api/v1/subscriptions/{id}/prompt-drafts` | Generate but do not save a prompt |
| POST | `/api/v1/episodes/{id}/chat` | Existing SSE chat protocol |

## Dev

```bash
make web-run     # uvicorn web_main:app --reload --port 8888
```

Required env vars (in addition to `GEMINI_API_KEY`):

| Variable | Notes |
|----------|-------|
| `WEB_USER_TELEGRAM_ID` | Telegram user ID; web UI auth resolves this to a DB user |
| `WEB_BASE_PATH` | Optional. Set when reverse-proxied under a sub-path (e.g. `tailscale serve --set-path=/podcast-bot 8888` needs `WEB_BASE_PATH=/podcast-bot`). Empty by default. |

## Auth

`get_current_user(request) → user_id (ULID)` is an injectable FastAPI dependency. Phase 1 always resolves to `WEB_USER_TELEGRAM_ID`. Signature must stay `Request → str` for the planned Phase 2 Telegram Login Widget upgrade.

Web-originated users are created with `chat_id=0` — a sentinel that causes the bot scheduler to skip Telegram delivery for those rows.

## New Endpoint Pattern

Use the v1 `require_podcast`, `require_episode`, and `require_subscription` dependencies for ownership checks. Shared podcast/episode lookup uses a nullable subscription join so a missing resource returns 404 while an existing inaccessible resource returns 403.

Feed synchronization calls `upsert_episode` for shared metadata and `ensure_user_episode` for the no-backlog user baseline. `mark_episode_seen` remains the bot-facing convenience wrapper around both operations.

## Job Store

`web/jobs.py` claims durable `api_jobs` rows with `FOR UPDATE SKIP LOCKED`. Workers renew a lease while processing; expired leases are requeued after a crashed worker or service restart without stealing live work from another process. A transcript job replaces cached text only after successful feed/ASR completion and invalidates the condensed transcript; summary regeneration never creates a transcript as a side effect.

## Frontend DOM Updates

Frontend uses ES modules (`<script type="module">`). FastAPI's StaticFiles serves correct MIME types — no bundler needed. `marked` is loaded from CDN as a global and accessed directly (not imported).

All API calls and asset references resolve against `document.baseURI` (or plain relative paths), never a hardcoded `/api/v1` or `/`, so the frontend keeps working when reverse-proxied under `WEB_BASE_PATH`.

`home.js` does in-place DOM mutations for subscribe/unsubscribe — no `location.hash` reload. Subscribe success appends a new card directly to the grid (or creates the grid if first subscription); unsubscribe removes the card and shows empty-state if the grid is now empty. This avoids the hashchange no-op when already on `#/`.

## RSS Description

`entry.get("summary")` is feedparser's field for RSS `<description>` content. It often contains HTML markup — render with `innerHTML`, not `textContent`/escaped.
