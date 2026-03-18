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
from pathlib import Path

import asyncpg

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

        # Tables to migrate in dependency order (FK-safe)
        tables = [
            ("users", "SELECT id, telegram_user_id, chat_id, language, created_at FROM users"),
            ("podcasts", "SELECT id, rss_url, title, created_at FROM podcasts"),
            ("subscriptions", "SELECT id, user_id, podcast_id, custom_prompt, created_at FROM subscriptions"),
            ("episodes", "SELECT id, podcast_id, episode_guid, title, published_at, transcript, condensed_transcript, description FROM episodes"),
            ("user_episodes", "SELECT id, user_id, episode_id, summary, notified_at FROM user_episodes"),
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

            async with pg.transaction():
                for row in rows:
                    values = [row[c] for c in columns]
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
