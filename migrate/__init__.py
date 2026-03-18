"""DB migration runner. Usage: python -m migrate [up|down <version>|status]"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

DEFAULT_MIGRATIONS_DIR = Path(__file__).parent.parent / "pg_migrations"


async def _exec_sql_file(db: asyncpg.Connection, sql_text: str) -> None:
    """Execute a SQL file by splitting on semicolons and running each statement."""
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    for stmt in statements:
        await db.execute(stmt)


async def ensure_migrations_table(db: asyncpg.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )


async def get_applied_versions(db: asyncpg.Connection) -> set[int]:
    rows = await db.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


def discover_migrations(
    migrations_dir: Path,
) -> list[tuple[int, Path, Path | None]]:
    """Returns sorted list of (version, up_path, down_path | None)."""
    if not migrations_dir.exists():
        return []
    results = []
    for up_path in migrations_dir.iterdir():
        m = re.match(r"^(\d+)_up\.sql$", up_path.name)
        if not m:
            continue
        version = int(m.group(1))
        down_path = migrations_dir / up_path.name.replace("_up.sql", "_down.sql")
        results.append((version, up_path, down_path if down_path.exists() else None))
    return sorted(results, key=lambda t: t[0])


async def migrate_up(
    db_url: str | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    if db_url is None:
        from core.config import get_settings
        db_url = get_settings().database_url
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        applied = await get_applied_versions(db)
        migrations = discover_migrations(migrations_dir)
        pending = [(v, up, down) for v, up, down in migrations if v not in applied]
        if not pending:
            print("Nothing to migrate.")
            return
        for version, up_path, _ in pending:
            print(f"Applying migration {version}: {up_path.name}")
            await _exec_sql_file(db, up_path.read_text())
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES ($1, $2)",
                version,
                datetime.now(timezone.utc).isoformat(),
            )
        print(f"Applied {len(pending)} migration(s).")
    finally:
        await db.close()


async def migrate_down(
    db_url: str | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    target_version: int = 0,
) -> None:
    if db_url is None:
        from core.config import get_settings
        db_url = get_settings().database_url
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        applied = await get_applied_versions(db)
        migrations = discover_migrations(migrations_dir)
        to_rollback = sorted(
            [(v, up, down) for v, up, down in migrations if v in applied and v > target_version],
            key=lambda t: t[0],
            reverse=True,
        )
        if not to_rollback:
            print("Nothing to rollback.")
            return
        for version, _, down_path in to_rollback:
            if down_path is None:
                print(f"Error: no down migration for version {version}", file=sys.stderr)
                sys.exit(1)
            print(f"Rolling back migration {version}: {down_path.name}")
            await _exec_sql_file(db, down_path.read_text())
            await db.execute("DELETE FROM schema_migrations WHERE version = $1", version)
        print(f"Rolled back {len(to_rollback)} migration(s).")
    finally:
        await db.close()


async def status(
    db_url: str | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    if db_url is None:
        from core.config import get_settings
        db_url = get_settings().database_url
    migrations = discover_migrations(migrations_dir)
    if not migrations:
        print("No migrations found.")
        return
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        applied = await get_applied_versions(db)
    finally:
        await db.close()
    print(f"{'Version':<10} {'Status':<10} {'File'}")
    print("-" * 50)
    for version, up_path, _ in migrations:
        state = "applied" if version in applied else "pending"
        print(f"{version:<10} {state:<10} {up_path.name}")
