FROM python:3.13-slim

# ffmpeg required by faster-whisper for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git openssh-client && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev group)
RUN uv sync --frozen --no-dev

# Copy application source
COPY main.py ./
COPY bot/ ./bot/

CMD ["uv", "run", "python", "main.py"]
