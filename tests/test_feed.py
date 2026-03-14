from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.feed import (
    MAX_TRANSCRIPT_CHARS,
    _extract_audio_url,
    _resolve_transcript_url,
    _strip_timing_markers,
    fetch_feed_entries,
    fetch_new_episodes,
    get_episode_content,
    parse_podcast_title,
)
from tests.conftest import async_gen


class TestStripTimingMarkers:
    def test_removes_vtt_timecodes(self):
        text = "00:00:01.000 --> 00:00:02.000\nHello world"
        result = _strip_timing_markers(text)
        assert "00:00:01.000 --> 00:00:02.000" not in result
        assert "Hello world" in result

    def test_removes_srt_index_and_timecode(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\nHello"
        result = _strip_timing_markers(text)
        assert "00:00:01,000 --> 00:00:02,000" not in result
        assert "Hello" in result

    def test_plain_text_unchanged(self):
        text = "Just some plain text here."
        assert _strip_timing_markers(text) == text

    def test_collapses_excess_blank_lines(self):
        text = "line1\n\n\n\nline2"
        result = _strip_timing_markers(text)
        assert "\n\n\n" not in result


class TestResolveTranscriptUrl:
    def test_podcast_transcript_as_dict(self):
        entry = {"podcast_transcript": {"url": "http://example.com/t.vtt"}}
        assert _resolve_transcript_url(entry) == "http://example.com/t.vtt"

    def test_podcast_transcript_as_list(self):
        entry = {"podcast_transcript": [{"url": "http://example.com/t.vtt"}]}
        assert _resolve_transcript_url(entry) == "http://example.com/t.vtt"

    def test_links_with_rel_transcript(self):
        entry = {"links": [{"rel": "transcript", "href": "http://example.com/t.srt"}]}
        assert _resolve_transcript_url(entry) == "http://example.com/t.srt"

    def test_non_transcript_link_returns_none(self):
        entry = {"links": [{"rel": "alternate", "href": "http://example.com"}]}
        assert _resolve_transcript_url(entry) is None

    def test_empty_entry_returns_none(self):
        assert _resolve_transcript_url({}) is None


class TestExtractAudioUrl:
    def test_audio_enclosure_with_href(self):
        entry = {"enclosures": [{"href": "http://example.com/ep.mp3", "type": "audio/mpeg"}]}
        assert _extract_audio_url(entry) == "http://example.com/ep.mp3"

    def test_audio_enclosure_with_url(self):
        entry = {"enclosures": [{"url": "http://example.com/ep.mp3", "type": "audio/mpeg"}]}
        assert _extract_audio_url(entry) == "http://example.com/ep.mp3"

    def test_non_audio_mime_skipped(self):
        entry = {"enclosures": [{"href": "http://example.com/img.jpg", "type": "image/jpeg"}]}
        assert _extract_audio_url(entry) is None

    def test_empty_enclosures_returns_none(self):
        assert _extract_audio_url({"enclosures": []}) is None


class TestParsePodcastTitle:
    def test_returns_title(self):
        parsed = MagicMock()
        parsed.feed = {"title": "My Show"}
        assert parse_podcast_title(parsed) == "My Show"

    def test_missing_title_returns_default(self):
        parsed = MagicMock()
        parsed.feed = {}
        assert parse_podcast_title(parsed) == "Unknown Podcast"


def _make_stream_mock(content: bytes):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.headers = {"content-type": "text/plain"}
    resp.aiter_bytes = MagicMock(return_value=async_gen(content))
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=resp)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock()
    client.stream = MagicMock(return_value=stream_ctx)
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx


