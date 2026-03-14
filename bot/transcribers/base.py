from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, audio_path: str) -> str | None: ...
