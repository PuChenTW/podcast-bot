import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import database as db
from web import jobs
from web.routers.v1 import router as api_v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    app = FastAPI(title="Podcast Bot API", version="1.0.0", lifespan=lifespan)
    app.include_router(api_v1_router)
    app.mount("/", StaticFiles(directory="web/static", html=True))
    return app