class TestFetchTranscriptUrl:
    async def test_returns_text_content(self):
        from bot.feed import _fetch_transcript_url

        mock_client = _make_stream_mock(b"transcript content")
        with patch("bot.feed.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_transcript_url("http://example.com/t.txt")
        assert result == "transcript content"

    async def test_strips_vtt_markers(self):
        from bot.feed import _fetch_transcript_url

        vtt_content = b"00:00:01.000 --> 00:00:02.000\nHello world"
        mock_client = _make_stream_mock(vtt_content)
        with patch("bot.feed.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_transcript_url("http://example.com/t.vtt")
        assert "00:00:01.000 --> 00:00:02.000" not in result
        assert "Hello world" in result

    async def test_returns_none_on_http_error(self):
        from bot.feed import _fetch_transcript_url

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("bot.feed.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_transcript_url("http://example.com/t.txt")
        assert result is None


class TestGetEpisodeContent:
    async def test_path1_transcript_url(self):
        entry = {
            "podcast_transcript": {"url": "http://example.com/t.txt"},
            "title": "Ep 1",
            "summary": "desc",
        }
        corrector = AsyncMock(return_value="corrected")
        transcriber = AsyncMock()
        transcriber.transcribe = AsyncMock(return_value=None)
        with patch("bot.feed._fetch_transcript_url", AsyncMock(return_value="raw transcript")):
            result = await get_episode_content(entry, transcriber, corrector=corrector)
        assert result == "corrected"
        corrector.assert_called_once_with("raw transcript", "", "Ep 1", "desc")

    async def test_path2_audio_transcription(self):
        entry = {
            "enclosures": [{"href": "http://example.com/ep.mp3", "type": "audio/mpeg"}],
            "title": "Ep 2",
            "summary": "desc",
        }
        corrector = AsyncMock(return_value="corrected audio")
        transcriber = AsyncMock()
        transcriber.transcribe = AsyncMock(return_value="transcribed")
        with (
            patch("bot.feed._fetch_transcript_url", AsyncMock(return_value=None)),
            patch("bot.feed._download_audio", AsyncMock(return_value="/tmp/audio.mp3")),
            patch("bot.feed.os.unlink"),
        ):
            result = await get_episode_content(entry, transcriber, corrector=corrector)
        assert result == "corrected audio"
        corrector.assert_called_once_with("transcribed", "", "Ep 2", "desc")

    async def test_path3_description_fallback(self):
        entry = {"title": "Ep 3", "summary": "fallback description"}
        corrector = AsyncMock(return_value="corrected fallback")
        transcriber = AsyncMock()
        transcriber.transcribe = AsyncMock(return_value=None)
        with (
            patch("bot.feed._fetch_transcript_url", AsyncMock(return_value=None)),
            patch("bot.feed._download_audio", AsyncMock(return_value=None)),
        ):
            result = await get_episode_content(entry, transcriber, corrector=corrector)
        assert result == "corrected fallback"
        corrector.assert_called_once_with("fallback description", "", "Ep 3", "fallback description")

    async def test_content_truncated(self):
        long_text = "x" * (MAX_TRANSCRIPT_CHARS + 100)
        entry = {
            "podcast_transcript": {"url": "http://example.com/t.txt"},
            "title": "Ep",
            "summary": "",
        }
        transcriber = AsyncMock()
        transcriber.transcribe = AsyncMock(return_value=None)
        with patch("bot.feed._fetch_transcript_url", AsyncMock(return_value=long_text)):
            result = await get_episode_content(entry, transcriber)
        assert len(result) <= MAX_TRANSCRIPT_CHARS


class TestFetchFeedEntries:
    async def test_limit_applied(self):
        mock_feed = MagicMock()
        mock_feed.entries = [{"title": f"Ep {i}"} for i in range(10)]
        with patch("bot.feed.feedparser.parse", return_value=mock_feed):
            result = await fetch_feed_entries("http://example.com/feed.rss", limit=3)
        assert len(result) == 3


class TestFetchNewEpisodes:
    async def test_seen_episodes_filtered(self):
        entry1 = {"id": "guid1", "title": "Ep 1", "summary": ""}
        entry2 = {"id": "guid2", "title": "Ep 2", "summary": ""}
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [entry1, entry2]

        async def is_seen(user_id, podcast_id, guid):
            return guid == "guid1"

        with (
            patch("bot.feed.feedparser.parse", return_value=mock_feed),
            patch("bot.feed.get_episode_content", AsyncMock(return_value="content")),
        ):
            result = await fetch_new_episodes("user1", "pod1", "http://example.com/feed.rss", is_seen)
        assert len(result) == 1
        assert result[0].guid == "guid2"

    async def test_bozo_empty_raises(self):
        mock_feed = MagicMock()
        mock_feed.bozo = True
        mock_feed.entries = []
        with patch("bot.feed.feedparser.parse", return_value=mock_feed):
            with pytest.raises(ValueError):
                await fetch_new_episodes("user1", "pod1", "http://bad.url/feed.rss", AsyncMock())
