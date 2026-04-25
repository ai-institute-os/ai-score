"""
Unit tests for the AISelect password reset flow.

Tests cover:
- Token hashing (deterministic SHA-256)
- Password hashing and verification (PBKDF2)
- forgot_password endpoint: always 200, email sent only for known accounts
- reset_password endpoint: accepts valid token, rejects expired/used/unknown tokens
"""

import hashlib
import secrets
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub out optional runtime-only packages that are unavailable in the test env
def _stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

for _mod_name in ("aiosmtplib", "stripe"):
    if _mod_name not in sys.modules:
        _stub(_mod_name)

# slowapi stub — linter may add rate limiting imports to apply_routes.
# The Limiter's limit() decorator must be a passthrough so async funcs stay awaitable.
class _PassthroughLimiter:
    def limit(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

if "slowapi" not in sys.modules:
    _sl = _stub("slowapi")
    _sl_util = _stub("slowapi.util")
    _sl_util.get_remote_address = lambda: "127.0.0.1"  # type: ignore[attr-defined]
    _sl.Limiter = lambda **kw: _PassthroughLimiter()  # type: ignore[attr-defined]

from src.api.apply_routes import (
    _hash_token,
    _hash_password,
    _verify_password,
)


# ─────────────────────────────────────────────
# Utility function unit tests (no DB required)
# ─────────────────────────────────────────────

def test_hash_token_is_sha256():
    raw = "my-test-token"
    result = _hash_token(raw)
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert result == expected


def test_hash_token_deterministic():
    raw = secrets.token_urlsafe(32)
    assert _hash_token(raw) == _hash_token(raw)


def test_hash_password_roundtrip():
    pw = "supersecret99"
    stored = _hash_password(pw)
    assert ":" in stored
    assert _verify_password(pw, stored) is True


def test_verify_password_wrong_password():
    stored = _hash_password("correct-horse")
    assert _verify_password("wrong-horse", stored) is False


def test_verify_password_invalid_stored_format():
    assert _verify_password("any", "notvalidformat") is False


def test_hash_password_produces_unique_salts():
    pw = "samepassword"
    h1 = _hash_password(pw)
    h2 = _hash_password(pw)
    # Different salts mean different stored hashes
    assert h1 != h2
    # But both verify correctly
    assert _verify_password(pw, h1)
    assert _verify_password(pw, h2)


# ─────────────────────────────────────────────
# Endpoint integration tests (mock DB)
# ─────────────────────────────────────────────

def _make_request() -> MagicMock:
    """Return a minimal mock satisfying FastAPI's Request type."""
    return MagicMock()


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_200():
    """Unknown email must return 200 (no enumeration)."""
    from src.api.apply_routes import forgot_password
    from src.api.schemas import ForgotPasswordRequest

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    body = ForgotPasswordRequest(email="unknown@example.com")
    # Pass request as first positional arg (added by linter for rate-limit support)
    response = await forgot_password(_make_request(), body, db=mock_db)
    assert "nulstillingslink" in response.message.lower()


@pytest.mark.asyncio
async def test_forgot_password_known_email_sends_email():
    """Known email generates a token and attempts to send email."""
    from src.api.apply_routes import forgot_password
    from src.api.schemas import ForgotPasswordRequest
    from src.db.models import AISelectSubscription, SubscriptionTier, SubscriptionStatus

    sub = AISelectSubscription(
        customer_email="known@example.com",
        company_name="TestCo",
        tier=SubscriptionTier.STARTER,
        status=SubscriptionStatus.ACTIVE,
    )

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sub
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    body = ForgotPasswordRequest(email="known@example.com")

    mock_send = AsyncMock()
    fake_emailer = types.ModuleType("src.payments.emailer")
    fake_emailer.send_password_reset_email = mock_send  # type: ignore[attr-defined]
    fake_emailer.send_payment_link_email = AsyncMock()  # type: ignore[attr-defined]
    fake_emailer.send_email = AsyncMock()  # type: ignore[attr-defined]
    fake_stripe_client = types.ModuleType("src.payments.stripe_client")
    fake_stripe_client.create_checkout_session = AsyncMock()  # type: ignore[attr-defined]
    fake_stripe_client.construct_stripe_event = MagicMock()  # type: ignore[attr-defined]
    fake_payments = types.ModuleType("src.payments")
    fake_payments.send_email = AsyncMock()  # type: ignore[attr-defined]
    fake_payments.send_payment_link_email = AsyncMock()  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {
        "src.payments": fake_payments,
        "src.payments.emailer": fake_emailer,
        "src.payments.stripe_client": fake_stripe_client,
    }):
        response = await forgot_password(_make_request(), body, db=mock_db)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args
    assert call_kwargs.kwargs["customer_email"] == "known@example.com"
    assert "token=" in call_kwargs.kwargs["reset_url"]
    assert "nulstillingslink" in response.message.lower()


