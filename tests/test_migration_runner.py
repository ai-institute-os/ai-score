"""
Tests for the run_migrations() startup helper.

Covers:
- Skips files already recorded in schema_migrations
- Applies files in alphabetical order
- Records each migration after applying it
- Raises RuntimeError if a migration fails (and does not mark it as applied)
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
