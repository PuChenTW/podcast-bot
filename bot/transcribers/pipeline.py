import logging

from bot.transcribers.base import Transcriber

logger = logging.getLogger(__name__)


class TranscriberPipeline:
    """Fallback pipeline: tries each transcriber in order, returns first success."""

    def __init__(self, transcribers: list[Transcriber], strategy: str = "fallback") -> None:
        self._transcribers = transcribers
        self._strategy = strategy

    async def transcribe(self, audio_path: str) -> str | None:
        for transcriber in self._transcribers:
            try:
                result = await transcriber.transcribe(audio_path)
                if result is not None:
                    return result
                logger.warning("%s returned None, trying next", type(transcriber).__name__)
            except Exception as exc:
                logger.warning("%s failed: %s, trying next", type(transcriber).__name__, exc)
        return None
