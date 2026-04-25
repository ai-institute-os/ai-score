#!/usr/bin/env python3
"""
One-time data migration: encrypt existing plaintext API keys in tenant_provider_configs.

Run this AFTER deploying the code change that adds EncryptedText to the model,
and AFTER setting LLM_ENCRYPTION_KEY in the environment.

Usage:
    LLM_ENCRYPTION_KEY=<your-key> python scripts/migrate_encrypt_api_keys.py

The script is idempotent — rows already encrypted (valid Fernet tokens) are skipped.
"""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def migrate() -> None:
    key = os.environ.get("LLM_ENCRYPTION_KEY", "")
    if not key:
        print("ERROR: LLM_ENCRYPTION_KEY is not set. Aborting.")
        sys.exit(1)

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://aiscore:aiscore_dev@localhost:5432/aiscore",
    )

    fernet = Fernet(key.encode())
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, api_key FROM tenant_provider_configs WHERE api_key IS NOT NULL")
        )
        rows = result.fetchall()

    total = len(rows)
    already_encrypted = 0
    encrypted_now = 0

    async with async_session() as session:
        for row_id, api_key in rows:
            if not api_key:
                continue

            # Check if already a valid Fernet token — skip if so
            try:
                fernet.decrypt(api_key.encode())
                already_encrypted += 1
                continue
            except (InvalidToken, Exception):
                pass

            # Plaintext row — encrypt and update
            encrypted_value = fernet.encrypt(api_key.encode()).decode()
            await session.execute(
                text("UPDATE tenant_provider_configs SET api_key = :enc WHERE id = :id"),
                {"enc": encrypted_value, "id": str(row_id)},
            )
            encrypted_now += 1

        await session.commit()

    await engine.dispose()

    print(f"Migration complete: {total} rows total, {encrypted_now} encrypted, {already_encrypted} already encrypted.")


if __name__ == "__main__":
    asyncio.run(migrate())
