import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_BYTES = 500_000
MAX_TRANSCRIPT_CHARS = 12_000

_VTT_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> .+$", re.MULTILINE)
_SRT_TIMECODE = re.compile(r"^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3} --> .+\n", re.MULTILINE)
_AUDIO_MIME = re.compile(r"^audio/")

MAX_AUDIO_BYTES = 200_000_000  # 200 MB hard cap


@dataclass
class Episode:
    guid: str
    title: str
    published: str | None
    content: str  # transcript text or description


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


async def _download_audio(url: str) -> str | None:
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".audio", delete=False)
        total = 0
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        logger.warning("Audio file too large, aborting: %s", url)
                        tmp.close()
                        os.unlink(tmp.name)
                        return None
                    tmp.write(chunk)
        tmp.close()
        return tmp.name
    except Exception as exc:
        logger.warning("Failed to download audio %s: %s", url, exc)
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return None


def _run_transcription(path: str, model_size: str) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path, beam_size=5, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments)


async def _transcribe_audio(path: str, model_size: str) -> str | None:
    try:
        return await asyncio.to_thread(_run_transcription, path, model_size)
    except Exception as exc:
        logger.warning("Transcription failed for %s: %s", path, exc)
        return None


async def get_episode_content(
    entry: dict,
    whisper_model: str = "base",
    podcast_title: str = "",
    gemini_model: str = "gemini-2.0-flash",
) -> str:
    from bot.summarizer import correct_transcript

    url = _resolve_transcript_url(entry)
    if url:
        text = await _fetch_transcript_url(url)
        if text:
            content = text[:MAX_TRANSCRIPT_CHARS]
            return await correct_transcript(
                content,
                podcast_title,
                entry.get("title", ""),
                entry.get("summary") or entry.get("description", ""),
                gemini_model,
            )

    audio_url = _extract_audio_url(entry)
    if audio_url:
        path = await _download_audio(audio_url)
        if path:
            try:
                text = await _transcribe_audio(path, whisper_model)
                if text:
                    content = text[:MAX_TRANSCRIPT_CHARS]
                    return await correct_transcript(
                        content,
                        podcast_title,
                        entry.get("title", ""),
                        entry.get("summary") or entry.get("description", ""),
                        gemini_model,
                    )
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    text = entry.get("summary") or entry.get("description") or ""
    content = text[:MAX_TRANSCRIPT_CHARS]
    return await correct_transcript(
        content,
        podcast_title,
        entry.get("title", ""),
        entry.get("summary") or entry.get("description", ""),
        gemini_model,
    )


async def fetch_feed(url: str) -> feedparser.FeedParserDict:
    return await asyncio.to_thread(feedparser.parse, url)


async def fetch_feed_entries(rss_url: str, limit: int = 5) -> list[dict]:
    """Return raw feed entries (no content fetch) for display purposes."""
    feed = await asyncio.to_thread(feedparser.parse, rss_url)
    return list(feed.entries[:limit])


def parse_podcast_title(parsed: feedparser.FeedParserDict) -> str:
    return parsed.feed.get("title", "Unknown Podcast")


async def _parse_entry(
    entry: dict,
    whisper_model: str = "base",
    podcast_title: str = "",
    gemini_model: str = "gemini-2.0-flash",
) -> Episode:
    guid = entry.get("id") or entry.get("link") or entry.get("title", "")
    content = await get_episode_content(
        entry, whisper_model, podcast_title, gemini_model
    )
    return Episode(
        guid=guid,
        title=entry.get("title", "Untitled"),
        published=entry.get("published"),
        content=content,
    )


async def fetch_feed_episodes(
    rss_url: str, limit: int = 5, whisper_model: str = "base"
) -> list[Episode]:
    """Return up to `limit` most-recent episodes from the feed."""
    feed = await asyncio.to_thread(feedparser.parse, rss_url)
    return [await _parse_entry(e, whisper_model) for e in feed.entries[:limit]]


async def fetch_new_episodes(
    subscription_id: str,
    rss_url: str,
    is_seen_fn,
    whisper_model: str = "base",
    podcast_title: str = "",
    gemini_model: str = "gemini-2.0-flash",
) -> list[Episode]:
    parsed = await fetch_feed(rss_url)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Failed to parse feed: {rss_url}")

    new_episodes: list[Episode] = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue
        if await is_seen_fn(subscription_id, guid):
            continue

        ep = await _parse_entry(entry, whisper_model, podcast_title, gemini_model)
        new_episodes.append(ep)

    return new_episodes
