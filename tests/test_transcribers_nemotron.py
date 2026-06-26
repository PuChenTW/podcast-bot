"""Unit tests for NemotronTranscriber (sherpa-onnx wiring, mocked).

The real model is ~700 MB, so these tests mock the recognizer and ffmpeg decode
to verify the transcriber's control flow without downloading anything.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.transcribers.nemotron import SAMPLE_RATE, NemotronTranscriber


def _fake_recognizer(result_text="hello world"):
    rec = MagicMock()
    stream = MagicMock()
    stream.has_option.return_value = True
    rec.create_stream.return_value = stream
    # is_ready returns True once, then False, so the decode loop runs exactly once
    rec.is_ready.side_effect = [True, False]
    rec.get_result.return_value = result_text  # sherpa-onnx returns a plain str
    return rec, stream


@pytest.mark.asyncio
async def test_transcribe_chunk_sets_language_and_returns_text():
    rec, stream = _fake_recognizer("  hello world  ")
    t = NemotronTranscriber("/fake/model", language="ja")

    with (
        patch.object(NemotronTranscriber, "_read_16k_mono", return_value=np.zeros(1600, dtype=np.float32)),
        patch.object(NemotronTranscriber, "_get_recognizer", return_value=rec),
    ):
        out = await t.transcribe_chunk("/fake/audio.mp3")

    assert out == "hello world"  # stripped
    stream.set_option.assert_called_once_with("language", "ja")
    rec.decode_stream.assert_called_once_with(stream)
    # waveform accepted at 16 kHz, plus a trailing-silence flush
    assert stream.accept_waveform.call_count == 2
    assert stream.accept_waveform.call_args_list[0].args[0] == SAMPLE_RATE


@pytest.mark.asyncio
async def test_transcribe_chunk_skips_language_when_unsupported():
    rec, stream = _fake_recognizer("text")
    stream.has_option.return_value = False
    t = NemotronTranscriber("/fake/model")

    with (
        patch.object(NemotronTranscriber, "_read_16k_mono", return_value=np.zeros(1600, dtype=np.float32)),
        patch.object(NemotronTranscriber, "_get_recognizer", return_value=rec),
    ):
        await t.transcribe_chunk("/fake/audio.wav")

    stream.set_option.assert_not_called()


def test_read_16k_mono_raises_on_ffmpeg_failure():
    t = NemotronTranscriber("/fake/model")
    failed = MagicMock(returncode=1, stderr=b"boom")

    with patch("core.transcribers.nemotron.subprocess.run", return_value=failed):
        with pytest.raises(RuntimeError, match="ffmpeg decode failed"):
            t._read_16k_mono("/fake/audio.mp3")


def test_accepted_formats_and_protocol():
    from core.transcribers.base import ChunkTranscriber

    t = NemotronTranscriber("/fake/model")
    assert isinstance(t, ChunkTranscriber)
    assert "wav" in t.accepted_formats
