import aiosqlite
from ulid import ULID

DB_PATH = "podcast_bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    telegram_user_id INTEGER UNIQUE NOT NULL,
    chat_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    podcast_title TEXT NOT NULL,
    rss_url TEXT NOT NULL,
    custom_prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    subscription_id TEXT REFERENCES subscriptions(id),
    episode_guid TEXT NOT NULL,
    title TEXT,
    published_at TIMESTAMP,
    summary TEXT,
    transcript TEXT,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(subscription_id, episode_guid)
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _new_id() -> str:
    return str(ULID())


async def get_or_create_user(telegram_user_id: int, chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return row[0]
        uid = _new_id()
        await db.execute(
            "INSERT INTO users (id, telegram_user_id, chat_id) VALUES (?, ?, ?)",
            (uid, telegram_user_id, chat_id),
        )
        await db.commit()
        return uid


async def add_subscription(user_id: str, podcast_title: str, rss_url: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        sub_id = _new_id()
        await db.execute(
            "INSERT INTO subscriptions (id, user_id, podcast_title, rss_url) VALUES (?, ?, ?, ?)",
            (sub_id, user_id, podcast_title, rss_url),
        )
        await db.commit()
        return sub_id


async def get_subscriptions(user_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, podcast_title, rss_url, custom_prompt FROM subscriptions WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_subscriptions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT s.id, s.podcast_title, s.rss_url, s.custom_prompt, u.chat_id "
            "FROM subscriptions s JOIN users u ON s.user_id = u.id"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def remove_subscription(user_id: str, name_fragment: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM subscriptions WHERE user_id = ? AND LOWER(podcast_title) LIKE LOWER(?)",
            (user_id, f"%{name_fragment}%"),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return False
        await db.execute("DELETE FROM subscriptions WHERE id = ?", (row[0],))
        await db.commit()
        return True


async def get_subscription_by_id(subscription_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, podcast_title, rss_url, custom_prompt FROM subscriptions WHERE id = ?",
            (subscription_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def is_episode_seen(subscription_id: str, guid: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM episodes WHERE subscription_id = ? AND episode_guid = ?",
            (subscription_id, guid),
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_episode_seen(
    subscription_id: str,
    guid: str,
    title: str | None = None,
    published_at: str | None = None,
    summary: str | None = None,
    transcript: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO episodes (id, subscription_id, episode_guid, title, published_at, summary, transcript) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(subscription_id, episode_guid) DO UPDATE SET "
            "  summary = COALESCE(excluded.summary, summary), "
            "  transcript = COALESCE(excluded.transcript, transcript)",
            (
                _new_id(),
                subscription_id,
                guid,
                title,
                published_at,
                summary,
                transcript,
            ),
        )
        await db.commit()


async def get_episode_transcript(subscription_id: str, guid: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT transcript FROM episodes WHERE subscription_id=? AND episode_guid=?",
            (subscription_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_subscription_prompt(subscription_id: str, prompt: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET custom_prompt = ? WHERE id = ?",
            (prompt, subscription_id),
        )
        await db.commit()
