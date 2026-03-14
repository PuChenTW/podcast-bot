"""Unit tests for AudioPipeline."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.transcribers.audio_pipeline import AudioPipeline


class MockChunkTranscriber:
    accepted_formats = ("mp3", "wav")
    max_bytes = 10_000_000

    def __init__(self, return_value="hello"):
        self.transcribe_chunk = AsyncMock(return_value=return_value)
        self.calls = []


def _ffprobe_format_result(fmt: str, returncode: int = 0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = fmt
    r.stderr = ""
    return r


@pytest.fixture
def transcriber():
    return MockChunkTranscriber()


@pytest.fixture
def pipeline(transcriber):
    return AudioPipeline(transcriber)


@pytest.mark.asyncio
async def test_no_conversion_no_split(pipeline, transcriber, tmp_path):
    """Format accepted, file small → transcribe_chunk called once with original path."""
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 100)

    with patch("bot.transcribers.audio_pipeline.subprocess.run") as mock_run:
        mock_run.return_value = _ffprobe_format_result("mp3")

        result = await pipeline.transcribe(str(audio))

    transcriber.transcribe_chunk.assert_awaited_once_with(str(audio))
    assert result == "hello"


@pytest.mark.asyncio
async def test_format_conversion(pipeline, transcriber, tmp_path):
    """Format not accepted → ffmpeg conversion called; converted path passed to chunk transcriber."""
    audio = tmp_path / "episode.ogg"
    audio.write_bytes(b"x" * 100)

    converted = tmp_path / "converted.mp3"
    converted.write_bytes(b"x" * 100)

    ffprobe_result = _ffprobe_format_result("ogg")
    ffmpeg_result = MagicMock(returncode=0)

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if "ffprobe" in cmd[0]:
            return ffprobe_result
        # ffmpeg conversion — create the output file
        if len(cmd) > 1 and cmd[1] == "-y":
            out = cmd[-1]
            open(out, "wb").write(b"x" * 100)
        return ffmpeg_result

    with patch("bot.transcribers.audio_pipeline.subprocess.run", side_effect=side_effect):
        result = await pipeline.transcribe(str(audio))

    assert result == "hello"
    # transcribe_chunk should NOT have been called with original ogg path
    called_path = transcriber.transcribe_chunk.call_args[0][0]
    assert called_path != str(audio)
    assert called_path.endswith(".mp3")


@pytest.mark.asyncio
async def test_format_conversion_cleanup(tmp_path):
    """Temp converted file is deleted after transcription."""
    transcriber = MockChunkTranscriber()
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.ogg"
    audio.write_bytes(b"x" * 100)

    created_tmp = []

    def side_effect(cmd, **kwargs):
        if "ffprobe" in cmd[0]:
            return _ffprobe_format_result("ogg")
        out = cmd[-1]
        open(out, "wb").write(b"x" * 100)
        created_tmp.append(out)
        return MagicMock(returncode=0)

    with patch("bot.transcribers.audio_pipeline.subprocess.run", side_effect=side_effect):
        await pipeline.transcribe(str(audio))

    for p in created_tmp:
        assert not os.path.exists(p), f"Temp file not cleaned up: {p}"


@pytest.mark.asyncio
async def test_oversized_file_split(tmp_path):
    """File > max_bytes → split called, N chunks dispatched via gather, results joined."""
    transcriber = MockChunkTranscriber(return_value="part")
    transcriber.max_bytes = 50
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 200)  # > max_bytes=50

    chunk1 = tmp_path / "chunk1.mp3"
    chunk2 = tmp_path / "chunk2.mp3"
    chunk1.write_bytes(b"x" * 40)
    chunk2.write_bytes(b"x" * 40)

    def ffprobe_format(cmd, **kwargs):
        return _ffprobe_format_result("mp3")

    with patch("bot.transcribers.audio_pipeline.subprocess.run", side_effect=ffprobe_format):
        with patch("bot.transcribers.audio_pipeline._split_audio", return_value=[str(chunk1), str(chunk2)]) as mock_split:
            result = await pipeline.transcribe(str(audio))

    mock_split.assert_called_once()
    assert transcriber.transcribe_chunk.await_count == 2
    assert result == "part part"


@pytest.mark.asyncio
async def test_chunk_raises_returns_none(tmp_path):
    """If transcribe_chunk raises, AudioPipeline.transcribe returns None."""
    transcriber = MockChunkTranscriber()
    transcriber.transcribe_chunk = AsyncMock(side_effect=RuntimeError("API down"))
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 100)

    with patch("bot.transcribers.audio_pipeline.subprocess.run", return_value=_ffprobe_format_result("mp3")):
        result = await pipeline.transcribe(str(audio))

    assert result is None


@pytest.mark.asyncio
async def test_ffprobe_fails_proceeds_with_original(tmp_path):
    """ffprobe failure → no conversion attempted, transcription proceeds on original."""
    transcriber = MockChunkTranscriber()
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 100)

    with patch("bot.transcribers.audio_pipeline.subprocess.run", return_value=_ffprobe_format_result("", returncode=1)):
        result = await pipeline.transcribe(str(audio))

    transcriber.transcribe_chunk.assert_awaited_once_with(str(audio))
    assert result == "hello"


@pytest.mark.asyncio
async def test_ffmpeg_conversion_fails_uses_original(tmp_path):
    """If ffmpeg conversion fails, original file is used for transcription."""
    transcriber = MockChunkTranscriber()
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.ogg"
    audio.write_bytes(b"x" * 100)

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if "ffprobe" in cmd[0]:
            return _ffprobe_format_result("ogg")
        # ffmpeg conversion fails
        r = MagicMock()
        r.returncode = 1
        r.stderr = b"conversion error"
        return r

    with patch("bot.transcribers.audio_pipeline.subprocess.run", side_effect=side_effect):
        result = await pipeline.transcribe(str(audio))

    transcriber.transcribe_chunk.assert_awaited_once_with(str(audio))
    assert result == "hello"


@pytest.mark.asyncio
async def test_cleanup_runs_on_exception(tmp_path):
    """Temp files are cleaned up even when transcribe_chunk raises."""
    transcriber = MockChunkTranscriber()
    transcriber.transcribe_chunk = AsyncMock(side_effect=RuntimeError("fail"))
    pipeline = AudioPipeline(transcriber)

    audio = tmp_path / "episode.ogg"
    audio.write_bytes(b"x" * 100)

    created_tmp = []

    def side_effect(cmd, **kwargs):
        if "ffprobe" in cmd[0]:
            return _ffprobe_format_result("ogg")
        out = cmd[-1]
        open(out, "wb").write(b"x" * 100)
        created_tmp.append(out)
        return MagicMock(returncode=0)

    with patch("bot.transcribers.audio_pipeline.subprocess.run", side_effect=side_effect):
        result = await pipeline.transcribe(str(audio))

    assert result is None
    for p in created_tmp:
        assert not os.path.exists(p), f"Temp file not cleaned up: {p}"


@pytest.mark.asyncio
async def test_whisper_max_bytes_never_triggers_split(tmp_path):
    """WhisperTranscriber.max_bytes=2GB means realistic files never get split."""
    from bot.transcribers.whisper import WHISPER_MAX_BYTES

    assert WHISPER_MAX_BYTES == 2_000_000_000
    # A 200MB file (the hard cap from feed.py) is well below WHISPER_MAX_BYTES
    assert 200 * 1024 * 1024 < WHISPER_MAX_BYTES