@pytest.mark.asyncio
async def test_forgot_password_invalidates_existing_tokens():
    """Second reset request must invalidate previous active tokens (used_at set)."""
    from src.api.apply_routes import forgot_password
    from src.api.schemas import ForgotPasswordRequest
    from src.db.models import AISelectSubscription, SubscriptionTier, SubscriptionStatus
    from sqlalchemy import update as sa_update
    from src.db.models import PasswordResetToken

    sub = AISelectSubscription(
        customer_email="user@example.com",
        company_name="TestCo",
        tier=SubscriptionTier.STARTER,
        status=SubscriptionStatus.ACTIVE,
    )

    invalidation_call_args = []

    mock_db = AsyncMock()
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub
    update_result = MagicMock()

    async def capture_execute(stmt, *args, **kwargs):
        invalidation_call_args.append(stmt)
        return sub_result

    mock_db.execute = AsyncMock(side_effect=capture_execute)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    body = ForgotPasswordRequest(email="user@example.com")

    mock_send = AsyncMock()
    fake_emailer = types.ModuleType("src.payments.emailer")
    fake_emailer.send_password_reset_email = mock_send  # type: ignore[attr-defined]
    fake_emailer.send_payment_link_email = AsyncMock()  # type: ignore[attr-defined]
    fake_emailer.send_email = AsyncMock()  # type: ignore[attr-defined]
    fake_stripe_client = types.ModuleType("src.payments.stripe_client")
    fake_stripe_client.create_checkout_session = AsyncMock()  # type: ignore[attr-defined]
    fake_stripe_client.construct_stripe_event = MagicMock()  # type: ignore[attr-defined]
    fake_payments = types.ModuleType("src.payments")
    fake_payments.send_email = AsyncMock()  # type: ignore[attr-defined]
    fake_payments.send_payment_link_email = AsyncMock()  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {
        "src.payments": fake_payments,
        "src.payments.emailer": fake_emailer,
        "src.payments.stripe_client": fake_stripe_client,
    }):
        await forgot_password(_make_request(), body, db=mock_db)

    # execute should be called twice: once for the SELECT, once for the UPDATE
    assert mock_db.execute.call_count == 2, (
        f"Expected 2 execute calls (SELECT + UPDATE), got {mock_db.execute.call_count}"
    )
    # Second call must be the UPDATE invalidation
    update_stmt = invalidation_call_args[1]
    compiled = str(update_stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "password_reset_token" in compiled.lower() or "UPDATE" in str(update_stmt.__class__.__name__).upper()


@pytest.mark.asyncio
async def test_reset_password_invalid_token_raises_400():
    """An invalid or expired token should raise HTTP 400."""
    from fastapi import HTTPException
    from src.api.apply_routes import reset_password
    from src.api.schemas import ResetPasswordRequest

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    body = ResetPasswordRequest(token="bad-token", new_password="newpassword123")

    with pytest.raises(HTTPException) as exc_info:
        await reset_password(_make_request(), body, db=mock_db)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_valid_token_updates_hash():
    """A valid token should update password_hash and mark token used."""
    from src.api.apply_routes import reset_password
    from src.api.schemas import ResetPasswordRequest
    from src.db.models import (
        PasswordResetToken, AISelectSubscription,
        SubscriptionTier, SubscriptionStatus,
    )

    email = "user@example.com"
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    token_row = PasswordResetToken(
        email=email,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    sub = AISelectSubscription(
        customer_email=email,
        company_name="TestCo",
        tier=SubscriptionTier.STARTER,
        status=SubscriptionStatus.ACTIVE,
    )

    mock_db = AsyncMock()
    token_result = MagicMock()
    token_result.scalar_one_or_none.return_value = token_row
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub
    mock_db.execute = AsyncMock(side_effect=[token_result, sub_result])
    mock_db.commit = AsyncMock()

    body = ResetPasswordRequest(token=raw_token, new_password="newpassword123")
    response = await reset_password(_make_request(), body, db=mock_db)

    assert sub.password_hash is not None
    assert _verify_password("newpassword123", sub.password_hash)
    assert token_row.used_at is not None
    assert "opdateret" in response.message.lower()
