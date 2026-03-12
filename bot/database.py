from contextlib import asynccontextmanager

import aiosqlite
from pydantic import BaseModel
from ulid import ULID

DB_PATH = "podcast_bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    telegram_user_id INTEGER UNIQUE NOT NULL,
    chat_id INTEGER NOT NULL,
    language TEXT DEFAULT 'zh-tw',
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


class Subscription(BaseModel):
    id: str
    podcast_title: str
    rss_url: str
    custom_prompt: str | None


class SubscriptionWithChat(Subscription):
    chat_id: int


@asynccontextmanager
async def _connect():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


def _new_id() -> str:
    return str(ULID())


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def get_or_create_user(telegram_user_id: int, chat_id: int) -> str:
    async with _connect() as db:
        async with db.execute(
            "SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return row[0]
        uid = _new_id()
        await db.execute(
            "INSERT INTO users (id, telegram_user_id, chat_id, language) VALUES (?, ?, ?, 'zh-tw')",
            (uid, telegram_user_id, chat_id),
        )
        await db.commit()
        return uid


async def get_user_language(telegram_user_id: int) -> str:
    async with _connect() as db:
        async with db.execute(
            "SELECT language FROM users WHERE telegram_user_id = ?", (telegram_user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row and row[0]:
            return row[0]
        return "zh-tw"


async def set_user_language(telegram_user_id: int, language: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE users SET language = ? WHERE telegram_user_id = ?",
            (language, telegram_user_id),
        )
        await db.commit()


async def add_subscription(user_id: str, podcast_title: str, rss_url: str) -> str:
    async with _connect() as db:
        sub_id = _new_id()
        await db.execute(
            "INSERT INTO subscriptions (id, user_id, podcast_title, rss_url) VALUES (?, ?, ?, ?)",
            (sub_id, user_id, podcast_title, rss_url),
        )
        await db.commit()
        return sub_id


async def get_subscriptions(user_id: str) -> list[Subscription]:
    async with _connect() as db:
        async with db.execute(
            "SELECT id, podcast_title, rss_url, custom_prompt FROM subscriptions WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [Subscription.model_validate(dict(r)) for r in rows]


async def get_all_subscriptions() -> list[SubscriptionWithChat]:
    async with _connect() as db:
        async with db.execute(
            "SELECT s.id, s.podcast_title, s.rss_url, s.custom_prompt, u.chat_id "
            "FROM subscriptions s JOIN users u ON s.user_id = u.id"
        ) as cursor:
            rows = await cursor.fetchall()
    return [SubscriptionWithChat.model_validate(dict(r)) for r in rows]


async def remove_subscription(user_id: str, name_fragment: str) -> bool:
    async with _connect() as db:
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


async def remove_subscription_by_id(subscription_id: str) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        await db.commit()


async def get_subscription_by_id(subscription_id: str) -> Subscription | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT id, podcast_title, rss_url, custom_prompt FROM subscriptions WHERE id = ?",
            (subscription_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return Subscription.model_validate(dict(row)) if row else None


async def is_episode_seen(subscription_id: str, guid: str) -> bool:
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
        async with db.execute(
            "SELECT transcript FROM episodes WHERE subscription_id=? AND episode_guid=?",
            (subscription_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_episode_summary(subscription_id: str, guid: str) -> str | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT summary FROM episodes WHERE subscription_id=? AND episode_guid=?",
            (subscription_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_subscription_prompt(subscription_id: str, prompt: str | None) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE subscriptions SET custom_prompt = ? WHERE id = ?",
            (prompt, subscription_id),
        )
        await db.commit()
