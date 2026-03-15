import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from shared import database as db
from web.routers import episodes, jobs, subscriptions


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    for var in ("GEMINI_API_KEY", "WEB_USER_TELEGRAM_ID"):
        if not os.environ.get(var):
            raise RuntimeError(f"Missing required env var: {var}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(subscriptions.router, prefix="/api")
    app.include_router(episodes.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.mount("/", StaticFiles(directory="web/static", html=True))
    return app
