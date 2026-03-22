import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import database as db
from core import feed as rss
from core.ai.prompt_engineer import generate_prompt_from_description
from core.feed import parse_published
from web.auth import get_current_user

router = APIRouter()


class SubscribeRequest(BaseModel):
    rss_url: str


class PromptRequest(BaseModel):
    prompt: str | None


class ChatPromptRequest(BaseModel):
    prompt: str | None


class GeneratePromptRequest(BaseModel):
    description: str = ""


@router.get("/podcasts/search")
async def search_podcasts(q: str = Query(default=""), user_id: str = Depends(get_current_user)):
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://itunes.apple.com/search",
                params={"term": q, "media": "podcast", "limit": 10},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="搜尋逾時，請稍後再試。")
    results = []
    for item in data.get("results", []):
        feed_url = item.get("feedUrl")
        if not feed_url:
            continue
        results.append(
            {
                "name": item.get("collectionName", ""),
                "artist": item.get("artistName", ""),
                "artwork_url": item.get("artworkUrl100", item.get("artworkUrl60", "")),
                "feed_url": feed_url,
            }
        )
    return results


@router.get("/subscriptions")
async def list_subscriptions(user_id: str = Depends(get_current_user)):
    subs = await db.get_subscriptions(user_id)
    return [s.model_dump() for s in subs]


@router.post("/subscriptions", status_code=201)
async def create_subscription(body: SubscribeRequest, user_id: str = Depends(get_current_user)):
    rss_url = await rss.resolve_rss_url(body.rss_url)
    feed = await rss.fetch_feed(rss_url)
    if feed.bozo and not feed.entries:
        raise HTTPException(status_code=422, detail="無效的 RSS 網址，請確認後再試。")
    title = getattr(feed.feed, "title", rss_url)
    sub_id = await db.add_subscription(user_id, title, rss_url)
    sub = await db.get_subscription_by_id(sub_id)
    # Mark all current feed entries as seen — no backlog flood
    # sub.podcast_id is already resolved by add_subscription; no extra DB call needed
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if guid:
            await db.mark_episode_seen(user_id, sub.podcast_id, guid, title=entry.get("title"), published_at=parse_published(entry))
    return sub.model_dump()


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(sub_id: str, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.remove_subscription_by_id(sub_id)


@router.post("/subscriptions/{sub_id}/refresh")
async def refresh_subscription(sub_id: str, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    feed = await rss.fetch_feed(sub.rss_url)
    new_count = 0
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue
        if not await db.is_episode_seen(user_id, sub.podcast_id, guid):
            new_count += 1
        description = entry.get("summary") or entry.get("description") or ""
        await db.mark_episode_seen(
            user_id,
            sub.podcast_id,
            guid,
            title=entry.get("title"),
            published_at=parse_published(entry),
            description=description or None,
        )
    return {"new_count": new_count}


@router.put("/subscriptions/{sub_id}/prompt")
async def update_prompt(sub_id: str, body: PromptRequest, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.set_subscription_prompt(sub_id, body.prompt)
    return {"ok": True}


@router.put("/subscriptions/{sub_id}/chat-prompt")
async def update_chat_prompt(sub_id: str, body: ChatPromptRequest, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.set_subscription_chat_prompt(sub_id, body.prompt)
    return {"ok": True}


# Two endpoints mirror the existing /prompt vs /chat-prompt split,
# allowing future divergence (e.g. chat-specific meta-prompt).
# Note: AI generation may take 5–30 s; no timeout guard — acceptable for now.
@router.post("/subscriptions/{sub_id}/generate-prompt")
async def generate_prompt(sub_id: str, body: GeneratePromptRequest, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    stripped_desc = body.description.strip()
    desc = f"{sub.podcast_title}. {stripped_desc}" if stripped_desc else sub.podcast_title
    prompt = await generate_prompt_from_description(desc)
    return {"prompt": prompt}


@router.post("/subscriptions/{sub_id}/generate-chat-prompt")
async def generate_chat_prompt(sub_id: str, body: GeneratePromptRequest, user_id: str = Depends(get_current_user)):
    sub = await db.get_subscription_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    stripped_desc = body.description.strip()
    desc = f"{sub.podcast_title}. {stripped_desc}" if stripped_desc else sub.podcast_title
    prompt = await generate_prompt_from_description(desc)
    return {"prompt": prompt}
