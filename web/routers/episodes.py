from fastapi import APIRouter, Depends, HTTPException, Query

from shared import database as db
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
