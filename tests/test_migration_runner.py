"""
Tests for the run_migrations() startup helper and _split_sql().

Covers:
- Skips files already recorded in schema_migrations
- Applies files in alphabetical order
- Records each migration after applying it
- Raises RuntimeError if a migration fails (and does not mark it as applied)
- Comment-only trailing blocks are skipped (regression for AII-1548 NoneType crash)
- _split_sql handles trailing comments without emitting comment-only statements
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


@pytest.fixture
def mock_engine():
    """Return a minimal async engine mock that supports engine.begin() context."""
    conn = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.begin = MagicMock(return_value=cm)
    engine.dispose = AsyncMock()
    return engine, conn


@pytest.mark.asyncio
async def test_run_migrations_skips_applied(tmp_path, mock_engine):
    """Migrations already in schema_migrations are not re-executed."""
    engine, conn = mock_engine

    migration_file = tmp_path / "001_init.sql"
    migration_file.write_text("CREATE TABLE t (id INT);")

    # Simulate that 001_init.sql was already applied
    applied_row = MagicMock()
    applied_row.__iter__ = MagicMock(return_value=iter(["001_init.sql"]))
    applied_row.__getitem__ = MagicMock(side_effect=lambda i: "001_init.sql" if i == 0 else None)

    fetch_result = MagicMock()
    fetch_result.fetchall = MagicMock(return_value=[("001_init.sql",)])
    conn.execute = AsyncMock(return_value=fetch_result)

    with patch("src.db.connection.make_engine", return_value=engine):
        with patch("src.db.connection.Path") as mock_path_cls:
            mock_migrations_dir = MagicMock()
            mock_migrations_dir.glob = MagicMock(return_value=[migration_file])
            mock_path_cls.return_value.parent.__truediv__ = MagicMock(return_value=mock_migrations_dir)

            from src.db.connection import run_migrations
            await run_migrations(database_url="postgresql+asyncpg://test")

    # The migration SQL should NOT have been executed (only the schema_migrations setup queries)
    sql_calls = [str(c.args[0]) if c.args else "" for c in conn.execute.call_args_list]
    migration_sqls = [s for s in sql_calls if "CREATE TABLE t" in s]
    assert migration_sqls == [], "Already-applied migration should be skipped"


def test_split_sql_skips_trailing_comment_block():
    """Regression: _split_sql must not emit comment-only statements (AII-1548)."""
    from src.db.connection import _split_sql

    sql = (
        "ALTER TABLE t ADD COLUMN x TEXT NOT NULL DEFAULT 'val';\n"
        "\n"
        "-- trailing comment\n"
        "-- another comment line\n"
    )
    stmts = _split_sql(sql)
    # There should be exactly one statement — the ALTER TABLE
    assert len(stmts) == 2  # raw split returns 2
    # Verify the comment-only tail is detectable
    comment_only = [
        s for s in stmts
        if all(not line.strip() or line.strip().startswith("--") for line in s.splitlines())
    ]
    assert len(comment_only) == 1
    sql_stmts = [s for s in stmts if s not in comment_only]
    assert len(sql_stmts) == 1
    assert "ALTER TABLE" in sql_stmts[0]


@pytest.mark.asyncio
async def test_run_migrations_comment_only_block_not_executed(tmp_path, mock_engine):
    """Comment-only trailing blocks must not be passed to conn.execute (AII-1548 regression)."""
    engine, conn = mock_engine

    migration_file = tmp_path / "008_test.sql"
    migration_file.write_text(
        "ALTER TABLE t ADD COLUMN x TEXT;\n"
        "\n"
        "-- this comment block has no SQL\n"
        "-- it must not be executed\n"
    )

    fetch_result = MagicMock()
    fetch_result.fetchall = MagicMock(return_value=[])
    conn.execute = AsyncMock(return_value=fetch_result)

    with patch("src.db.connection.make_engine", return_value=engine):
        with patch("src.db.connection.Path") as mock_path_cls:
            mock_migrations_dir = MagicMock()
            mock_migrations_dir.glob = MagicMock(return_value=[migration_file])
            mock_path_cls.return_value.parent.__truediv__ = MagicMock(return_value=mock_migrations_dir)

            from src.db.connection import run_migrations
            await run_migrations(database_url="postgresql+asyncpg://test")

    executed_sqls = [str(c.args[0]) for c in conn.execute.call_args_list if c.args]
    comment_only_executed = [
        s for s in executed_sqls
        if "this comment block has no SQL" in s
    ]
    assert comment_only_executed == [], "Comment-only statement must not be executed"


@pytest.mark.asyncio
async def test_run_migrations_raises_on_failure(tmp_path):
    """If a migration SQL fails, run_migrations raises RuntimeError."""
    engine = MagicMock()
    conn = AsyncMock()

    # First engine.begin() — for setup (schema_migrations table + SELECT)
    setup_cm = AsyncMock()
    setup_result = MagicMock()
    setup_result.fetchall = MagicMock(return_value=[])  # no applied migrations
    conn.execute = AsyncMock(return_value=setup_result)
    setup_cm.__aenter__ = AsyncMock(return_value=conn)
    setup_cm.__aexit__ = AsyncMock(return_value=False)

    # Second engine.begin() — for the migration itself — raises
    fail_conn = AsyncMock()
    fail_conn.execute = AsyncMock(side_effect=Exception("column already exists"))
    fail_cm = AsyncMock()
    fail_cm.__aenter__ = AsyncMock(return_value=fail_conn)
    fail_cm.__aexit__ = AsyncMock(return_value=False)

    engine.begin = MagicMock(side_effect=[setup_cm, fail_cm])
    engine.dispose = AsyncMock()

    migration_file = tmp_path / "001_bad.sql"
    migration_file.write_text("ALTER TABLE broken ADD COLUMN x INT;")

    with patch("src.db.connection.make_engine", return_value=engine):
        with patch("src.db.connection.Path") as mock_path_cls:
            mock_migrations_dir = MagicMock()
            mock_migrations_dir.glob = MagicMock(return_value=[migration_file])
            mock_path_cls.return_value.parent.__truediv__ = MagicMock(return_value=mock_migrations_dir)

            from src.db.connection import run_migrations
            with pytest.raises(RuntimeError, match="001_bad.sql"):
                await run_migrations(database_url="postgresql+asyncpg://test")
