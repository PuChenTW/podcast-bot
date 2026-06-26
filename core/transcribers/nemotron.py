import asyncio
import logging
import subprocess
import wave

logger = logging.getLogger(__name__)

NEMOTRON_MAX_BYTES = 2_000_000_000  # effectively unlimited for local processing
SAMPLE_RATE = 16_000


class NemotronTranscriber:
    """Local streaming ASR via NVIDIA Nemotron-3.5 (multilingual) on sherpa-onnx.

    Runs on CPU (incl. Apple Silicon) at RTF ~0.06 — no CUDA required. The model
    directory must contain sherpa-onnx-format files: encoder/decoder/joiner .onnx
    plus tokens.txt (e.g. csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-*).
    """

    accepted_formats = ("wav",)
    max_bytes = NEMOTRON_MAX_BYTES

    def __init__(self, model_dir: str, language: str = "auto", num_threads: int = 4) -> None:
        self._model_dir = model_dir
        self._language = language
        self._num_threads = num_threads
        self._recognizer = None

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx

            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=f"{self._model_dir}/tokens.txt",
                encoder=f"{self._model_dir}/encoder.int8.onnx",
                decoder=f"{self._model_dir}/decoder.int8.onnx",
                joiner=f"{self._model_dir}/joiner.int8.onnx",
                num_threads=self._num_threads,
                model_type="nemo_transducer",
                provider="cpu",
            )
        return self._recognizer

    async def transcribe_chunk(self, path: str) -> str:
        return await asyncio.to_thread(self._run, path)

    def _run(self, path: str) -> str:
        import numpy as np

        samples = self._read_16k_mono(path)
        rec = self._get_recognizer()
        stream = rec.create_stream()
        if stream.has_option("language"):
            stream.set_option("language", self._language)
        stream.accept_waveform(SAMPLE_RATE, samples)
        # Pad with trailing silence so the cache-aware decoder flushes the final tokens.
        stream.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
        stream.input_finished()
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        return rec.get_result(stream).strip()

    def _read_16k_mono(self, path: str):
        """Decode any audio file to 16 kHz mono float32 via ffmpeg piping a WAV to stdout."""
        import numpy as np

        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "wav", "-"],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg decode failed: {proc.stderr.decode('utf-8', 'replace')[:200]}")
        import io

        with wave.open(io.BytesIO(proc.stdout)) as w:
            frames = w.readframes(w.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
