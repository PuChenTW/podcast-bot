"""DB migration runner. Usage: python -m migrate [up|down <version>|status]"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

DEFAULT_DB_PATH = "podcast_bot.db"
DEFAULT_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def ensure_migrations_table(db: aiosqlite.Connection) -> None:
    await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    await db.commit()


async def get_applied_versions(db: aiosqlite.Connection) -> set[int]:
    async with db.execute("SELECT version FROM schema_migrations") as cursor:
        rows = await cursor.fetchall()
    return {row[0] for row in rows}


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
    db_path: str = DEFAULT_DB_PATH,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        applied = await get_applied_versions(db)
        migrations = discover_migrations(migrations_dir)
        pending = [(v, up, down) for v, up, down in migrations if v not in applied]
        if not pending:
            print("Nothing to migrate.")
            return
        for version, up_path, _ in pending:
            print(f"Applying migration {version}: {up_path.name}")
            sql = up_path.read_text()
            await db.executescript(sql)
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
        print(f"Applied {len(pending)} migration(s).")


async def migrate_down(
    db_path: str = DEFAULT_DB_PATH,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    target_version: int = 0,
) -> None:
    async with aiosqlite.connect(db_path) as db:
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
            sql = down_path.read_text()
            await db.executescript(sql)
            await db.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
            await db.commit()
        print(f"Rolled back {len(to_rollback)} migration(s).")


async def status(
    db_path: str = DEFAULT_DB_PATH,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    migrations = discover_migrations(migrations_dir)
    if not migrations:
        print("No migrations found.")
        return
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        applied = await get_applied_versions(db)
    print(f"{'Version':<10} {'Status':<10} {'File'}")
    print("-" * 50)
    for version, up_path, _ in migrations:
        state = "applied" if version in applied else "pending"
        print(f"{version:<10} {state:<10} {up_path.name}")
