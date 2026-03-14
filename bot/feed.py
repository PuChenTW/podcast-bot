import asyncio
import logging
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, runtime_checkable

import feedparser
import httpx

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_BYTES = 500_000
MAX_TRANSCRIPT_CHARS = 100_000
CORRECTION_CHUNK_CHARS = 12_000

_VTT_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> .+$", re.MULTILINE)
_SRT_TIMECODE = re.compile(r"^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3} --> .+\n", re.MULTILINE)
_AUDIO_MIME = re.compile(r"^audio/")
_APPLE_PODCAST_RE = re.compile(r"podcasts\.apple\.com/.+/id(\d+)")

MAX_AUDIO_BYTES = 200_000_000  # 200 MB hard cap

# Type alias for the transcript corrector callable.
Corrector = Callable[[str, str, str, str, str], Awaitable[str]]


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, audio_path: str) -> str | None: ...


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
        logger.warning("Failed to download audio %s: %s\n", url, exc)
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return None


def _split_audio(path: str, max_bytes: int) -> list[str]:
    """Split audio file into chunks each under max_bytes. Returns list of temp file paths."""
    try:
        file_size = os.path.getsize(path)
        # Get duration via ffprobe
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed: %s", result.stderr)
            return [path]
        total_duration = float(result.stdout.strip())
        n_chunks = math.ceil(file_size / max_bytes)
        chunk_duration = total_duration / n_chunks
# Detect format from ffprobe so ffmpeg can mux correctly
        fmt_result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        fmt = fmt_result.stdout.strip().split(",")[0] if fmt_result.returncode == 0 else ""
        FORMAT_TO_EXT = {"mp3": ".mp3", "ogg": ".ogg", "flac": ".flac", "wav": ".wav", "aac": ".aac", "m4a": ".m4a"}
        suffix = FORMAT_TO_EXT.get(fmt, ".mp3")
        chunk_paths: list[str] = []
        for i in range(n_chunks):
            offset = i * chunk_duration
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.close()
            r = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", path,
                    "-ss", str(offset), "-t", str(chunk_duration),
                    "-c", "copy", tmp.name,
                ],
                capture_output=True, timeout=120,
            )
            if r.returncode != 0:
                logger.warning("ffmpeg chunk %d failed: %s", i, r.stderr)
                for p in chunk_paths:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                return [path]
            chunk_paths.append(tmp.name)
        return chunk_paths
    except Exception as exc:
        logger.warning("_split_audio failed: %s", exc, exc_info=True)
        return [path]


class WhisperTranscriber:
    def __init__(self, model_size: str) -> None:
        self._model_size = model_size

    async def transcribe(self, audio_path: str) -> str | None:
        try:
            return await asyncio.to_thread(self._run, audio_path)
        except Exception as exc:
            logger.warning("Transcription failed for %s: %s", audio_path, exc)
            return None

    def _run(self, path: str) -> str:
        from faster_whisper import WhisperModel

        model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path, beam_size=5, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments)


MAX_GROQ_BYTES = 20_000_000  # Groq limit is 25MB but multipart overhead requires headroom


class GroqTranscriber:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from groq import AsyncGroq
            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    async def transcribe(self, audio_path: str) -> str | None:
        try:
            size = os.path.getsize(audio_path)
            if size > MAX_GROQ_BYTES:
                chunk_paths = await asyncio.to_thread(_split_audio, audio_path, MAX_GROQ_BYTES)
            else:
                chunk_paths = [audio_path]

            client = self._get_client()

            async def _transcribe_chunk(chunk_path: str) -> str:
                with open(chunk_path, "rb") as f:
                    result = await client.audio.transcriptions.create(
                        model="whisper-large-v3",
                        file=f,
                    )
                return result.text

            try:
                parts = await asyncio.gather(*[_transcribe_chunk(p) for p in chunk_paths])
            finally:
                # Clean up chunks (but not the original file — caller owns that)
                for chunk_path in chunk_paths:
                    if chunk_path != audio_path:
                        try:
                            os.unlink(chunk_path)
                        except OSError:
                            pass

            return " ".join(parts) if parts else None
        except Exception as exc:
            logger.warning("Groq transcription failed for %s: %s", audio_path, exc)
            return None


def _split_chunks(text: str, max_chars: int) -> list[str]:
    """Split text at paragraph boundaries into chunks of at most max_chars."""
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        # Hard-cut oversized single paragraph
        while len(para) > max_chars:
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        sep = "\n\n" if current else ""
        if current_len + len(sep) + len(para) > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(sep) + len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


async def get_episode_content(
    entry: dict,
    transcriber: Transcriber,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> str:
    """Return corrected transcript text (or episode description as fallback)."""
    async def _correct(text: str) -> str:
        if corrector is None:
            return text
        ep_title = entry.get("title", "")
        description = entry.get("summary") or entry.get("description", "")
        chunks = _split_chunks(text, CORRECTION_CHUNK_CHARS)
        if len(chunks) == 1:
            return await corrector(text, podcast_title, ep_title, description)
        results = await asyncio.gather(
            *[corrector(chunk, podcast_title, ep_title, description) for chunk in chunks]
        )
        return "\n\n".join(results)

    url = _resolve_transcript_url(entry)
    if url:
        text = await _fetch_transcript_url(url)
        if text:
            return await _correct(text[:MAX_TRANSCRIPT_CHARS])

    audio_url = _extract_audio_url(entry)
    if audio_url:
        path = await _download_audio(audio_url)
        if path:
            try:
                text = await transcriber.transcribe(path)
                if text:
                    return await _correct(text[:MAX_TRANSCRIPT_CHARS])
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    fallback = entry.get("summary") or entry.get("description") or ""
    return await _correct(fallback[:MAX_TRANSCRIPT_CHARS])


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


async def _parse_entry(
    entry: dict,
    transcriber: Transcriber,
    podcast_title: str = "",
    corrector: Corrector | None = None,
) -> Episode:
    guid = entry.get("id") or entry.get("link") or entry.get("title", "")
    content = await get_episode_content(
        entry, transcriber, podcast_title, corrector
    )
    return Episode(
        guid=guid,
        title=entry.get("title", "Untitled"),
        published=entry.get("published"),
        content=content,
    )


async def fetch_feed_episodes(
    rss_url: str,
    limit: int = 5,
    transcriber: Transcriber = None,
    corrector: Corrector | None = None,
) -> list[Episode]:
    """Return up to `limit` most-recent episodes from the feed."""
    feed = await asyncio.to_thread(feedparser.parse, rss_url)
    return [await _parse_entry(e, transcriber, corrector=corrector) for e in feed.entries[:limit]]


async def fetch_new_episodes(
    subscription_id: str,
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
        if await is_seen_fn(subscription_id, guid):
            continue

        ep = await _parse_entry(entry, transcriber, podcast_title, corrector)
        new_episodes.append(ep)

    return new_episodes
