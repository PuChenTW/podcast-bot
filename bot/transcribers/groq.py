import logging

logger = logging.getLogger(__name__)

MAX_GROQ_BYTES = 20_000_000  # Groq limit is 25MB but multipart overhead requires headroom


class GroqTranscriber:
    accepted_formats = ("mp3", "m4a", "ogg", "wav", "flac", "aac")
    max_bytes = MAX_GROQ_BYTES

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    async def transcribe_chunk(self, path: str) -> str:
        client = self._get_client()
        with open(path, "rb") as f:
            result = await client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
            )
        return result.text
