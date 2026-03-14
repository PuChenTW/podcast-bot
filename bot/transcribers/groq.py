import asyncio
import logging
import math
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

MAX_GROQ_BYTES = 20_000_000  # Groq limit is 25MB but multipart overhead requires headroom
FORMAT_TO_EXT = {"mp3": ".mp3", "ogg": ".ogg", "flac": ".flac", "wav": ".wav", "aac": ".aac", "m4a": ".m4a"}


def _split_audio(path: str, max_bytes: int) -> list[str]:
    """Split audio file into chunks each under max_bytes. Returns list of temp file paths."""
    try:
        file_size = os.path.getsize(path)
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
        fmt_result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        fmt = fmt_result.stdout.strip().split(",")[0] if fmt_result.returncode == 0 else ""
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
