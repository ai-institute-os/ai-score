"""
Fernet-based field-level encryption for sensitive database columns.

Requires LLM_ENCRYPTION_KEY env var — a URL-safe base64-encoded 32-byte key.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If LLM_ENCRYPTION_KEY is not set, values are stored/read as plaintext (no-op).
This allows development without the key but is NOT safe for production.
"""

import os
from typing import Optional

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

log = structlog.get_logger()


def _get_fernet() -> Optional[Fernet]:
    key = os.environ.get("LLM_ENCRYPTION_KEY", "")
    if not key:
        log.warning("crypto.no_encryption_key", msg="LLM_ENCRYPTION_KEY not set — API keys stored in plaintext")
        return None
    return Fernet(key.encode())


class EncryptedText(TypeDecorator):
    """SQLAlchemy TypeDecorator that transparently Fernet-encrypts a TEXT column.

    Gracefully handles existing plaintext rows (InvalidToken → returns raw value)
    so deployments can migrate existing data without downtime.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        """Encrypt on write."""
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return value
        return fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        """Decrypt on read. Falls back to plaintext for pre-migration rows."""
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return value
        try:
            return fernet.decrypt(value.encode()).decode()
        except (InvalidToken, Exception):
            # Pre-migration plaintext row — return as-is; will be encrypted on next write
            log.warning("crypto.plaintext_fallback", msg="Could not decrypt value, treating as plaintext")
            return value
