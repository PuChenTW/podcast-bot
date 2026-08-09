import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from pydantic import BaseModel
from ulid import ULID

import migrate
from core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level pool; patched in tests via monkeypatch.setattr(db_module, "_pool", None)
_pool: asyncpg.Pool | None = None


class Subscription(BaseModel):
    id: str
    user_id: str
    podcast_id: str
    podcast_title: str  # populated via JOIN to podcasts
    rss_url: str  # populated via JOIN to podcasts
    custom_prompt: str | None
    chat_prompt: str | None
    telegram_delivery: bool


class SubscriptionWithChat(Subscription):
    chat_id: int


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_settings().database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


@asynccontextmanager
async def _connect():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        yield conn


def _new_id() -> str:
    return str(ULID())


def _parse_dt(value: str | datetime | None) -> datetime | None:
    """Convert a string timestamp to datetime for asyncpg TIMESTAMPTZ parameters."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def close_db() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            logger.warning("Error closing DB pool", exc_info=True)
        _pool = None


async def init_db() -> None:
    pool = await _get_pool()
    async with pool.acquire() as db:
        await migrate.ensure_migrations_table(db)
        applied = await migrate.get_applied_versions(db)
        pending = [(v, up) for v, up, _ in migrate.discover_migrations(migrate.DEFAULT_MIGRATIONS_DIR) if v not in applied]
        for version, up_path in pending:
            logger.info("Applying migration %d: %s", version, up_path.name)
            await migrate._exec_sql_file(db, up_path.read_text())
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES ($1, $2)",
                version,
                datetime.now(timezone.utc).isoformat(),
            )
        if pending:
            logger.info("Applied %d migration(s).", len(pending))


async def get_or_create_user(telegram_user_id: int, chat_id: int) -> str:
    async with _connect() as db:
        row = await db.fetchrow("SELECT id FROM users WHERE telegram_user_id = $1", telegram_user_id)
        if row:
            return row["id"]
        uid = _new_id()
        await db.execute(
            "INSERT INTO users (id, telegram_user_id, chat_id, language) VALUES ($1, $2, $3, 'zh-tw')",
            uid,
            telegram_user_id,
            chat_id,
        )
        return uid


async def get_user_language(telegram_user_id: int) -> str:
    async with _connect() as db:
        row = await db.fetchrow("SELECT language FROM users WHERE telegram_user_id = $1", telegram_user_id)
    if row and row["language"]:
        return row["language"]
    return "zh-tw"


async def set_user_language(telegram_user_id: int, language: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE users SET language = $1 WHERE telegram_user_id = $2",
            language,
            telegram_user_id,
        )


async def get_or_create_podcast(rss_url: str, title: str) -> str:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO podcasts (id, rss_url, title) VALUES ($1, $2, $3) ON CONFLICT (rss_url) DO NOTHING",
            _new_id(),
            rss_url,
            title,
        )
        row = await db.fetchrow("SELECT id FROM podcasts WHERE rss_url = $1", rss_url)
        return row["id"]


async def add_subscription(user_id: str, podcast_title: str, rss_url: str) -> str:
    podcast_id = await get_or_create_podcast(rss_url, podcast_title)
    async with _connect() as db:
        sub_id = _new_id()
        row = await db.fetchrow(
            "INSERT INTO subscriptions (id, user_id, podcast_id) VALUES ($1, $2, $3) ON CONFLICT (user_id, podcast_id) DO UPDATE SET user_id = EXCLUDED.user_id RETURNING id",
            sub_id,
            user_id,
            podcast_id,
        )
        return row["id"]


async def get_subscriptions(user_id: str) -> list[Subscription]:
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt, s.chat_prompt, s.telegram_delivery "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id "
            "WHERE s.user_id = $1 ORDER BY s.created_at",
            user_id,
        )
    return [Subscription.model_validate(dict(r)) for r in rows]


async def get_all_subscriptions() -> list[SubscriptionWithChat]:
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt, s.chat_prompt, s.telegram_delivery, u.chat_id "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id JOIN users u ON s.user_id = u.id"
        )
    return [SubscriptionWithChat.model_validate(dict(r)) for r in rows]


async def remove_subscription(user_id: str, name_fragment: str) -> bool:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT s.id FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id WHERE s.user_id = $1 AND LOWER(p.title) LIKE LOWER($2)",
            user_id,
            f"%{name_fragment}%",
        )
        if not row:
            return False
        await db.execute("DELETE FROM subscriptions WHERE id = $1", row["id"])
        return True


async def remove_subscription_by_id(subscription_id: str) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM subscriptions WHERE id = $1", subscription_id)


async def get_subscription_by_id(subscription_id: str) -> Subscription | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT s.id, s.user_id, s.podcast_id, p.title AS podcast_title, p.rss_url, s.custom_prompt, s.chat_prompt, s.telegram_delivery "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id WHERE s.id = $1",
            subscription_id,
        )
        return Subscription.model_validate(dict(row)) if row else None


async def get_episode_id(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT id FROM episodes WHERE podcast_id = $1 AND episode_guid = $2",
            podcast_id,
            guid,
        )
        return row["id"] if row else None


async def get_episodes_by_podcast(podcast_id: str, limit: int = 50) -> list[dict]:
    """Return cached episodes for a podcast ordered by published_at DESC."""
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT episode_guid, title, published_at FROM episodes WHERE podcast_id = $1 ORDER BY published_at DESC LIMIT $2",
            podcast_id,
            limit,
        )
    return [dict(r) for r in rows]


async def get_episode_detail(user_id: str, episode_id: str) -> dict | None:
    """Return episode fields + user's summary. summary is None if user has no user_episodes row."""
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT e.id, e.podcast_id, e.episode_guid, e.title, e.published_at, e.transcript, e.condensed_transcript, "
            "e.description, ue.summary "
            "FROM episodes e "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = $1 "
            "WHERE e.id = $2",
            user_id,
            episode_id,
        )
        return dict(row) if row else None


