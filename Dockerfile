FROM python:3.13-slim

# ffmpeg required by faster-whisper for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev group)
RUN uv sync --frozen --no-dev --all-extras

# Copy application source
COPY bot_main.py web_main.py ./
COPY bot/ ./bot/
COPY web/ ./web/
COPY core/ ./core/
COPY migrate/ ./migrate/
COPY pg_migrations/ ./pg_migrations/

CMD ["uv", "run", "python", "bot_main.py"]
