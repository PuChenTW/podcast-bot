from pathlib import Path

import asyncpg
import pytest
from pytest_mock_resources import create_postgres_fixture

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


# Function-scoped fixture so each migrate test gets a fresh, empty DB.
# The session-scoped _postgres in conftest.py already has real migrations applied,
# so migrate tests need their own isolated DB to test migration logic cleanly.
_migrate_postgres = create_postgres_fixture()


@pytest.fixture
def db_url(_migrate_postgres):
    creds = _migrate_postgres.pmr_credentials
    return f"postgresql://{creds.username}:{creds.password}@{creds.host}:{creds.port}/{creds.database}"


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
async def test_ensure_migrations_table_creates(db_url):
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        row = await db.fetchrow("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='schema_migrations'")
        assert row is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ensure_migrations_table_idempotent(db_url):
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        await ensure_migrations_table(db)  # should not raise
    finally:
        await db.close()


# --- get_applied_versions ---


@pytest.mark.asyncio
async def test_get_applied_versions_empty(db_url):
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == set()


@pytest.mark.asyncio
async def test_get_applied_versions_returns_inserted(db_url):
    db = await asyncpg.connect(db_url)
    try:
        await ensure_migrations_table(db)
        await db.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES ($1, $2)",
            1,
            "2026-01-01T00:00:00+00:00",
        )
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == {1}


# --- migrate_up ---


@pytest.mark.asyncio
async def test_migrate_up_applies_all(db_url, migrations_dir):
    await migrate_up(db_url, migrations_dir)
    db = await asyncpg.connect(db_url)
    try:
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == {1, 2}


@pytest.mark.asyncio
async def test_migrate_up_idempotent(db_url, migrations_dir):
    await migrate_up(db_url, migrations_dir)
    await migrate_up(db_url, migrations_dir)  # should not raise or double-apply
    db = await asyncpg.connect(db_url)
    try:
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == {1, 2}


@pytest.mark.asyncio
async def test_migrate_up_skips_applied(db_url, migrations_dir, capsys):
    await migrate_up(db_url, migrations_dir)
    await migrate_up(db_url, migrations_dir)
    captured = capsys.readouterr()
    assert "Nothing to migrate" in captured.out


@pytest.mark.asyncio
async def test_migrate_up_nothing_to_migrate_empty(db_url, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    await migrate_up(db_url, empty)
    captured = capsys.readouterr()
    assert "Nothing to migrate" in captured.out


# --- migrate_down ---


@pytest.mark.asyncio
async def test_migrate_down_rollback_to_zero(db_url, migrations_dir):
    await migrate_up(db_url, migrations_dir)
    await migrate_down(db_url, migrations_dir, target_version=0)
    db = await asyncpg.connect(db_url)
    try:
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == set()


@pytest.mark.asyncio
async def test_migrate_down_rollback_to_version_1(db_url, migrations_dir):
    await migrate_up(db_url, migrations_dir)
    await migrate_down(db_url, migrations_dir, target_version=1)
    db = await asyncpg.connect(db_url)
    try:
        versions = await get_applied_versions(db)
    finally:
        await db.close()
    assert versions == {1}


@pytest.mark.asyncio
async def test_migrate_down_nothing_to_rollback(db_url, migrations_dir, capsys):
    await migrate_up(db_url, migrations_dir)
    await migrate_down(db_url, migrations_dir, target_version=2)
    captured = capsys.readouterr()
    assert "Nothing to rollback" in captured.out


@pytest.mark.asyncio
async def test_migrate_down_missing_down_exits(db_url, tmp_path):
    d = tmp_path / "migs"
    d.mkdir()
    write_migration(d, "001_up.sql", "CREATE TABLE IF NOT EXISTS t1 (id INTEGER);")
    # No 001_down.sql
    await migrate_up(db_url, d)
    with pytest.raises(SystemExit) as exc_info:
        await migrate_down(db_url, d, target_version=0)
    assert exc_info.value.code == 1


# --- status ---


@pytest.mark.asyncio
async def test_status_shows_pending(db_url, migrations_dir, capsys):
    await status(db_url, migrations_dir)
    captured = capsys.readouterr()
    assert "pending" in captured.out


@pytest.mark.asyncio
async def test_status_shows_applied(db_url, migrations_dir, capsys):
    await migrate_up(db_url, migrations_dir)
    await status(db_url, migrations_dir)
    captured = capsys.readouterr()
    assert "applied" in captured.out


@pytest.mark.asyncio
async def test_status_no_migrations(db_url, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    await status(db_url, empty)
    captured = capsys.readouterr()
    assert "No migrations found" in captured.out


# --- Round-trip ---


@pytest.mark.asyncio
async def test_round_trip_up_down_up(db_url, migrations_dir):
    await migrate_up(db_url, migrations_dir)
    db = await asyncpg.connect(db_url)
    try:
        v1 = await get_applied_versions(db)
    finally:
        await db.close()
    assert v1 == {1, 2}

    await migrate_down(db_url, migrations_dir, target_version=0)
    db = await asyncpg.connect(db_url)
    try:
        v2 = await get_applied_versions(db)
    finally:
        await db.close()
    assert v2 == set()

    await migrate_up(db_url, migrations_dir)
    db = await asyncpg.connect(db_url)
    try:
        v3 = await get_applied_versions(db)
    finally:
        await db.close()
    assert v3 == {1, 2}
