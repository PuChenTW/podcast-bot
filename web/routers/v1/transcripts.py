import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from core import database as db
from web import jobs as job_worker
from web.routers.v1.dependencies import CurrentUser, require_episode
from web.routers.v1.schemas import Transcript, TranscriptStatus

router = APIRouter(tags=["transcripts"])

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _filename(podcast_title: str, episode_title: str) -> str:
    podcast = _UNSAFE_FILENAME.sub("_", podcast_title).strip("_")[:40] or "podcast"
    episode = _UNSAFE_FILENAME.sub("_", episode_title).strip("_")[:60] or "episode"
    return f"{podcast}_{episode}.md"


@router.get(
    "/episodes/{episode_id}/transcript",
    response_model=Transcript,
    operation_id="get_episode_transcript",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Transcript not found"}},
)
async def get_episode_transcript(episode: dict = Depends(require_episode)):
    """Return an episode transcript and its provenance.

    `source` identifies whether the transcript came from the podcast feed or
    audio transcription. A subscribed episode without a transcript returns
    `404`.
    """
    if episode["transcript"] is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return Transcript(
        episode_id=episode["id"],
        content=episode["transcript"],
        source=episode["transcript_source"],
        updated_at=episode["transcript_updated_at"],
    )


@router.get(
    "/episodes/{episode_id}/transcript/download",
    response_class=PlainTextResponse,
    operation_id="download_episode_transcript",
    responses={200: {"content": {"text/markdown": {}}}, 403: {"description": "Subscription required"}, 404: {"description": "Transcript not found"}},
)
async def download_episode_transcript(episode: dict = Depends(require_episode)):
    """Download an episode transcript as a Markdown attachment.

    The document includes the episode title, podcast title, publication date,
    and cached transcript content.
    """
    if episode["transcript"] is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    episode_title = episode["title"] or episode["episode_guid"]
    published = episode["published_at"].isoformat() if episode["published_at"] else "Unknown"
    content = f"# {episode_title}\n\n**Podcast:** {episode['podcast_title']}\n\n**Published:** {published}\n\n## Transcript\n\n{episode['transcript']}\n"
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{_filename(episode["podcast_title"], episode_title)}"'},
    )


@router.get(
    "/episodes/{episode_id}/transcript-text",
    response_model=TranscriptStatus,
    operation_id="fetch_episode_transcript",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Episode not found"}},
)
async def fetch_episode_transcript(user_id: CurrentUser, episode: dict = Depends(require_episode)):
    """Get an episode transcript, generating it first if it is not cached yet.

    Returns `status="ready"` with the full transcript text when it is available.
    Otherwise transcription is queued and `status="generating"` is returned
    immediately — transcribing an episode takes minutes, so do other work and
    call this again later rather than waiting. `status="failed"` means the last
    attempt failed and calling again will retry.

    Prefer this over the separate transcript and job endpoints: it is a single
    call that reports its own progress.
    """
    if episode["transcript"] is not None:
        return TranscriptStatus(
            episode_id=episode["id"],
            status="ready",
            content=episode["transcript"],
            chars=len(episode["transcript"]),
            source=episode["transcript_source"],
            updated_at=episode["transcript_updated_at"],
        )
    # Report a finished failure before queueing again, so a retry loop cannot mask
    # a permanently untranscribable episode as perpetually "generating".
    previous = await db.get_latest_api_job(user_id, episode["id"], "transcript")
    if previous is not None and previous["status"] == "error":
        return TranscriptStatus(
            episode_id=episode["id"],
            status="failed",
            job_id=previous["id"],
            error_code=previous["error_code"],
            error_message=previous["error_message"],
        )
    job = await db.create_api_job(user_id, episode["id"], "transcript", f"/api/v1/episodes/{episode['id']}/transcript")
    job_worker.notify_job_worker()
    return TranscriptStatus(episode_id=episode["id"], status="generating", job_id=job["id"])
