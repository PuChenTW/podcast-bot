import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import database as db
from core.audio_workspace import cleanup_stale_audio_workspaces
from web import jobs
from web.routers.v1 import router as api_v1_router

API_DESCRIPTION = """
Manage podcast subscriptions and turn podcast episodes into AI-assisted
knowledge. The API discovers podcasts, synchronizes RSS feeds, exposes episode
metadata, generates summaries and transcripts, manages custom prompts, and
streams episode-grounded chat.

## Recommended workflow for agents

1. Search the podcast catalog or create a subscription from a known RSS URL.
2. List the subscribed podcast's episodes using opaque cursor pagination.
3. Fetch an episode's summary or transcript. A `404` can mean that the resource
   has not been generated yet.
4. Create the corresponding background job, follow its `Location` header, and
   poll until the status is `done` or `error`. On success, fetch `result_url`.
5. Use the chat endpoint for questions grounded in the episode. Chat responds as
   a Server-Sent Events stream, not a JSON document, and returns a `history`
   event to send with the next turn.

## Behavior

- All operations are versioned under `/api/v1` and act as the server's current
  user.
- Podcast, episode, subscription, prompt, and job access is scoped to that user.
- Pagination cursors are opaque; clients should store and replay them unchanged.
- Summaries are user-specific. Transcripts and podcast metadata are shared, but
  require access through a subscription.
- Synchronizing a feed discovers episodes but does not generate summaries or
  transcripts. Those are explicit background jobs.
"""

OPENAPI_TAGS = [
    {
        "name": "podcast-catalog",
        "description": "Discover podcasts and obtain RSS feed URLs for new subscriptions.",
    },
    {
        "name": "podcasts",
        "description": "Manage the current user's subscriptions and synchronize podcast RSS feeds.",
    },
    {
        "name": "episodes",
        "description": "Browse episode metadata, read summaries, and stream episode-grounded chat.",
    },
    {
        "name": "transcripts",
        "description": "Read or download cached episode transcripts and inspect their provenance.",
    },
    {
        "name": "jobs",
        "description": "Generate summaries and transcripts through durable asynchronous jobs.",
    },
    {
        "name": "prompts",
        "description": "Read, update, or draft per-subscription summary and chat instructions.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stale_audio_workspaces()
    await db.init_db()
    for var in ("GEMINI_API_KEY", "WEB_USER_TELEGRAM_ID"):
        if not os.environ.get(var):
            raise RuntimeError(f"Missing required env var: {var}")
    await jobs.start_job_worker()
    try:
        yield
    finally:
        await jobs.stop_job_worker()
        await db.close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Podcast Bot API",
        summary="Discover podcasts and turn episodes into summaries, transcripts, and grounded conversations.",
        description=API_DESCRIPTION,
        version="1.0.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.include_router(api_v1_router)
    app.mount("/", StaticFiles(directory="web/static", html=True))
    return app
