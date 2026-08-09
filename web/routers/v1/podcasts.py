from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from core import database as db
from core import feed as rss
from core.feed import parse_published
from web.routers.v1.dependencies import CurrentUser, require_podcast, require_subscription
from web.routers.v1.pagination import decode_cursor, encode_cursor
from web.routers.v1.schemas import DeliverySettings, Podcast, PodcastList, SubscriptionCreate, SyncResult

router = APIRouter(tags=["podcasts"])


def _podcast(row: dict) -> Podcast:
    return Podcast(
        id=row["id"] if "id" in row else row["podcast_id"],
        title=row.get("title") or row.get("podcast_title"),
        rss_url=row["rss_url"],
        subscription_id=row.get("subscription_id") or row["id"],
        telegram_delivery=row["telegram_delivery"],
    )


@router.get("/podcasts", response_model=PodcastList, operation_id="list_podcasts")
async def list_podcasts(
    user_id: CurrentUser,
    q: str = "",
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    """List the current user's podcast subscriptions.

    Optionally filters subscriptions by `q`. Results use opaque cursor
    pagination; pass `next_cursor` as `cursor` to retrieve the next page.
    """
    decoded = decode_cursor(cursor)
    after_id = decoded.get("subscription_id") if decoded else None
    if decoded is not None and not isinstance(after_id, str):
        raise HTTPException(status_code=422, detail="Invalid cursor")
    rows = await db.list_podcasts_for_user(user_id, q.strip(), limit + 1, after_id)
    has_next = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor({"subscription_id": items[-1]["subscription_id"]}) if has_next else None
    return PodcastList(items=[_podcast(row) for row in items], next_cursor=next_cursor)


@router.get(
    "/podcasts/{podcast_id}",
    response_model=Podcast,
    operation_id="get_podcast",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Podcast not found"}},
)
async def get_podcast(podcast: dict = Depends(require_podcast)):
    """Return one subscribed podcast.

    The podcast must exist and the current user must have an active
    subscription to it.
    """
    return _podcast(podcast)


@router.post(
    "/subscriptions",
    response_model=Podcast,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_subscription",
    responses={422: {"description": "Invalid RSS URL"}},
)
async def create_subscription(body: SubscriptionCreate, user_id: CurrentUser):
    """Subscribe the current user to a podcast RSS feed.

    Resolves the supplied URL to an RSS feed, stores the podcast and its known
    episodes, and establishes those episodes as the user's no-backlog baseline.
    """
    try:
        rss_url = await rss.resolve_rss_url(body.rss_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    feed = await rss.fetch_feed(rss_url)
    if feed.bozo and not feed.entries:
        raise HTTPException(status_code=422, detail="Invalid RSS URL")
    title = getattr(feed.feed, "title", rss_url)
    subscription_id = await db.add_subscription(user_id, title, rss_url)
    subscription = await db.get_subscription_by_id(subscription_id)
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue
        episode_id = await db.upsert_episode(
            subscription.podcast_id,
            guid,
            title=entry.get("title"),
            published_at=parse_published(entry),
            description=entry.get("summary") or entry.get("description") or None,
        )
        await db.ensure_user_episode(user_id, episode_id)
    return Podcast(
        id=subscription.podcast_id,
        title=subscription.podcast_title,
        rss_url=subscription.rss_url,
        subscription_id=subscription.id,
        telegram_delivery=subscription.telegram_delivery,
    )


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_subscription",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def delete_subscription(subscription=Depends(require_subscription)):
    """Remove the current user's podcast subscription.

    Shared podcast and episode records are retained for other subscribers.
    """
    await db.remove_subscription_by_id(subscription.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/subscriptions/{subscription_id}/delivery",
    response_model=DeliverySettings,
    operation_id="get_subscription_delivery",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def get_subscription_delivery(subscription=Depends(require_subscription)):
    """Return whether new episodes are pushed to Telegram for this subscription.

    Polling, transcription, and summarization run regardless of this setting —
    it controls delivery only.
    """
    return DeliverySettings(telegram_delivery=subscription.telegram_delivery)


@router.patch(
    "/subscriptions/{subscription_id}/delivery",
    response_model=DeliverySettings,
    operation_id="update_subscription_delivery",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def update_subscription_delivery(body: DeliverySettings, subscription=Depends(require_subscription)):
    """Enable or disable Telegram delivery for this subscription.

    Disabling keeps the scheduler downloading, transcribing, and summarizing new
    episodes — they simply stop being pushed to Telegram and remain readable here.
    """
    await db.set_subscription_telegram_delivery(subscription.id, body.telegram_delivery)
    return DeliverySettings(telegram_delivery=body.telegram_delivery)


@router.post(
    "/podcasts/{podcast_id}/sync",
    response_model=SyncResult,
    operation_id="sync_podcast",
    responses={403: {"description": "Subscription required"}, 404: {"description": "Podcast not found"}},
)
async def sync_podcast(user_id: CurrentUser, podcast: dict = Depends(require_podcast)):
    """Refresh a subscribed podcast from its RSS feed.

    Upserts feed metadata and episodes, then returns the number of episodes the
    current user had not previously seen. This does not generate transcripts or
    summaries.
    """
    feed = await rss.fetch_feed(podcast["rss_url"])
    new_count = 0
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue
        if not await db.is_episode_seen(user_id, podcast["id"], guid):
            new_count += 1
        episode_id = await db.upsert_episode(
            podcast["id"],
            guid,
            title=entry.get("title"),
            published_at=parse_published(entry),
            description=entry.get("summary") or entry.get("description") or None,
        )
        await db.ensure_user_episode(user_id, episode_id)
    return SyncResult(new_count=new_count)
