from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from core import database as db
from core.ai.chat import chat_with_episode_stream
from web.auth import get_current_user

router = APIRouter()


PAGE_SIZE = 20


@router.get("/subscriptions/{sub_id}/episodes")
async def list_episodes(sub_id: str, page: int = Query(default=0, ge=0), user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = await db.get_episodes_by_podcast_with_summary(user_id, sub.podcast_id, limit=PAGE_SIZE + 1, offset=page * PAGE_SIZE)
    has_next = len(rows) > PAGE_SIZE
    return {"episodes": rows[:PAGE_SIZE], "page": page, "has_next": has_next, "has_prev": page > 0}


@router.get("/podcasts/{podcast_id}/episodes/{guid}/detail")
async def episode_detail(podcast_id: str, guid: str, user_id: str = Depends(get_current_user)):
    subs = await db.get_subscriptions(user_id)
    if not any(s.podcast_id == podcast_id for s in subs):
        raise HTTPException(status_code=403, detail="No subscription to this podcast")
    detail = await db.get_episode_detail(user_id, podcast_id, guid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return detail


class ChatRequest(BaseModel):
    message: str
    history: str  # JSON string from ModelMessagesTypeAdapter.dump_json(); "" for first turn


_CHAT_INIT_MESSAGE = "Please briefly introduce this episode's main topics and key points in 2-3 sentences, then invite the user to ask questions or share what they'd like to explore."


@router.post("/podcasts/{podcast_id}/episodes/{guid}/chat")
async def episode_chat(podcast_id: str, guid: str, body: ChatRequest, user_id: str = Depends(get_current_user)):
    subs = await db.get_subscriptions(user_id)
    if not any(s.podcast_id == podcast_id for s in subs):
        raise HTTPException(status_code=403, detail="No subscription to this podcast")

    if len(body.message) > 4000:
        raise HTTPException(status_code=400, detail="Message too long")
    if len(body.history) > 200_000:
        raise HTTPException(status_code=400, detail="History too large")

    history: list[ModelMessage] = []
    if body.history:
        try:
            history = ModelMessagesTypeAdapter.validate_json(body.history)
        except ValidationError:
            raise HTTPException(status_code=400, detail="Invalid history")

    detail = await db.get_episode_detail(user_id, podcast_id, guid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    podcast_title = next((s.podcast_title for s in subs if s.podcast_id == podcast_id), "")
    transcript = detail.get("condensed_transcript") or detail.get("transcript") or ""
    summary = detail.get("summary")
    episode_title = detail.get("title") or guid

    user_message = body.message
    if user_message == "__init__" and not body.history:
        user_message = _CHAT_INIT_MESSAGE

    async def generate():
        try:
            async for chunk, msgs in chat_with_episode_stream(
                user_message=user_message,
                episode_title=episode_title,
                podcast_title=podcast_title,
                transcript=transcript,
                summary=summary,
                history=history,
                lang="zh-TW",
            ):
                if msgs is not None:
                    history_json = ModelMessagesTypeAdapter.dump_json(msgs).decode()
                    yield f"event: history\ndata: {history_json}\n\n"
                else:
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {e}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
