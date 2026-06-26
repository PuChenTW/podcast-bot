"""Download a sherpa-onnx Nemotron-3.5 streaming ASR model bundle into models/.

The model is git-ignored (~665 MB), so a fresh clone or deployment must fetch it
before running with TRANSCRIBER=nemotron. Bundles are published by the sherpa-onnx
maintainer on Hugging Face; we pull the encoder/decoder/joiner .onnx + tokens.txt.

    uv run python -m scripts.download_nemotron                 # default: 1120ms int8
    uv run python -m scripts.download_nemotron --chunk 560ms   # lower latency
    uv run python -m scripts.download_nemotron --no-int8       # full precision
"""

import argparse
import subprocess
import sys
from pathlib import Path

CHUNKS = ("80ms", "160ms", "560ms", "1120ms")
DATE = "2026-06-11"
FILES = ("tokens.txt", "decoder.int8.onnx", "joiner.int8.onnx", "encoder.int8.onnx", "test_wavs/en.wav", "test_wavs/ja.wav")


def _repo(chunk: str, int8: bool) -> str:
    quant = "int8-" if int8 else ""
    return f"csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-{chunk}-{quant}{DATE}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chunk", choices=CHUNKS, default="1120ms", help="streaming chunk size (default: 1120ms)")
    p.add_argument("--no-int8", dest="int8", action="store_false", help="download full-precision instead of int8")
    p.add_argument("--dest", default="models/nemotron-3.5-ml", help="destination directory (default: models/nemotron-3.5-ml)")
    args = p.parse_args()

    repo = _repo(args.chunk, args.int8)
    files = FILES if args.int8 else tuple(f.replace(".int8", "") for f in FILES)
    dest = Path(args.dest)
    print(f"Downloading {repo} -> {dest}/")

    for f in files:
        out = dest / f
        out.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{repo}/resolve/main/{f}"
        print(f"  {f} ...", flush=True)
        r = subprocess.run(["curl", "-fsSL", "-o", str(out), url])
        if r.returncode != 0:
            print(f"FAILED to download {url}", file=sys.stderr)
            return 1

    print(f"Done. Set NEMOTRON_MODEL_DIR={dest} and TRANSCRIBER=nemotron in .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
