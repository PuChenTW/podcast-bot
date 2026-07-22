from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from core import database as db
from core.ai.chat import chat_with_episode_stream
from web.routers.v1.dependencies import CurrentUser, require_episode, require_podcast
from web.routers.v1.pagination import decode_cursor, encode_cursor
from web.routers.v1.schemas import ChatRequest, EpisodeDetail, EpisodeList, EpisodeListItem, Summary

router = APIRouter(tags=["episodes"])

_CHAT_INIT_MESSAGE = (
    "[system] Please briefly introduce this episode's main topics and key points in 2-3 sentences"
    ", then invite the user to ask questions or share what they'd like to explore. Follow the language instruction and style guide in system prompt."
)


@router.get(
    "/podcasts/{podcast_id}/episodes",
    response_model=EpisodeList,
    operation_id="list_podcast_episodes",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Podcast not found"}},
)
async def list_podcast_episodes(
    user_id: CurrentUser,
    podcast: dict = Depends(require_podcast),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    """List episodes for a subscribed podcast, newest first.

    Results include resource-availability flags and use opaque cursor
    pagination. Pass `next_cursor` as `cursor` to retrieve the next page.
    """
    decoded = decode_cursor(cursor)
    after_id = decoded.get("id") if decoded else None
    published_raw = decoded.get("published_at") if decoded else None
    if decoded is not None and (not isinstance(after_id, str) or (published_raw is not None and not isinstance(published_raw, str))):
        raise HTTPException(status_code=422, detail="Invalid cursor")
    try:
        after_published = datetime.fromisoformat(published_raw) if published_raw else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc
    rows = await db.list_episodes_for_user(user_id, podcast["id"], limit + 1, after_published, after_id)
    has_next = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_next:
        last = items[-1]
        next_cursor = encode_cursor(
            {
                "id": last["id"],
                "published_at": last["published_at"].isoformat() if last["published_at"] else None,
            }
        )
    return EpisodeList(items=[EpisodeListItem.model_validate(row) for row in items], next_cursor=next_cursor)


@router.get(
    "/episodes/{episode_id}",
    response_model=EpisodeDetail,
    operation_id="get_episode",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Episode not found"}},
)
async def get_episode(episode: dict = Depends(require_episode)):
    """Return episode metadata and resource-availability flags.

    The current user must subscribe to the episode's podcast. Summary and
    transcript content are available from their dedicated endpoints.
    """
    return EpisodeDetail(
        id=episode["id"],
        podcast_id=episode["podcast_id"],
        title=episode["title"],
        published_at=episode["published_at"],
        description=episode["description"],
        has_summary=episode["summary"] is not None,
        has_transcript=episode["transcript"] is not None,
    )


@router.get(
    "/episodes/{episode_id}/summary",
    response_model=Summary,
    operation_id="get_episode_summary",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Summary not found"}},
)
async def get_episode_summary(episode: dict = Depends(require_episode)):
    """Return the current user's generated summary for an episode.

    A subscribed episode without a generated summary returns `404`. Use the
    summary-job endpoint to generate or regenerate one.
    """
    if episode["summary"] is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return Summary(episode_id=episode["id"], content=episode["summary"])


@router.post(
    "/episodes/{episode_id}/chat",
    operation_id="chat_with_episode",
    responses={200: {"content": {"text/event-stream": {}}}, 400: {"description": "Invalid history"}, 403: {"description": "Subscription required"}, 404: {"description": "Episode not found"}},
)
async def episode_chat(body: ChatRequest, episode: dict = Depends(require_episode)):
    """Chat about an episode over a Server-Sent Events stream.

    Send the user message and the serialized history returned by the previous
    response. Text chunks use the default `message` event; the final `history`
    event contains the serialized history to send with the next turn. An
    `error` event reports failures that occur after streaming begins.
    """
    history: list[ModelMessage] = []
    if body.history:
        try:
            history = ModelMessagesTypeAdapter.validate_json(body.history)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Invalid history") from exc
    user_message = body.message
    if user_message == "__init__" and not body.history:
        user_message = _CHAT_INIT_MESSAGE

    async def generate():
        try:
            async for chunk, messages in chat_with_episode_stream(
                user_message=user_message,
                episode_title=episode["title"] or episode["episode_guid"],
                podcast_title=episode["podcast_title"],
                transcript=episode["condensed_transcript"] or episode["transcript"] or "",
                summary=episode["summary"],
                history=history,
                lang="zh-TW",
                custom_system_prompt=episode["chat_prompt"],
            ):
                if messages is not None:
                    history_json = ModelMessagesTypeAdapter.dump_json(messages).decode()
                    yield f"event: history\ndata: {history_json}\n\n"
                else:
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {exc}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
