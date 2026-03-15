from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from bot import feed as rss
from bot.feed import _parse_published
from shared import database as db
from web.auth import get_current_user

router = APIRouter()


class SubscribeRequest(BaseModel):
    rss_url: str


class PromptRequest(BaseModel):
    prompt: str | None


@router.get("/subscriptions")
async def list_subscriptions(user_id: str = Depends(get_current_user)):
    subs = await db.get_subscriptions(user_id)
    return [s.model_dump() for s in subs]


@router.post("/subscriptions", status_code=201)
async def create_subscription(body: SubscribeRequest, user_id: str = Depends(get_current_user)):
    rss_url = await rss.resolve_rss_url(body.rss_url)
    feed = await rss.fetch_feed(rss_url)
    title = getattr(feed.feed, "title", rss_url)
    sub_id = await db.add_subscription(user_id, title, rss_url)
    sub = await db.get_subscription_by_id(sub_id)
    # Mark all current feed entries as seen — no backlog flood
    # sub.podcast_id is already resolved by add_subscription; no extra DB call needed
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if guid:
            await db.mark_episode_seen(user_id, sub.podcast_id, guid, title=entry.get("title"), published_at=_parse_published(entry))
    return sub.model_dump()


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(sub_id: str, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.remove_subscription_by_id(sub_id)


@router.put("/subscriptions/{sub_id}/prompt")
async def update_prompt(sub_id: str, body: PromptRequest, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.set_subscription_prompt(sub_id, body.prompt)
    return {"ok": True}
