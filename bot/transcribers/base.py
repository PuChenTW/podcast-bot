from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, audio_path: str) -> str | None: ...


@runtime_checkable
class ChunkTranscriber(Protocol):
    accepted_formats: tuple[str, ...]
    max_bytes: int

    async def transcribe_chunk(self, path: str) -> str: ...
