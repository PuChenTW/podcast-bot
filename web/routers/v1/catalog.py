import httpx
from fastapi import APIRouter, HTTPException, Query

from web.routers.v1.dependencies import CurrentUser
from web.routers.v1.schemas import CatalogPodcast

router = APIRouter(prefix="/podcast-catalog", tags=["podcast-catalog"])


@router.get(
    "/search",
    response_model=list[CatalogPodcast],
    operation_id="search_podcast_catalog",
    responses={503: {"description": "Apple catalog unavailable"}},
)
async def search_podcast_catalog(user_id: CurrentUser, q: str = Query(min_length=1)):
    del user_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://itunes.apple.com/search",
                params={"term": q, "media": "podcast", "limit": 10},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail="Podcast catalog is temporarily unavailable") from exc
    return [
        CatalogPodcast(
            name=item.get("collectionName", ""),
            artist=item.get("artistName", ""),
            artwork_url=item.get("artworkUrl100", item.get("artworkUrl60", "")),
            feed_url=item["feedUrl"],
        )
        for item in data.get("results", [])
        if item.get("feedUrl")
    ]
