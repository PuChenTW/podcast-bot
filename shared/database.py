import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from pydantic import BaseModel
from ulid import ULID

import migrate

logger = logging.getLogger(__name__)

DB_PATH = "podcast_bot.db"


class Subscription(BaseModel):
    id: str
    user_id: str
    podcast_id: str
    podcast_title: str  # populated via JOIN to podcasts
    rss_url: str  # populated via JOIN to podcasts
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
        await migrate.ensure_migrations_table(db)
        applied = await migrate.get_applied_versions(db)
        pending = [(v, up) for v, up, _ in migrate.discover_migrations(migrate.DEFAULT_MIGRATIONS_DIR) if v not in applied]
        for version, up_path in pending:
            logger.info("Applying migration %d: %s", version, up_path.name)
            await db.executescript(up_path.read_text())
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
        if pending:
            logger.info("Applied %d migration(s).", len(pending))
        # Enable WAL mode for concurrent reads from web + bot processes (idempotent, safe every startup)
        await db.execute("PRAGMA journal_mode=WAL")


async def get_or_create_user(telegram_user_id: int, chat_id: int) -> str:
    async with _connect() as db:
        async with db.execute("SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)) as cursor:
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
        async with db.execute("SELECT language FROM users WHERE telegram_user_id = ?", (telegram_user_id,)) as cursor:
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


async def get_or_create_podcast(rss_url: str, title: str) -> str:
    async with _connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO podcasts (id, rss_url, title) VALUES (?, ?, ?)",
            (_new_id(), rss_url, title),
        )
        await db.commit()
        async with db.execute("SELECT id FROM podcasts WHERE rss_url = ?", (rss_url,)) as cursor:
            row = await cursor.fetchone()
        return row[0]


async def add_subscription(user_id: str, podcast_title: str, rss_url: str) -> str:
    podcast_id = await get_or_create_podcast(rss_url, podcast_title)
    async with _connect() as db:
        sub_id = _new_id()
        await db.execute(
            "INSERT INTO subscriptions (id, user_id, podcast_id) VALUES (?, ?, ?)",
            (sub_id, user_id, podcast_id),
        )
        await db.commit()
        return sub_id


async def get_subscriptions(user_id: str) -> list[Subscription]:
    async with _connect() as db:
        async with db.execute(
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id "
            "WHERE s.user_id = ? ORDER BY s.created_at",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [Subscription.model_validate(dict(r)) for r in rows]


async def get_all_subscriptions() -> list[SubscriptionWithChat]:
    async with _connect() as db:
        async with db.execute(
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt, u.chat_id "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id JOIN users u ON s.user_id = u.id"
        ) as cursor:
            rows = await cursor.fetchall()
    return [SubscriptionWithChat.model_validate(dict(r)) for r in rows]


async def remove_subscription(user_id: str, name_fragment: str) -> bool:
    async with _connect() as db:
        async with db.execute(
            "SELECT s.id FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id WHERE s.user_id = ? AND LOWER(p.title) LIKE LOWER(?)",
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
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id WHERE s.id = ?",
            (subscription_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return Subscription.model_validate(dict(row)) if row else None


async def get_episode_id(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT id FROM episodes WHERE podcast_id = ? AND episode_guid = ?",
            (podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None


async def get_episodes_by_podcast(podcast_id: str, limit: int = 50) -> list[dict]:
    """Return cached episodes for a podcast ordered by published_at DESC."""
    async with _connect() as db:
        async with db.execute(
            "SELECT episode_guid, title, published_at FROM episodes WHERE podcast_id = ? ORDER BY published_at DESC LIMIT ?",
            (podcast_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_episode_detail(user_id: str, podcast_id: str, guid: str) -> dict | None:
    """Return episode fields + user's summary. summary is None if user has no user_episodes row."""
    async with _connect() as db:
        async with db.execute(
            "SELECT e.id, e.title, e.published_at, e.transcript, e.condensed_transcript, ue.summary "
            "FROM episodes e "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = ? "
            "WHERE e.podcast_id = ? AND e.episode_guid = ?",
            (user_id, podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def get_episodes_by_podcast_with_summary(user_id: str, podcast_id: str, limit: int = 50) -> list[dict]:
    """Return episodes for a podcast with has_summary flag for this user."""
    async with _connect() as db:
        async with db.execute(
            "SELECT e.id, e.episode_guid, e.title, e.published_at, "
            "CASE WHEN ue.summary IS NOT NULL THEN 1 ELSE 0 END AS has_summary "
            "FROM episodes e "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = ? "
            "WHERE e.podcast_id = ? "
            "ORDER BY e.published_at DESC LIMIT ?",
            (user_id, podcast_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_episode_summary(user_id: str, podcast_id: str, guid: str, summary: str) -> None:
    """Upsert summary for a user's episode. Resolves guid → episode_id first."""
    async with _connect() as db:
        async with db.execute(
            "SELECT id FROM episodes WHERE podcast_id = ? AND episode_guid = ?",
            (podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Episode not found: podcast_id={podcast_id}, guid={guid}")
        episode_id = row[0]
        await db.execute(
            "INSERT INTO user_episodes (id, user_id, episode_id, summary) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, episode_id) DO UPDATE SET summary = excluded.summary",
            (_new_id(), user_id, episode_id, summary),
        )
        await db.commit()


async def is_episode_seen(user_id: str, podcast_id: str, guid: str) -> bool:
    async with _connect() as db:
        async with db.execute(
            "SELECT 1 FROM user_episodes ue JOIN episodes e ON ue.episode_id = e.id WHERE ue.user_id = ? AND e.podcast_id = ? AND e.episode_guid = ?",
            (user_id, podcast_id, guid),
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_episode_seen(
    user_id: str,
    podcast_id: str,
    guid: str,
    title: str | None = None,
    published_at: str | None = None,
    summary: str | None = None,
    transcript: str | None = None,
) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO episodes (id, podcast_id, episode_guid, title, published_at, transcript) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(podcast_id, episode_guid) DO UPDATE SET "
            "  transcript = COALESCE(excluded.transcript, transcript), "
            "  title = COALESCE(excluded.title, title), "
            "  published_at = COALESCE(excluded.published_at, published_at)",
            (_new_id(), podcast_id, guid, title, published_at, transcript),
        )
        async with db.execute(
            "SELECT id FROM episodes WHERE podcast_id = ? AND episode_guid = ?",
            (podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
        episode_id = row[0]
        await db.execute(
            "INSERT INTO user_episodes (id, user_id, episode_id, summary) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, episode_id) DO UPDATE SET summary = COALESCE(excluded.summary, summary)",
            (_new_id(), user_id, episode_id, summary),
        )
        await db.commit()


async def get_episode_transcript(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT transcript FROM episodes WHERE podcast_id = ? AND episode_guid = ?",
            (podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_episode_condensed_transcript(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT condensed_transcript FROM episodes WHERE podcast_id = ? AND episode_guid = ?",
            (podcast_id, guid),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def save_episode_condensed_transcript(podcast_id: str, guid: str, condensed_transcript: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE episodes SET condensed_transcript = ? WHERE podcast_id = ? AND episode_guid = ?",
            (condensed_transcript, podcast_id, guid),
        )
        await db.commit()


async def get_episode_summary(user_id: str, episode_id: str) -> str | None:
    async with _connect() as db:
        async with db.execute(
            "SELECT summary FROM user_episodes WHERE user_id = ? AND episode_id = ?",
            (user_id, episode_id),
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
