import pytest

from shared import database as db


@pytest.mark.asyncio
async def test_get_episode_detail_returns_none_for_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    result = await db.get_episode_detail("user1", "pod1", "guid1")
    assert result is None


@pytest.mark.asyncio
async def test_get_episode_detail_returns_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    user_id = await db.get_or_create_user(1001, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://example.com/feed.rss", "Test Pod")
    await db.mark_episode_seen(
        user_id,
        podcast_id,
        "ep-001",
        title="Episode One",
        published_at="2024-01-01T00:00:00",
        summary="My summary",
        transcript="Full transcript text",
    )
    detail = await db.get_episode_detail(user_id, podcast_id, "ep-001")
    assert detail is not None
    assert detail["title"] == "Episode One"
    assert detail["summary"] == "My summary"
    assert detail["transcript"] == "Full transcript text"
    assert detail["condensed_transcript"] is None


@pytest.mark.asyncio
async def test_get_episode_detail_no_summary_when_no_user_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    user_id = await db.get_or_create_user(1002, chat_id=0)
    other_user_id = await db.get_or_create_user(1003, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://example.com/feed2.rss", "Test Pod 2")
    await db.mark_episode_seen(other_user_id, podcast_id, "ep-002", title="Ep2", published_at=None, summary="Other's summary")
    detail = await db.get_episode_detail(user_id, podcast_id, "ep-002")
    assert detail is not None
    assert detail["summary"] is None  # LEFT JOIN: no user_episodes row for user_id


@pytest.mark.asyncio
async def test_get_episodes_by_podcast_with_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    user_id = await db.get_or_create_user(1004, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://example.com/feed3.rss", "Test Pod 3")
    await db.mark_episode_seen(user_id, podcast_id, "ep-a", title="A", published_at="2024-02-01", summary="Sum A")
    await db.mark_episode_seen(user_id, podcast_id, "ep-b", title="B", published_at="2024-01-01", summary=None)
    rows = await db.get_episodes_by_podcast_with_summary(user_id, podcast_id)
    assert len(rows) == 2
    assert rows[0]["episode_guid"] == "ep-a"
    assert rows[0]["has_summary"] == 1
    assert rows[1]["episode_guid"] == "ep-b"
    assert rows[1]["has_summary"] == 0


@pytest.mark.asyncio
async def test_update_episode_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    user_id = await db.get_or_create_user(1005, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://example.com/feed4.rss", "Test Pod 4")
    await db.mark_episode_seen(user_id, podcast_id, "ep-c", title="C", published_at=None, summary=None)
    await db.update_episode_summary(user_id, podcast_id, "ep-c", "New summary")
    detail = await db.get_episode_detail(user_id, podcast_id, "ep-c")
    assert detail["summary"] == "New summary"


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path, monkeypatch):
    import aiosqlite

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    await db.init_db()
    async with aiosqlite.connect(str(tmp_path / "test.db")) as conn:
        async with conn.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
    assert row[0] == "wal"
