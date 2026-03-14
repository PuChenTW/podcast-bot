## Groq byte limit

`MAX_GROQ_BYTES = 20_000_000` — NOT 25 MB. Multipart HTTP overhead causes a 413 at the nominal API limit. Files larger than this are split via ffmpeg; chunks are transcribed in parallel via `asyncio.gather`.

## ffmpeg chunk temp files

Chunk temp files must use a real format extension (`.mp3`, `.ogg`, etc.), NOT `.audio`. ffmpeg cannot mux without a known container. Detect format via `ffprobe -show_entries format=format_name` and map to extension before writing the temp file.

## faster-whisper lazy import

`faster_whisper` is imported inside `WhisperTranscriber._run()`, not at module level — avoids slow startup when Whisper is not the active backend.

## TranscriberPipeline wiring

`TranscriberPipeline` itself has no knowledge of which backends to use. The wiring (`[GroqTranscriber, WhisperTranscriber]`) is done in `main.py` via `_build_transcriber()`. When `TRANSCRIBER=groq`, Groq is tried first; on failure or `None` result it falls back to local Whisper automatically.