async def get_episodes_by_podcast_with_summary(user_id: str, podcast_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Return episodes for a podcast with has_summary flag for this user, newest first."""
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT e.id, e.episode_guid, e.title, e.published_at, "
            "CASE WHEN ue.summary IS NOT NULL THEN 1 ELSE 0 END AS has_summary "
            "FROM episodes e "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = $1 "
            "WHERE e.podcast_id = $2 "
            "ORDER BY e.published_at DESC NULLS LAST LIMIT $3 OFFSET $4",
            user_id,
            podcast_id,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def update_episode_summary(user_id: str, episode_id: str, summary: str) -> None:
    """Upsert summary for a user's episode."""
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT 1 FROM episodes WHERE id = $1",
            episode_id,
        )
        if row is None:
            raise ValueError(f"Episode not found: episode_id={episode_id}")
        await db.execute(
            "INSERT INTO user_episodes (id, user_id, episode_id, summary) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, episode_id) DO UPDATE SET summary = EXCLUDED.summary",
            _new_id(),
            user_id,
            episode_id,
            summary,
        )


async def is_episode_seen(user_id: str, podcast_id: str, guid: str) -> bool:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT 1 FROM user_episodes ue JOIN episodes e ON ue.episode_id = e.id WHERE ue.user_id = $1 AND e.podcast_id = $2 AND e.episode_guid = $3",
            user_id,
            podcast_id,
            guid,
        )
        return row is not None


async def mark_episode_seen(
    user_id: str,
    podcast_id: str,
    guid: str,
    title: str | None = None,
    published_at: str | None = None,
    summary: str | None = None,
    transcript: str | None = None,
    description: str | None = None,
    transcript_source: str | None = None,
) -> None:
    episode_id = await upsert_episode(
        podcast_id,
        guid,
        title=title,
        published_at=published_at,
        transcript=transcript,
        description=description,
        transcript_source=transcript_source,
    )
    await ensure_user_episode(user_id, episode_id, summary=summary)


