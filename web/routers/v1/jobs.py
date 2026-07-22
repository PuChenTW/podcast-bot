from fastapi import APIRouter, Depends, HTTPException, Response, status

from core import database as db
from web import jobs as job_worker
from web.routers.v1.dependencies import CurrentUser, require_episode
from web.routers.v1.schemas import Job

router = APIRouter(tags=["jobs"])


async def _create_job(kind: str, user_id: str, episode: dict, response: Response) -> Job:
    result_url = f"/api/v1/episodes/{episode['id']}/{kind}"
    job = await db.create_api_job(user_id, episode["id"], kind, result_url)
    response.headers["Location"] = f"/api/v1/jobs/{job['id']}"
    job_worker.notify_job_worker()
    return Job.model_validate(job)


@router.post(
    "/episodes/{episode_id}/summary-jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="create_summary_job",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Episode not found"}, 409: {"description": "Job conflict"}},
)
async def create_summary_job(response: Response, user_id: CurrentUser, episode: dict = Depends(require_episode)):
    return await _create_job("summary", user_id, episode, response)


@router.post(
    "/episodes/{episode_id}/transcript-jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="create_transcript_job",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Episode not found"}, 409: {"description": "Job conflict"}},
)
async def create_transcript_job(response: Response, user_id: CurrentUser, episode: dict = Depends(require_episode)):
    return await _create_job("transcript", user_id, episode, response)


@router.get(
    "/jobs/{job_id}",
    response_model=Job,
    operation_id="get_job",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Job not found"}},
)
async def get_job(job_id: str, user_id: CurrentUser):
    job = await db.get_api_job_for_user(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Job.model_validate(job)
