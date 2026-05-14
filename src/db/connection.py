from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from src.config import get_settings
import structlog

log = structlog.get_logger()


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    return create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:
    async with get_session_factory()() as session:
        yield session


async def run_migrations(database_url: str | None = None) -> None:
    """Apply all pending SQL migration files from src/db/migrations/ in alphabetical order.

    Tracks applied migrations in a schema_migrations table so each file runs exactly once.
    Safe to call on every startup — already-applied migrations are skipped.
    """
    migrations_dir = Path(__file__).parent / "migrations"
    engine = make_engine(database_url)

    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    VARCHAR(255) PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        result = await conn.execute(text("SELECT filename FROM schema_migrations"))
        applied = {row[0] for row in result.fetchall()}

    sql_files = sorted(migrations_dir.glob("*.sql"))
    for sql_file in sql_files:
        if sql_file.name in applied:
            log.debug("migration.skipped", filename=sql_file.name)
            continue

        sql_content = sql_file.read_text(encoding="utf-8")
        try:
            async with engine.begin() as conn:
                # asyncpg rejects multi-statement strings — split on semicolons
                import re as _re
                statements = [s.strip() for s in _re.split(r";\s*", sql_content) if s.strip()]
                for stmt in statements:
                    await conn.execute(text(stmt))
                await conn.execute(
                    text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                    {"filename": sql_file.name},
                )
            log.info("migration.applied", filename=sql_file.name)
        except Exception as exc:
            log.error("migration.failed", filename=sql_file.name, error=str(exc))
            raise RuntimeError(f"Migration {sql_file.name} failed: {exc}") from exc

    await engine.dispose()
