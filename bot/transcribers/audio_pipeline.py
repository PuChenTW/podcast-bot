import asyncio
import logging
import math
import os
import subprocess
import tempfile

from bot.transcribers.base import ChunkTranscriber

logger = logging.getLogger(__name__)

FORMAT_TO_EXT = {"mp3": ".mp3", "ogg": ".ogg", "flac": ".flac", "wav": ".wav", "aac": ".aac", "m4a": ".m4a"}


def _split_audio(path: str, max_bytes: int) -> list[str]:
    """Split audio file into chunks each under max_bytes. Returns list of temp file paths."""
    try:
        file_size = os.path.getsize(path)
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed: %s", result.stderr)
            return [path]
        total_duration = float(result.stdout.strip())
        n_chunks = math.ceil(file_size / max_bytes)
        chunk_duration = total_duration / n_chunks
        fmt_result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True,
            text=True,
            timeout=30,
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
                    "ffmpeg",
                    "-y",
                    "-i",
                    path,
                    "-ss",
                    str(offset),
                    "-t",
                    str(chunk_duration),
                    "-c",
                    "copy",
                    tmp.name,
                ],
                capture_output=True,
                timeout=120,
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


class AudioPipeline:
    """Handles format conversion and audio splitting before dispatching to a ChunkTranscriber."""

    def __init__(self, transcriber: ChunkTranscriber) -> None:
        self._transcriber = transcriber

    async def transcribe(self, audio_path: str) -> str | None:
        temp_files: list[str] = []
        try:
            working_path = audio_path

            # Detect format
            fmt_result = await asyncio.to_thread(
                subprocess.run,
                ["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if fmt_result.returncode == 0:
                fmt = fmt_result.stdout.strip().split(",")[0]
            else:
                logger.warning("ffprobe format detection failed: %s", fmt_result.stderr)
                fmt = ""

            # Convert if format not accepted
            if fmt and fmt not in self._transcriber.accepted_formats:
                target_ext = FORMAT_TO_EXT.get(self._transcriber.accepted_formats[0], ".mp3")
                tmp = tempfile.NamedTemporaryFile(suffix=target_ext, delete=False)
                tmp.close()
                temp_files.append(tmp.name)
                conv_result = await asyncio.to_thread(
                    subprocess.run,
                    ["ffmpeg", "-y", "-i", audio_path, tmp.name],
                    capture_output=True,
                    timeout=300,
                )
                if conv_result.returncode == 0:
                    working_path = tmp.name
                else:
                    logger.warning("ffmpeg conversion failed, using original: %s", conv_result.stderr)

            # Split if oversized
            if os.path.getsize(working_path) > self._transcriber.max_bytes:
                chunk_paths = await asyncio.to_thread(_split_audio, working_path, self._transcriber.max_bytes)
                # Only track chunks as temp if they differ from working_path
                temp_files.extend(p for p in chunk_paths if p != working_path and p != audio_path)
            else:
                chunk_paths = [working_path]

            parts = await asyncio.gather(*[self._transcriber.transcribe_chunk(p) for p in chunk_paths])
            return " ".join(parts) if parts else None
        except Exception as exc:
            logger.warning("AudioPipeline transcription failed for %s: %s", audio_path, exc)
            return None
        finally:
            for p in temp_files:
                try:
                    os.unlink(p)
                except OSError:
                    pass
