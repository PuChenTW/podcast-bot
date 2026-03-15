# Web UI — Phase 1 Design Spec

**Date:** 2026-03-15
**Status:** Approved

---

## Context

The podcast bot currently operates entirely through Telegram. As features grew (transcription, AI chat, custom prompts), a web interface would offer a better browsing and reading experience. Phase 1 adds five features: subscribe/unsubscribe, set custom summarization prompt, browse episode lists, read episode content (summary / transcript / condensed transcript), and regenerate summaries on demand.

Auth is deferred — a stub returns a hardcoded user for prototyping. Telegram Login Widget will be the Phase 2 auth path.

---

## Decisions

| Topic | Decision | Rationale |
|-------|----------|-----------|
| Deployment | Separate FastAPI process | Clean separation; both services share image and SQLite file |
| Frontend | Vanilla HTML/JS, hash-based SPA | No build step; fastest to iterate; sufficient for Phase 1 |
| Backend | FastAPI + uvicorn | Async-native; matches existing aiosqlite/pydantic stack |
| Auth | Stub returning hardcoded user | Deferred; interface designed for easy Telegram Login Widget swap |
| Episode source | DB only | Episodes populated by bot's 6-hour poller; avoids real-time RSS fetch |
| Regenerate summary | Async + polling | Returns `job_id` 202 immediately; frontend polls `/api/jobs/{id}` every 2s |
| SQLite concurrency | WAL mode in `init_db()` | Safe concurrent reads + single writer; applied on every startup (idempotent) |

---

## Navigation

Three-level hash-based SPA:

```
#/                              → Homepage: subscribed podcast cards + subscribe form
#/podcast/{sub_id}              → Episode list for one podcast
#/episode/{podcast_id}/{guid}   → Episode detail: Summary / Transcript / Condensed tabs
```

---

## Project Structure

```
podcast-bot/
├── bot/                            # unchanged
├── web/
│   ├── __init__.py
│   ├── app.py                      # FastAPI factory + lifespan
│   ├── auth.py                     # get_current_user() stub
│   ├── jobs.py                     # in-process job registry
│   └── routers/
│       ├── __init__.py
│       ├── subscriptions.py        # subscribe/unsubscribe/prompt endpoints
│       ├── episodes.py             # episode list + detail endpoints
│       └── jobs.py                 # regenerate + polling endpoints
├── web/static/
│   ├── index.html                  # SPA shell (nav + <main id="content">)
│   ├── app.js                      # router + all page renderers
│   └── style.css
└── web_main.py                     # entry: uvicorn web_main:app
```

`web/` imports from `bot/` only — never the reverse.

---

## Backend

### `web/app.py`

```python
@asynccontextmanager
async def lifespan(app):
    await db.init_db()          # applies pending migrations + enables WAL
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("Missing required env var: GEMINI_API_KEY")
    yield

def create_app():
    app = FastAPI(lifespan=lifespan)
    app.include_router(subscriptions.router, prefix="/api")
    app.include_router(episodes.router,      prefix="/api")
    app.include_router(jobs_router.router,   prefix="/api")
    app.mount("/", StaticFiles(directory="web/static", html=True))
    return app
```

Do **not** import `bot.config.get_settings` — it requires `TELEGRAM_BOT_TOKEN` and `ADMIN_USER_ID` which the web process does not use.

### `web/auth.py`

```python
async def get_current_user(request: Request) -> str:
    """
    Phase 1: always returns the user identified by WEB_USER_TELEGRAM_ID.
    Phase 2: replace body with Telegram Login Widget token verification.
    Signature (Request → str user_id ULID) must not change.

    chat_id=0 is a sentinel for web-originated users with no Telegram chat context.
    The bot scheduler skips delivery for rows where chat_id=0.
    """
    telegram_id = int(os.environ["WEB_USER_TELEGRAM_ID"])
    return await db.get_or_create_user(telegram_id, chat_id=0)
```

### API Endpoints

#### Subscriptions

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/subscriptions` | Returns `[{id, podcast_id, podcast_title, rss_url, custom_prompt}]` |
| `POST` | `/api/subscriptions` | Body: `{rss_url}`. Pipeline: `resolve_rss_url → fetch_feed → parse title → add_subscription → mark all current entries seen` (same no-backlog logic as bot's `subscribe.py`) |
| `DELETE` | `/api/subscriptions/{sub_id}` | Verify `subscription.user_id == current_user`; return 403/404/204 |
| `PUT` | `/api/subscriptions/{sub_id}/prompt` | Body: `{prompt: str \| null}` |

#### Episodes

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/subscriptions/{sub_id}/episodes` | Resolves `sub_id → podcast_id` via `get_subscription_by_id`, then calls `get_episodes_by_podcast_with_summary(user_id, podcast_id)`. Returns `[{episode_guid, title, published_at, has_summary}]` |
| `GET` | `/api/podcasts/{podcast_id}/episodes/{guid}/detail` | Calls `get_episode_detail(user_id, podcast_id, guid)`. Returns `{title, summary, transcript, condensed_transcript}` — any field may be null |

