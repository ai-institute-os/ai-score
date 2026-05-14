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
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
    return create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_timeout=10,
        connect_args={"timeout": 10},
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


def _split_sql(sql: str) -> list[str]:
    """Split a SQL script into individual statements at top-level semicolons.

    Handles dollar-quoted blocks (DO $$ ... $$; and $tag$...$tag$) and
    single-quoted string literals so internal semicolons are never treated
    as statement boundaries.
    """
    import re as _re
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    dollar_tag: str | None = None  # non-None while inside $tag$...$tag$
    in_single_quote = False

    while i < n:
        c = sql[i]

        if dollar_tag is not None:
            closing = f"${dollar_tag}$"
            if sql[i:i + len(closing)] == closing:
                buf.append(closing)
                i += len(closing)
                dollar_tag = None
            else:
                buf.append(c)
                i += 1

        elif in_single_quote:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 2
                else:
                    in_single_quote = False
                    i += 1
            else:
                i += 1

        elif c == "'":
            in_single_quote = True
            buf.append(c)
            i += 1

        elif c == "$":
            m = _re.match(r"\$([A-Za-z_0-9]*)\$", sql[i:])
            if m:
                tag = m.group(1)
                dollar_tag = tag
                buf.append(m.group(0))
                i += len(m.group(0))
            else:
                buf.append(c)
                i += 1

        elif c == "-" and i + 1 < n and sql[i + 1] == "-":
            # Line comment — copy through but don't treat ';' inside as boundary
            while i < n and sql[i] != "\n":
                buf.append(sql[i])
                i += 1

        elif c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1

        else:
            buf.append(c)
            i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


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
    try:
        for sql_file in sql_files:
            if sql_file.name in applied:
                log.debug("migration.skipped", filename=sql_file.name)
                continue

            sql_content = sql_file.read_text(encoding="utf-8")
            try:
                async with engine.begin() as conn:
                    # asyncpg rejects multi-statement strings — split on top-level semicolons
                    # (respects dollar-quoted blocks like DO $$ ... $$; and $tag$...$tag$)
                    statements = _split_sql(sql_content)
                    for stmt in statements:
                        if not stmt:
                            continue
                        # Skip comment-only blocks — asyncpg rejects queries with no SQL command
                        if all(
                            not line.strip() or line.strip().startswith("--")
                            for line in stmt.splitlines()
                        ):
                            continue
                        await conn.execute(text(stmt))
                    await conn.execute(
                        text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                        {"filename": sql_file.name},
                    )
                log.info("migration.applied", filename=sql_file.name)
            except Exception as exc:
                log.error("migration.failed", filename=sql_file.name, error=str(exc))
                raise RuntimeError(f"Migration {sql_file.name} failed: {exc}") from exc
    finally:
        await engine.dispose()