async def upsert_episode(
    podcast_id: str,
    guid: str,
    title: str | None = None,
    published_at: str | datetime | None = None,
    transcript: str | None = None,
    description: str | None = None,
    transcript_source: str | None = None,
) -> str:
    """Upsert shared episode metadata and return its stable episode ID."""
    async with _connect() as db:
        await db.execute(
            "INSERT INTO episodes (id, podcast_id, episode_guid, title, published_at, transcript, description, transcript_source, transcript_updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CASE WHEN $6::text IS NOT NULL THEN CURRENT_TIMESTAMP END) "
            "ON CONFLICT (podcast_id, episode_guid) DO UPDATE SET "
            "  transcript = COALESCE(EXCLUDED.transcript, episodes.transcript), "
            "  title = COALESCE(EXCLUDED.title, episodes.title), "
            "  published_at = COALESCE(EXCLUDED.published_at, episodes.published_at), "
            "  description = COALESCE(EXCLUDED.description, episodes.description), "
            "  transcript_source = COALESCE(EXCLUDED.transcript_source, episodes.transcript_source), "
            "  transcript_updated_at = COALESCE(EXCLUDED.transcript_updated_at, episodes.transcript_updated_at)",
            _new_id(),
            podcast_id,
            guid,
            title,
            _parse_dt(published_at),
            transcript,
            description,
            transcript_source,
        )
        row = await db.fetchrow(
            "SELECT id FROM episodes WHERE podcast_id = $1 AND episode_guid = $2",
            podcast_id,
            guid,
        )
        return row["id"]


async def ensure_user_episode(user_id: str, episode_id: str, summary: str | None = None) -> None:
    """Create the per-user episode state without changing shared episode data."""
    async with _connect() as db:
        await db.execute(
            "INSERT INTO user_episodes (id, user_id, episode_id, summary) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id, episode_id) DO UPDATE SET summary = COALESCE(EXCLUDED.summary, user_episodes.summary)",
            _new_id(),
            user_id,
            episode_id,
            summary,
        )


async def get_episode_transcript(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT transcript FROM episodes WHERE podcast_id = $1 AND episode_guid = $2",
            podcast_id,
            guid,
        )
        return row["transcript"] if row else None


async def get_episode_condensed_transcript(podcast_id: str, guid: str) -> str | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT condensed_transcript FROM episodes WHERE podcast_id = $1 AND episode_guid = $2",
            podcast_id,
            guid,
        )
        return row["condensed_transcript"] if row else None


async def get_podcast(podcast_id: str) -> dict | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT id, rss_url, title FROM podcasts WHERE id = $1",
            podcast_id,
        )
        return dict(row) if row else None


async def get_podcast_for_user(user_id: str, podcast_id: str) -> dict | None:
    """Return a podcast plus this user's subscription ID, if any."""
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT p.id, p.rss_url, p.title, s.id AS subscription_id, COALESCE(s.telegram_delivery, TRUE) AS telegram_delivery "
            "FROM podcasts p LEFT JOIN subscriptions s ON s.podcast_id = p.id AND s.user_id = $1 WHERE p.id = $2",
            user_id,
            podcast_id,
        )
    return dict(row) if row else None


async def get_episode_for_user(user_id: str, episode_id: str) -> dict | None:
    """Return episode data with nullable subscription_id to distinguish 403 from 404."""
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT e.id, e.podcast_id, e.episode_guid, e.title, e.published_at, e.description, e.transcript, "
            "e.condensed_transcript, e.transcript_source, e.transcript_updated_at, p.title AS podcast_title, p.rss_url, "
            "s.id AS subscription_id, s.custom_prompt, s.chat_prompt, ue.summary "
            "FROM episodes e JOIN podcasts p ON p.id = e.podcast_id "
            "LEFT JOIN subscriptions s ON s.podcast_id = e.podcast_id AND s.user_id = $1 "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = $1 "
            "WHERE e.id = $2",
            user_id,
            episode_id,
        )
    return dict(row) if row else None


