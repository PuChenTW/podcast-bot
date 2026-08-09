import asyncio
import calendar
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Awaitable, Callable

import feedparser
import httpx

from core.audio_workspace import audio_workspace
from core.transcribers import Transcriber

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_BYTES = 500_000
MAX_TRANSCRIPT_CHARS = 100_000

_VTT_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> .+$", re.MULTILINE)
_SRT_TIMECODE = re.compile(r"^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3} --> .+\n", re.MULTILINE)
_AUDIO_MIME = re.compile(r"^audio/")
_APPLE_PODCAST_RE = re.compile(r"podcasts\.apple\.com/.+/id(\d+)")

MAX_AUDIO_BYTES = 500_000_000  # 500 MB hard cap

# Type alias for the transcript corrector callable.
Corrector = Callable[[str, str, str, str], Awaitable[str]]


def parse_published(entry: dict) -> str | None:
    """Return ISO 8601 UTC date string from a feedparser entry, or None."""
    parsed = entry.get("published_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = entry.get("published")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


@dataclass
class Episode:
    guid: str
    title: str
    published: str | None
    content: str  # transcript text or description (used for summarization)
    description: str  # raw RSS description/show notes
    transcript: str | None  # real transcript only; None if no transcript was found
    transcript_source: str | None


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    source: str


def _strip_timing_markers(text: str) -> str:
    text = _VTT_LINE.sub("", text)
    text = _SRT_TIMECODE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _fetch_transcript_url(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    total += len(chunk)
                    if total > MAX_TRANSCRIPT_BYTES:
                        break
                    chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        if "vtt" in content_type or "vtt" in url.lower():
            return _strip_timing_markers(raw)
        if "srt" in url.lower():
            return _strip_timing_markers(raw)
        return raw
    except Exception as exc:
        logger.warning("Failed to fetch transcript %s: %s", url, exc)
        return None


def _resolve_transcript_url(entry: dict) -> str | None:
    # 1. Podcasting 2.0 tag
    transcript = entry.get("podcast_transcript")
    if isinstance(transcript, dict):
        url = transcript.get("url")
        if url:
            return url
    # Handle list form
    if isinstance(transcript, list) and transcript:
        url = transcript[0].get("url")
        if url:
            return url

    # 2. Apple Podcasts convention — links with rel="transcript"
    for link in entry.get("links", []):
        if link.get("rel") == "transcript" and link.get("href"):
            return link["href"]

    return None


def _extract_audio_url(entry: dict) -> str | None:
    for enc in entry.get("enclosures", []):
        href = enc.get("href") or enc.get("url")
        mime = enc.get("type", "")
        if href and _AUDIO_MIME.match(mime):
            return href
    return None


async def _download_audio(url: str, workspace: Path) -> str | None:
    path = workspace / "source.audio"
    try:
        total = 0
        with path.open("wb") as audio_file:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES:
                            logger.warning("Audio file too large, aborting: %s", url)
                            return None
                        audio_file.write(chunk)
        return str(path)
    except Exception as exc:
        logger.warning("Failed to download audio %s: %s\n", url, exc)
        return None


async def get_transcript_result(
    entry: dict,
    transcriber: Transcriber,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> TranscriptResult | None:
    """Return corrected transcript text and its source, or None if unavailable."""

    async def _correct(text: str) -> str:
        if corrector is None:
            return text
        ep_title = entry.get("title", "")
        description = entry.get("summary") or entry.get("description", "")
        return await corrector(text, podcast_title, ep_title, description)

    url = _resolve_transcript_url(entry)
    if url:
        text = await _fetch_transcript_url(url)
        if text:
            return TranscriptResult(await _correct(text[:MAX_TRANSCRIPT_CHARS]), "feed")

    audio_url = _extract_audio_url(entry)
    if audio_url:
        with audio_workspace() as workspace:
            path = await _download_audio(audio_url, workspace)
            if path:
                text = await transcriber.transcribe(path)
                if text:
                    return TranscriptResult(await _correct(text[:MAX_TRANSCRIPT_CHARS]), "asr")

    return None


async def get_transcript(
    entry: dict,
    transcriber: Transcriber,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> str | None:
    result = await get_transcript_result(entry, transcriber, podcast_title, corrector)
    return result.text if result else None


async def resolve_rss_url(url: str) -> str:
    """Resolve Apple Podcasts URLs to RSS via iTunes Lookup API.
    Returns input unchanged for non-Apple URLs.
    Raises ValueError with a user-facing message on failure.
    """
    m = _APPLE_PODCAST_RE.search(url)
    if m is None:
        return url

    podcast_id = m.group(1)
    lookup_url = f"https://itunes.apple.com/lookup?id={podcast_id}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(lookup_url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise ValueError("Apple Podcasts lookup timed out. Try again or paste the RSS URL directly.")
    except Exception as exc:
        logger.warning("iTunes lookup failed for id=%s: %s", podcast_id, exc)
        raise ValueError("Apple Podcasts lookup failed. Try again or paste the RSS URL directly.")

    results = data.get("results", [])
    if not results:
        raise ValueError("Couldn't find a podcast with that Apple ID. It may be private or removed.")

    feed_url = results[0].get("feedUrl")
    if not feed_url:
        raise ValueError("This podcast doesn't have a public RSS feed on Apple Podcasts.")

    return feed_url


async def fetch_feed(url: str) -> feedparser.FeedParserDict:
    return await asyncio.to_thread(feedparser.parse, url)


async def fetch_feed_entries(rss_url: str, limit: int = 5) -> list[dict]:
    """Return raw feed entries (no content fetch) for display purposes."""
    feed = await asyncio.to_thread(feedparser.parse, rss_url)
    return list(feed.entries[:limit])


def parse_podcast_title(parsed: feedparser.FeedParserDict) -> str:
    return parsed.feed.get("title", "Unknown Podcast")


async def _build_episode(
    entry: dict,
    transcriber: Transcriber,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> Episode:
    guid = entry.get("id") or entry.get("link") or entry.get("title", "")
    transcript_result = await get_transcript_result(entry, transcriber, podcast_title, corrector)
    transcript = transcript_result.text if transcript_result else None
    description = entry.get("summary") or entry.get("description") or ""
    content = transcript or description
    return Episode(
        guid=guid,
        title=entry.get("title", "Untitled"),
        published=parse_published(entry),
        content=content,
        description=description,
        transcript=transcript,
        transcript_source=transcript_result.source if transcript_result else None,
    )


async def fetch_feed_episodes(
    rss_url: str,
    limit: int = 5,
    transcriber: Transcriber = None,
    corrector: Corrector | None = None,
) -> list[Episode]:
    """Return up to `limit` most-recent episodes from the feed."""
    feed = await asyncio.to_thread(feedparser.parse, rss_url)
    podcast_title = parse_podcast_title(feed)
    return [await _build_episode(e, transcriber, podcast_title, corrector) for e in feed.entries[:limit]]


async def fetch_new_episodes(
    user_id: str,
    podcast_id: str,
    rss_url: str,
    is_seen_fn,
    transcriber: Transcriber = None,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> list[Episode]:
    parsed = await fetch_feed(rss_url)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Failed to parse feed: {rss_url}")

    new_episodes: list[Episode] = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue
        if await is_seen_fn(user_id, podcast_id, guid):
            continue

        ep = await _build_episode(entry, transcriber, podcast_title, corrector)
        new_episodes.append(ep)

    return new_episodes
