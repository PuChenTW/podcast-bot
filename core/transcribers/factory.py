from core.config import Settings
from core.transcribers.audio_pipeline import AudioPipeline
from core.transcribers.base import Transcriber
from core.transcribers.groq import GroqTranscriber
from core.transcribers.nemotron import NemotronTranscriber
from core.transcribers.pipeline import TranscriberPipeline
from core.transcribers.whisper import WhisperTranscriber


def build_transcriber(settings: Settings) -> Transcriber:
    whisper = AudioPipeline(WhisperTranscriber(settings.whisper_model))
    if settings.transcriber_backend == "groq":
        return TranscriberPipeline(
            [
                AudioPipeline(GroqTranscriber(settings.groq_api_key)),
                AudioPipeline(NemotronTranscriber(settings.nemotron_model_dir, settings.nemotron_language)),
                whisper,
            ]
        )
    if settings.transcriber_backend == "nemotron":
        return TranscriberPipeline(
            [
                AudioPipeline(NemotronTranscriber(settings.nemotron_model_dir, settings.nemotron_language)),
                whisper,
            ]
        )
    return whisper
