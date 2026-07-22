import asyncio
import logging
import secrets
from contextlib import suppress

from core import database as db
from core import feed as feed_module
from core.ai.corrector import correct_transcript
from core.ai.summarizer import summarize_episode
from core.config import get_settings
from core.transcribers import build_transcriber

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_wake_event: asyncio.Event | None = None
_worker_id = secrets.token_urlsafe(12)


class JobExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def start_job_worker() -> None:
    global _worker_task, _wake_event
    await db.requeue_expired_api_jobs()
    _wake_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_job_worker() -> None:
    global _worker_task, _wake_event
    if _worker_task is not None:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task
    _worker_task = None
    _wake_event = None


def notify_job_worker() -> None:
    if _wake_event is not None:
        _wake_event.set()


async def _worker_loop() -> None:
    transcriber = build_transcriber(get_settings())
    while True:
        processed = await run_next_job(transcriber)
        if processed:
            continue
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=1)
        except TimeoutError:
            pass
        _wake_event.clear()


async def run_next_job(transcriber=None) -> bool:
    job = await db.claim_api_job(_worker_id)
    if job is None:
        return False
    heartbeat = asyncio.create_task(_heartbeat(job["id"]))
    try:
        if job["kind"] == "summary":
            await _run_summary_job(job)
        else:
            await _run_transcript_job(job, transcriber or build_transcriber(get_settings()))
        await db.complete_api_job(job["id"], _worker_id)
    except JobExecutionError as exc:
        await db.fail_api_job(job["id"], _worker_id, (exc.code, str(exc)))
    except Exception as exc:
        logger.exception("API job %s failed", job["id"])
        await db.fail_api_job(job["id"], _worker_id, ("internal_error", str(exc)))
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
    return True


async def _heartbeat(job_id: str) -> None:
    while True:
        await asyncio.sleep(20)
        await db.renew_api_job_lease(job_id, _worker_id)


async def _run_summary_job(job: dict) -> None:
    detail = await db.get_episode_for_user(job["user_id"], job["episode_id"])
    if detail is None:
        raise JobExecutionError("episode_not_found", "Episode not found")
    if detail["subscription_id"] is None:
        raise JobExecutionError("subscription_required", "No subscription to this podcast")
    content = detail["transcript"] or detail["description"] or ""
    summary = await summarize_episode(
        detail["title"] or detail["episode_guid"],
        content,
        detail["custom_prompt"],
    )
    await db.update_episode_summary(job["user_id"], job["episode_id"], summary)


async def _run_transcript_job(job: dict, transcriber) -> None:
    detail = await db.get_episode_for_user(job["user_id"], job["episode_id"])
    if detail is None:
        raise JobExecutionError("episode_not_found", "Episode not found")
    if detail["subscription_id"] is None:
        raise JobExecutionError("subscription_required", "No subscription to this podcast")
    feed = await feed_module.fetch_feed(detail["rss_url"])
    entry = next(
        (item for item in feed.entries if (item.get("id") or item.get("link") or item.get("title", "")) == detail["episode_guid"]),
        None,
    )
    if entry is None:
        raise JobExecutionError("episode_source_not_found", "Episode is no longer present in the podcast feed")
    result = await feed_module.get_transcript_result(
        entry,
        transcriber,
        detail["podcast_title"] or "",
        correct_transcript,
    )
    if result is None:
        raise JobExecutionError("transcript_unavailable", "No feed transcript or transcribable audio is available")
    await db.replace_episode_transcript(job["episode_id"], result.text, result.source)