async def list_podcasts_for_user(user_id: str, query: str, limit: int, after_id: str | None = None) -> list[dict]:
    params: list = [user_id, f"%{query}%", limit]
    cursor_sql = ""
    if after_id is not None:
        params.append(after_id)
        cursor_sql = " AND s.id > $4"
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT p.id, p.rss_url, p.title, s.id AS subscription_id, s.telegram_delivery "
            "FROM subscriptions s JOIN podcasts p ON p.id = s.podcast_id "
            "WHERE s.user_id = $1 AND ($2 = '%%' OR p.title ILIKE $2)" + cursor_sql + " ORDER BY s.id LIMIT $3",
            *params,
        )
    return [dict(row) for row in rows]


async def list_episodes_for_user(
    user_id: str,
    podcast_id: str,
    limit: int,
    after_published_at: datetime | None = None,
    after_id: str | None = None,
) -> list[dict]:
    cursor_sql = ""
    params: list = [user_id, podcast_id, limit]
    if after_id is not None and after_published_at is None:
        params.append(after_id)
        cursor_sql = " AND e.published_at IS NULL AND e.id < $4"
    elif after_id is not None:
        params.extend([after_published_at, after_id])
        cursor_sql = " AND (e.published_at < $4 OR (e.published_at = $4 AND e.id < $5) OR e.published_at IS NULL)"
    async with _connect() as db:
        rows = await db.fetch(
            "SELECT e.id, e.title, e.published_at, e.description, "
            "(e.transcript IS NOT NULL) AS has_transcript, (ue.summary IS NOT NULL) AS has_summary "
            "FROM episodes e JOIN subscriptions s ON s.podcast_id = e.podcast_id AND s.user_id = $1 "
            "LEFT JOIN user_episodes ue ON ue.episode_id = e.id AND ue.user_id = $1 "
            "WHERE e.podcast_id = $2" + cursor_sql + " ORDER BY e.published_at DESC NULLS LAST, e.id DESC LIMIT $3",
            *params,
        )
    return [dict(row) for row in rows]


async def update_episode_transcript(podcast_id: str, guid: str, transcript: str) -> None:
    """Update transcript for an existing episode row."""
    async with _connect() as db:
        await db.execute(
            "UPDATE episodes SET transcript = $1 WHERE podcast_id = $2 AND episode_guid = $3",
            transcript,
            podcast_id,
            guid,
        )


async def replace_episode_transcript(episode_id: str, transcript: str, source: str) -> None:
    """Replace a transcript atomically and invalidate all derived transcript data."""
    async with _connect() as db:
        result = await db.execute(
            "UPDATE episodes SET transcript = $1, transcript_source = $2, transcript_updated_at = CURRENT_TIMESTAMP, condensed_transcript = NULL WHERE id = $3",
            transcript,
            source,
            episode_id,
        )
    if result == "UPDATE 0":
        raise ValueError(f"Episode not found: episode_id={episode_id}")


async def save_episode_condensed_transcript(podcast_id: str, guid: str, condensed_transcript: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE episodes SET condensed_transcript = $1 WHERE podcast_id = $2 AND episode_guid = $3",
            condensed_transcript,
            podcast_id,
            guid,
        )


async def get_episode_summary(user_id: str, episode_id: str) -> str | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT summary FROM user_episodes WHERE user_id = $1 AND episode_id = $2",
            user_id,
            episode_id,
        )
        return row["summary"] if row else None


async def set_subscription_prompt(subscription_id: str, prompt: str | None) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE subscriptions SET custom_prompt = $1 WHERE id = $2",
            prompt,
            subscription_id,
        )


async def set_subscription_chat_prompt(subscription_id: str, prompt: str | None) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE subscriptions SET chat_prompt = $1 WHERE id = $2",
            prompt,
            subscription_id,
        )


