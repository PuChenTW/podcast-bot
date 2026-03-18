import asyncio

from fastapi import APIRouter, Depends, HTTPException

from core import database as db
from core import feed as feed_module
from core.ai import summarizer
from core.ai.corrector import correct_transcript
from core.config import get_settings
from core.transcribers import AudioPipeline, GroqTranscriber, TranscriberPipeline, WhisperTranscriber
from web import jobs as job_store
from web.auth import get_current_user

router = APIRouter()


def _build_transcriber():
    s = get_settings()
    if s.transcriber_backend == "groq":
        return TranscriberPipeline(
            [
                AudioPipeline(GroqTranscriber(s.groq_api_key)),
                AudioPipeline(WhisperTranscriber(s.whisper_model)),
            ]
        )
    return AudioPipeline(WhisperTranscriber(s.whisper_model))


@router.post("/podcasts/{podcast_id}/episodes/{guid}/regenerate", status_code=202)
async def regenerate_summary(podcast_id: str, guid: str, user_id: str = Depends(get_current_user)):
    # Verify user has a subscription to this podcast
    subs = await db.get_subscriptions(user_id)
    sub = next((s for s in subs if s.podcast_id == podcast_id), None)
    if sub is None:
        raise HTTPException(status_code=403, detail="No subscription to this podcast")

    detail = await db.get_episode_detail(user_id, podcast_id, guid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    job = job_store.create_job()

    async def _task():
        transcript = detail["transcript"]
        if not transcript:
            # No transcript stored — fetch RSS entry and transcribe
            podcast = await db.get_podcast(podcast_id)
            feed = await feed_module.fetch_feed(podcast["rss_url"])
            entry = next(
                (e for e in feed.entries if (e.get("id") or e.get("link") or e.get("title", "")) == guid),
                None,
            )
            if entry:
                transcriber = _build_transcriber()
                transcript = await feed_module.get_transcript(entry, transcriber, podcast.get("title", ""), corrector=correct_transcript)
                if transcript:
                    await db.update_episode_transcript(podcast_id, guid, transcript)

        summary = await summarizer.summarize_episode(
            detail["title"] or guid,
            transcript or detail.get("description") or "",
            sub.custom_prompt,
        )
        await db.update_episode_summary(user_id, podcast_id, guid, summary)
        return summary

    asyncio.create_task(job_store.run_job(job.id, _task()))
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.status, "result": job.result, "error": job.error}
