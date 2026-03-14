import asyncio
import logging

logger = logging.getLogger(__name__)


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
