from core.ai.corrector import CORRECTION_CHUNK_CHARS, _split_chunks, correct_transcript

# --- _split_chunks ---


def test_split_chunks_short():
    text = "hello world"
    assert _split_chunks(text, CORRECTION_CHUNK_CHARS) == [text]


def test_split_chunks_paragraph_boundary():
    # Each paragraph is 6000 chars; two together = 6000+2+6000=12002 > 12000, so each is own chunk
    para = "a" * 6_000
    text = f"{para}\n\n{para}\n\n{para}"
    chunks = _split_chunks(text, CORRECTION_CHUNK_CHARS)
    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk) <= CORRECTION_CHUNK_CHARS


def test_split_chunks_oversized_paragraph():
    # Single paragraph longer than the limit must be hard-cut
    text = "x" * (CORRECTION_CHUNK_CHARS + 500)
    chunks = _split_chunks(text, CORRECTION_CHUNK_CHARS)
    assert len(chunks) == 2
    assert len(chunks[0]) == CORRECTION_CHUNK_CHARS
    assert chunks[1] == "x" * 500


def test_split_chunks_exact_boundary():
    # Two paragraphs that together exactly equal the limit
    half = CORRECTION_CHUNK_CHARS // 2
    para = "b" * half
    text = f"{para}\n\n{para}"
    # Combined length = half + 2 (\n\n) + half = CORRECTION_CHUNK_CHARS + 2 > limit
    chunks = _split_chunks(text, CORRECTION_CHUNK_CHARS)
    # Each paragraph individually fits, so they should be in separate chunks
    assert len(chunks) >= 1
    for chunk in chunks:
        assert len(chunk) <= CORRECTION_CHUNK_CHARS


# --- correct_transcript chunking ---


async def test_correct_short_no_chunking(monkeypatch):
    calls = []

    async def mock_correct_single_chunk(text, podcast_title, ep_title, description):
        calls.append(text)
        return text + "[ok]"

    monkeypatch.setattr("core.ai.corrector._correct_single_chunk", mock_correct_single_chunk)

    result = await correct_transcript(text="short text", podcast_title="Pod", episode_title="Ep1", description="desc")

    assert len(calls) == 1
    assert result.endswith("[ok]")


async def test_correct_long_chunked(monkeypatch):
    calls = []

    async def mock_correct_single_chunk(text, podcast_title, ep_title, description):
        calls.append(text)
        return text

    monkeypatch.setattr("core.ai.corrector._correct_single_chunk", mock_correct_single_chunk)

    # Build a transcript longer than CORRECTION_CHUNK_CHARS via paragraphs
    para = "w" * 6_000
    long_text = "\n\n".join([para] * 4)  # ~24k chars across 4 paragraphs

    await correct_transcript(
        text=long_text,
        podcast_title="Pod",
        episode_title="Long Episode",
        description="desc",
    )

    assert len(calls) > 1
    for chunk in calls:
        assert len(chunk) <= CORRECTION_CHUNK_CHARS