async def set_subscription_telegram_delivery(subscription_id: str, enabled: bool) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE subscriptions SET telegram_delivery = $1 WHERE id = $2",
            enabled,
            subscription_id,
        )


async def update_subscription_prompts(
    subscription_id: str,
    updates: dict[str, str | None],
) -> None:
    if not updates:
        return
    assignments: list[str] = []
    values: list[str | None] = []
    if "custom_prompt" in updates:
        values.append(updates["custom_prompt"])
        assignments.append(f"custom_prompt = ${len(values)}")
    if "chat_prompt" in updates:
        values.append(updates["chat_prompt"])
        assignments.append(f"chat_prompt = ${len(values)}")
    values.append(subscription_id)
    async with _connect() as db:
        await db.execute(
            f"UPDATE subscriptions SET {', '.join(assignments)} WHERE id = ${len(values)}",
            *values,
        )


async def create_api_job(user_id: str, episode_id: str, kind: str, result_url: str) -> dict:
    async with _connect() as db:
        row = await db.fetchrow(
            "INSERT INTO api_jobs (id, user_id, episode_id, kind, result_url) VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (user_id, episode_id, kind) WHERE status IN ('pending', 'running') DO NOTHING RETURNING *",
            _new_id(),
            user_id,
            episode_id,
            kind,
            result_url,
        )
        if row is None:
            row = await db.fetchrow(
                "SELECT * FROM api_jobs WHERE user_id = $1 AND episode_id = $2 AND kind = $3 AND status IN ('pending', 'running') ORDER BY created_at LIMIT 1",
                user_id,
                episode_id,
                kind,
            )
    return dict(row)


async def get_api_job_for_user(user_id: str, job_id: str) -> dict | None:
    async with _connect() as db:
        row = await db.fetchrow(
            "SELECT id, user_id, episode_id, kind, status, result_url, error_code, error_message, created_at, started_at, finished_at FROM api_jobs WHERE id = $1",
            job_id,
        )
    return dict(row) if row else None


async def requeue_expired_api_jobs() -> None:
    async with _connect() as db:
        await db.execute("UPDATE api_jobs SET status = 'pending', started_at = NULL, worker_id = NULL, lease_expires_at = NULL WHERE status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP")


async def claim_api_job(worker_id: str) -> dict | None:
    async with _connect() as db:
        async with db.transaction():
            await db.execute("UPDATE api_jobs SET status = 'pending', started_at = NULL, worker_id = NULL, lease_expires_at = NULL WHERE status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP")
            row = await db.fetchrow("SELECT id FROM api_jobs WHERE status = 'pending' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
            if row is None:
                return None
            claimed = await db.fetchrow(
                "UPDATE api_jobs SET status = 'running', started_at = CURRENT_TIMESTAMP, worker_id = $2, "
                "lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '60 seconds', error_code = NULL, error_message = NULL "
                "WHERE id = $1 RETURNING *",
                row["id"],
                worker_id,
            )
    return dict(claimed)


async def renew_api_job_lease(job_id: str, worker_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE api_jobs SET lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '60 seconds' WHERE id = $1 AND worker_id = $2 AND status = 'running'",
            job_id,
            worker_id,
        )


async def complete_api_job(job_id: str, worker_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE api_jobs SET status = 'done', finished_at = CURRENT_TIMESTAMP, lease_expires_at = NULL WHERE id = $1 AND worker_id = $2 AND status = 'running'",
            job_id,
            worker_id,
        )


async def fail_api_job(job_id: str, worker_id: str, error: tuple[str, str]) -> None:
    error_code, error_message = error
    async with _connect() as db:
        await db.execute(
            "UPDATE api_jobs SET status = 'error', error_code = $3, error_message = $4, finished_at = CURRENT_TIMESTAMP, lease_expires_at = NULL "
            "WHERE id = $1 AND worker_id = $2 AND status = 'running'",
            job_id,
            worker_id,
            error_code,
            error_message,
        )
