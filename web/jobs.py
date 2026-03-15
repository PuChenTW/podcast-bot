from collections.abc import Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ulid import ULID

_jobs: dict[str, "Job"] = {}


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    result: str | None = None
    error: str | None = None


def create_job() -> Job:
    job = Job(id=str(ULID()))
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


async def run_job(job_id: str, coro: Coroutine[Any, Any, str | None]) -> None:
    """Execute coro, updating job status. Called via asyncio.create_task."""
    job = _jobs.get(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    try:
        job.result = await coro
        job.status = JobStatus.DONE
    except Exception as exc:
        job.error = str(exc)
        job.status = JobStatus.ERROR
