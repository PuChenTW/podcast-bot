"""One-time migration script: copies all data from SQLite to PostgreSQL.

Usage:
    uv run python scripts/migrate_sqlite_to_postgres.py \\
        --sqlite podcast_bot.db \\
        --postgres postgresql://podcast:secret@localhost:5432/podcast_bot

The script is idempotent (uses INSERT ... ON CONFLICT DO NOTHING) and can be re-run safely.
Tables are created if they don't exist before migration begins.
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import asyncpg

# Columns that are TIMESTAMPTZ in PostgreSQL but stored as strings in SQLite
_TIMESTAMP_COLS: dict[str, set[str]] = {
    "users": {"created_at"},
    "podcasts": {"created_at"},
    "subscriptions": {"created_at"},
    "episodes": {"published_at"},
    "user_episodes": {"notified_at"},
}

# Path to the PostgreSQL migration SQL file (relative to project root)
PG_MIGRATIONS_DIR = Path(__file__).parent.parent / "pg_migrations"


async def _exec_sql_file(pg: asyncpg.Connection, path: Path) -> None:
    sql = path.read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        await pg.execute(stmt)


def _fetch_all_sqlite(sqlite_path: str, sql: str) -> list[dict]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def migrate(sqlite_path: str, postgres_url: str) -> None:
    print(f"Source SQLite:     {sqlite_path}")
    print(f"Target PostgreSQL: {postgres_url}\n")

    pg = await asyncpg.connect(postgres_url)
    try:
        # Ensure schema exists
        print("Applying pg_migrations/001_up.sql …")
        await _exec_sql_file(pg, PG_MIGRATIONS_DIR / "001_up.sql")
        print("Schema ready.\n")

        # Tables to migrate in dependency order (FK-safe).
        # Queries filter out orphaned rows to avoid FK violations in PostgreSQL.
        tables = [
            ("users", "SELECT id, telegram_user_id, chat_id, language, created_at FROM users"),
            ("podcasts", "SELECT id, rss_url, title, created_at FROM podcasts"),
            (
                "subscriptions",
                "SELECT s.id, s.user_id, s.podcast_id, s.custom_prompt, s.created_at FROM subscriptions s "
                "WHERE EXISTS (SELECT 1 FROM users u WHERE u.id = s.user_id) "
                "AND EXISTS (SELECT 1 FROM podcasts p WHERE p.id = s.podcast_id)",
            ),
            (
                "episodes",
                "SELECT e.id, e.podcast_id, e.episode_guid, e.title, e.published_at, e.transcript, e.condensed_transcript, e.description FROM episodes e "
                "WHERE EXISTS (SELECT 1 FROM podcasts p WHERE p.id = e.podcast_id)",
            ),
            (
                "user_episodes",
                "SELECT ue.id, ue.user_id, ue.episode_id, ue.summary, ue.notified_at FROM user_episodes ue "
                "WHERE EXISTS (SELECT 1 FROM users u WHERE u.id = ue.user_id) "
                "AND EXISTS (SELECT 1 FROM episodes e WHERE e.id = ue.episode_id)",
            ),
            ("schema_migrations", "SELECT version, applied_at FROM schema_migrations"),
        ]

        for table, sql in tables:
            rows = _fetch_all_sqlite(sqlite_path, sql)
            if not rows:
                print(f"  {table}: 0 rows (skipped)")
                continue

            columns = list(rows[0].keys())
            placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
            col_list = ", ".join(columns)
            insert_sql = (
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            )

            ts_cols = _TIMESTAMP_COLS.get(table, set())
            async with pg.transaction():
                for row in rows:
                    values = []
                    for c in columns:
                        v = row[c]
                        if c in ts_cols and isinstance(v, str):
                            try:
                                v = datetime.fromisoformat(v)
                            except ValueError:
                                v = None
                        values.append(v)
                    await pg.execute(insert_sql, *values)

            print(f"  {table}: {len(rows)} rows migrated")

        print("\nMigration complete.")
    finally:
        await pg.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL")
    parser.add_argument("--sqlite", default="podcast_bot.db", help="Path to SQLite database file")
    parser.add_argument("--postgres", required=True, help="PostgreSQL connection URL")
    args = parser.parse_args()

    if not Path(args.sqlite).exists():
        print(f"Error: SQLite file not found: {args.sqlite}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(migrate(args.sqlite, args.postgres))


if __name__ == "__main__":
    main()
