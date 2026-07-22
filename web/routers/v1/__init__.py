from fastapi import APIRouter

from web.routers.v1 import catalog, episodes, jobs, podcasts, prompts, transcripts

router = APIRouter(prefix="/api/v1")
router.include_router(catalog.router)
router.include_router(podcasts.router)
router.include_router(episodes.router)
router.include_router(transcripts.router)
router.include_router(prompts.router)
router.include_router(jobs.router)
