import pytest

from web.jobs import JobStatus, create_job, get_job, run_job


def test_create_and_get_job():
    job = create_job()
    assert job.status == JobStatus.PENDING
    retrieved = get_job(job.id)
    assert retrieved is job


def test_get_job_missing_returns_none():
    result = get_job("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_run_job_success():
    job = create_job()

    async def succeed():
        return "result text"

    await run_job(job.id, succeed())
    assert job.status == JobStatus.DONE
    assert job.result == "result text"
    assert job.error is None


@pytest.mark.asyncio
async def test_run_job_failure():
    job = create_job()

    async def fail():
        raise ValueError("something went wrong")

    await run_job(job.id, fail())
    assert job.status == JobStatus.ERROR
    assert job.error == "something went wrong"
    assert job.result is None
