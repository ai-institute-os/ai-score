"""Run pending SQL migrations at startup.

Tracks applied migrations in a `schema_migrations` table (created on first run).
Migrations are SQL files in src/db/migrations/, applied in lexicographic order.
Each file is applied exactly once — idempotent due to IF NOT EXISTS guards in the SQL.
"""

import re
from pathlib import Path
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def run_migrations(engine: AsyncEngine) -> None:
    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        log.warning("migrations.none_found", dir=str(_MIGRATIONS_DIR))
        return

    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_TRACKING_TABLE))

        result = await conn.execute(text("SELECT filename FROM schema_migrations"))
        applied = {row[0] for row in result.fetchall()}

    for path in migration_files:
        name = path.name
        if name in applied:
            continue

        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            continue

        log.info("migration.applying", filename=name)
        async with engine.begin() as conn:
            # Split on semicolons so multi-statement files work correctly.
            # Filter out empty statements (e.g. trailing semicolons).
            statements = [s.strip() for s in re.split(r";\s*", sql) if s.strip()]
            for stmt in statements:
                await conn.execute(text(stmt))
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f) ON CONFLICT DO NOTHING"),
                {"f": name},
            )
        log.info("migration.applied", filename=name)

    log.info("migrations.done", total=len(migration_files), applied_count=len(migration_files) - len(applied))
