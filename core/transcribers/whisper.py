import asyncio
import logging

logger = logging.getLogger(__name__)

WHISPER_MAX_BYTES = 2_000_000_000  # effectively unlimited for local processing


class WhisperTranscriber:
    accepted_formats = ("mp3", "wav", "flac", "ogg", "m4a", "aac")
    max_bytes = WHISPER_MAX_BYTES

    def __init__(self, model_size: str) -> None:
        self._model_size = model_size

    async def transcribe_chunk(self, path: str) -> str:
        return await asyncio.to_thread(self._run, path)

    def _run(self, path: str) -> str:
        from faster_whisper import WhisperModel

        model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path, beam_size=5, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments)
