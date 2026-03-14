from pathlib import Path

import aiosqlite
import pytest

from migrate import (
    discover_migrations,
    ensure_migrations_table,
    get_applied_versions,
    migrate_down,
    migrate_up,
    status,
)


def write_migration(dir: Path, name: str, sql: str) -> Path:
    p = dir / name
    p.write_text(sql)
    return p


@pytest.fixture
def migrations_dir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    write_migration(d, "001_up.sql", "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY);")
    write_migration(d, "001_down.sql", "DROP TABLE IF EXISTS t1;")
    write_migration(d, "002_up.sql", "CREATE TABLE IF NOT EXISTS t2 (id INTEGER PRIMARY KEY);")
    write_migration(d, "002_down.sql", "DROP TABLE IF EXISTS t2;")
    return d


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


# --- discover_migrations ---


def test_discover_finds_both_sorted(migrations_dir):
    results = discover_migrations(migrations_dir)
    assert len(results) == 2
    assert results[0][0] == 1
    assert results[1][0] == 2


def test_discover_ignores_non_sql(migrations_dir):
    (migrations_dir / "README.txt").write_text("ignore me")
    (migrations_dir / "003_down.sql").write_text("DROP TABLE IF EXISTS t3;")
    results = discover_migrations(migrations_dir)
    assert len(results) == 2  # 003_down without matching _up is ignored


def test_discover_missing_down_is_none(migrations_dir):
    (migrations_dir / "003_up.sql").write_text("CREATE TABLE IF NOT EXISTS t3 (id INTEGER);")
    results = discover_migrations(migrations_dir)
    v3 = next(r for r in results if r[0] == 3)
    assert v3[2] is None


def test_discover_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_migrations(empty) == []


def test_discover_nonexistent_dir(tmp_path):
    assert discover_migrations(tmp_path / "nonexistent") == []


def test_discover_normalizes_version(migrations_dir):
    results = discover_migrations(migrations_dir)
    assert all(isinstance(r[0], int) for r in results)


# --- ensure_migrations_table ---


@pytest.mark.asyncio
async def test_ensure_migrations_table_creates(db_path):
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_ensure_migrations_table_idempotent(db_path):
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        await ensure_migrations_table(db)  # should not raise


# --- get_applied_versions ---


@pytest.mark.asyncio
async def test_get_applied_versions_empty(db_path):
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        versions = await get_applied_versions(db)
    assert versions == set()


@pytest.mark.asyncio
async def test_get_applied_versions_returns_inserted(db_path):
    async with aiosqlite.connect(db_path) as db:
        await ensure_migrations_table(db)
        await db.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (1, "2026-01-01T00:00:00+00:00"),
        )
        await db.commit()
        versions = await get_applied_versions(db)
    assert versions == {1}


# --- migrate_up ---


@pytest.mark.asyncio
async def test_migrate_up_applies_all(db_path, migrations_dir):
    await migrate_up(db_path, migrations_dir)
    async with aiosqlite.connect(db_path) as db:
        versions = await get_applied_versions(db)
    assert versions == {1, 2}


@pytest.mark.asyncio
async def test_migrate_up_idempotent(db_path, migrations_dir):
    await migrate_up(db_path, migrations_dir)
    await migrate_up(db_path, migrations_dir)  # should not raise or double-apply
    async with aiosqlite.connect(db_path) as db:
        versions = await get_applied_versions(db)
    assert versions == {1, 2}


@pytest.mark.asyncio
async def test_migrate_up_skips_applied(db_path, migrations_dir, capsys):
    await migrate_up(db_path, migrations_dir)
    await migrate_up(db_path, migrations_dir)
    captured = capsys.readouterr()
    assert "Nothing to migrate" in captured.out


@pytest.mark.asyncio
async def test_migrate_up_nothing_to_migrate_empty(db_path, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    await migrate_up(db_path, empty)
    captured = capsys.readouterr()
    assert "Nothing to migrate" in captured.out


# --- migrate_down ---


@pytest.mark.asyncio
async def test_migrate_down_rollback_to_zero(db_path, migrations_dir):
    await migrate_up(db_path, migrations_dir)
    await migrate_down(db_path, migrations_dir, target_version=0)
    async with aiosqlite.connect(db_path) as db:
        versions = await get_applied_versions(db)
    assert versions == set()


@pytest.mark.asyncio
async def test_migrate_down_rollback_to_version_1(db_path, migrations_dir):
    await migrate_up(db_path, migrations_dir)
    await migrate_down(db_path, migrations_dir, target_version=1)
    async with aiosqlite.connect(db_path) as db:
        versions = await get_applied_versions(db)
    assert versions == {1}


@pytest.mark.asyncio
async def test_migrate_down_nothing_to_rollback(db_path, migrations_dir, capsys):
    await migrate_up(db_path, migrations_dir)
    await migrate_down(db_path, migrations_dir, target_version=2)
    captured = capsys.readouterr()
    assert "Nothing to rollback" in captured.out


@pytest.mark.asyncio
async def test_migrate_down_missing_down_exits(db_path, tmp_path):
    d = tmp_path / "migs"
    d.mkdir()
    write_migration(d, "001_up.sql", "CREATE TABLE IF NOT EXISTS t1 (id INTEGER);")
    # No 001_down.sql
    await migrate_up(db_path, d)
    with pytest.raises(SystemExit) as exc_info:
        await migrate_down(db_path, d, target_version=0)
    assert exc_info.value.code == 1


# --- status ---


@pytest.mark.asyncio
async def test_status_shows_pending(db_path, migrations_dir, capsys):
    await status(db_path, migrations_dir)
    captured = capsys.readouterr()
    assert "pending" in captured.out


@pytest.mark.asyncio
async def test_status_shows_applied(db_path, migrations_dir, capsys):
    await migrate_up(db_path, migrations_dir)
    await status(db_path, migrations_dir)
    captured = capsys.readouterr()
    assert "applied" in captured.out


@pytest.mark.asyncio
async def test_status_no_migrations(db_path, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    await status(db_path, empty)
    captured = capsys.readouterr()
    assert "No migrations found" in captured.out


# --- Round-trip ---


@pytest.mark.asyncio
async def test_round_trip_up_down_up(db_path, migrations_dir):
    await migrate_up(db_path, migrations_dir)
    async with aiosqlite.connect(db_path) as db:
        v1 = await get_applied_versions(db)
    assert v1 == {1, 2}

    await migrate_down(db_path, migrations_dir, target_version=0)
    async with aiosqlite.connect(db_path) as db:
        v2 = await get_applied_versions(db)
    assert v2 == set()

    await migrate_up(db_path, migrations_dir)
    async with aiosqlite.connect(db_path) as db:
        v3 = await get_applied_versions(db)
    assert v3 == {1, 2}
