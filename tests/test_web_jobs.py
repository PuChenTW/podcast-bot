import pytest

from core import database as db


async def _job_fixture():
    user_id = await db.get_or_create_user(2020, 0)
    podcast_id = await db.get_or_create_podcast("https://jobs.example/feed", "Jobs")
    episode_id = await db.upsert_episode(podcast_id, "episode-1", title="Episode")
    await db.ensure_user_episode(user_id, episode_id)
    return user_id, episode_id


@pytest.mark.asyncio
async def test_create_and_claim_persisted_job(tmp_db):
    user_id, episode_id = await _job_fixture()
    created = await db.create_api_job(user_id, episode_id, "summary", f"/api/v1/episodes/{episode_id}/summary")
    claimed = await db.claim_api_job("worker-1")
    assert claimed["id"] == created["id"]
    assert claimed["status"] == "running"


@pytest.mark.asyncio
async def test_second_worker_cannot_claim_active_lease(tmp_db):
    user_id, episode_id = await _job_fixture()
    await db.create_api_job(user_id, episode_id, "summary", f"/api/v1/episodes/{episode_id}/summary")
    await db.claim_api_job("worker-1")
    assert await db.claim_api_job("worker-2") is None


@pytest.mark.asyncio
async def test_expired_jobs_are_requeued_after_restart(tmp_db):
    user_id, episode_id = await _job_fixture()
    created = await db.create_api_job(user_id, episode_id, "summary", f"/api/v1/episodes/{episode_id}/summary")
    await db.claim_api_job("worker-1")
    async with db._connect() as connection:
        await connection.execute("UPDATE api_jobs SET lease_expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
    await db.requeue_expired_api_jobs()
    reclaimed = await db.claim_api_job("worker-2")
    assert reclaimed["id"] == created["id"]