#### Jobs

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/podcasts/{podcast_id}/episodes/{guid}/regenerate` | Verifies user has subscription to podcast; creates job; launches `asyncio.create_task`; returns `{job_id}` 202 |
| `GET` | `/api/jobs/{job_id}` | Returns `{status: pending\|running\|done\|error, result?, error?}` |

The regenerate task calls `summarize_episode(title, transcript, custom_prompt)` then `update_episode_summary(user_id, podcast_id, guid, summary)`.

---

## New DB Functions (`shared/database.py`)

### WAL mode

Add to `init_db()` after migrations:
```python
async with _connect() as db:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.commit()
```

### `get_episode_detail(user_id, podcast_id, guid) -> dict | None`

```sql
SELECT e.id, e.title, e.published_at, e.transcript, e.condensed_transcript,
       ue.summary
FROM episodes e
LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = ?
WHERE e.podcast_id = ? AND e.episode_guid = ?
```

### `get_episodes_by_podcast_with_summary(user_id, podcast_id, limit=50) -> list[dict]`

```sql
SELECT e.id, e.episode_guid, e.title, e.published_at,
       CASE WHEN ue.summary IS NOT NULL THEN 1 ELSE 0 END AS has_summary
FROM episodes e
LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = ?
WHERE e.podcast_id = ?
ORDER BY e.published_at DESC LIMIT ?
```

### `update_episode_summary(user_id, podcast_id, guid, summary) -> None`

```python
episode_id = await get_episode_id(podcast_id, guid)
# INSERT OR REPLACE into user_episodes (id, user_id, episode_id, summary, notified_at)
```

---

## Async Job System (`web/jobs.py`)

In-process dict + `asyncio.Task`. No external queue — jobs are ephemeral (~30s lifecycle).

```python
@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    result: str | None = None
    error: str | None = None
```

**Constraint:** Pin uvicorn to `--workers 1`. Multiple workers would split the job store across processes, breaking `GET /api/jobs/{id}` lookups.

---

## Frontend (`web/static/`)

Single `index.html` shell. All navigation via `location.hash`. `app.js` structure:

- `route()` — dispatches on `hashchange` + `load`
- `api(path, opts)` — thin fetch wrapper, throws on non-2xx
- `renderHome()` — podcast card grid + subscribe form
- `renderEpisodeList(subId)` — episode list with summary status badges
- `renderEpisodeDetail(podId, guid)` — tabs for Summary / Transcript / Condensed
- `pollJob(jobId, onDone, onError)` — recursive `setTimeout` every 2s

Use `marked.js` (CDN) to render Markdown summaries as HTML. Tabs are CSS class toggles — no JS framework.

---

## Docker Compose

```yaml
services:
  bot:
    # ... unchanged ...

  web:
    build: .
    env_file: .env
    command: ["uv", "run", "uvicorn", "web_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
    ports:
      - "8000:8000"
    volumes:
      - .:/app          # shares podcast_bot.db with bot service
      - /app/.venv
    restart: unless-stopped
```

Both services use the same image and share `podcast_bot.db` via `.:/app` bind mount.

---

## Environment Variables

Web process requires only:

| Variable | Notes |
|----------|-------|
| `GEMINI_API_KEY` | For summary regeneration |
| `WEB_USER_TELEGRAM_ID` | Phase 1 auth stub — your Telegram user ID |

Bot vars (`TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`) are not required by the web process.

---

## Reuse Map

| Module | Used by web? |
|--------|-------------|
| `shared/database.py` | Yes — all existing functions + 3 new ones |
| `bot/feed.py` | Yes — `resolve_rss_url`, `fetch_feed` for subscribe |
| `bot/ai/summarizer.py` | Yes — `summarize_episode()` in regenerate job |
| `bot/config.py` | No — web reads env vars directly |
| `bot/handlers/subscribe.py` | Reference only — replicate subscribe flow logic |
| Everything else | No |

---

## Verification

1. `uv sync` — clean after adding fastapi/uvicorn to `pyproject.toml`
2. `uv run uvicorn web_main:app --reload --port 8000` — server starts
3. `curl http://localhost:8000/api/subscriptions` — returns list
4. Subscribe to a real RSS feed via `POST /api/subscriptions`
5. Browse `http://localhost:8000/#/podcast/{sub_id}` — episodes appear after bot poll
6. Episode detail page — all three tabs render (null fields show gracefully)
7. "Regenerate" → spinner → polls `/api/jobs/{id}` → result updates in place
8. `make docker-up` — both `bot` and `web` services start cleanly
