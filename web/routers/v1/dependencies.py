from typing import Annotated

from fastapi import Depends, HTTPException

from core import database as db
from web.auth import get_current_user

CurrentUser = Annotated[str, Depends(get_current_user)]


async def require_podcast(podcast_id: str, user_id: CurrentUser) -> dict:
    podcast = await db.get_podcast_for_user(user_id, podcast_id)
    if podcast is None:
        raise HTTPException(status_code=404, detail="Podcast not found")
    if podcast["subscription_id"] is None:
        raise HTTPException(status_code=403, detail="No subscription to this podcast")
    return podcast


async def require_episode(episode_id: str, user_id: CurrentUser) -> dict:
    episode = await db.get_episode_for_user(user_id, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if episode["subscription_id"] is None:
        raise HTTPException(status_code=403, detail="No subscription to this podcast")
    return episode


async def require_subscription(subscription_id: str, user_id: CurrentUser):
    subscription = await db.get_subscription_by_id(subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if subscription.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return subscription
