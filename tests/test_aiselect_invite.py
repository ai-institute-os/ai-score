"""
Unit tests for _call_aiselect_invite — the AIScore→AISelect invite HTTP call.

Tests cover:
- Skips the call when aiselect_admin_secret is not configured
- POSTs the correct payload and headers on success (HTTP 200)
- Logs an error but does not raise on non-200 response
- Logs an error but does not raise on network exception
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub out optional runtime-only packages ────────────────────────────────────

def _stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

for _mod_name in ("aiosmtplib", "stripe"):
    if _mod_name not in sys.modules:
        _stub(_mod_name)

class _PassthroughLimiter:
    def limit(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

if "slowapi" not in sys.modules:
    _sl = _stub("slowapi")
    _sl_util = _stub("slowapi.util")
    _sl_util.get_remote_address = lambda: "127.0.0.1"  # type: ignore
    _sl.Limiter = lambda **kw: _PassthroughLimiter()  # type: ignore

# ── Import after stubs ─────────────────────────────────────────────────────────

from src.api.apply_routes import _call_aiselect_invite


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(admin_secret: str = "test-secret", base_url: str = "https://aiselect.dk"):
    s = MagicMock()
    s.aiselect_admin_secret = admin_secret
    s.aiselect_base_url = base_url
    return s


def _http_response(status_code: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


def _make_mock_client(resp_or_exc):
    """Return an httpx.AsyncClient mock that returns resp_or_exc on .post()."""
    mock_inst = AsyncMock()
    if isinstance(resp_or_exc, Exception):
        mock_inst.post = AsyncMock(side_effect=resp_or_exc)
    else:
        mock_inst.post = AsyncMock(return_value=resp_or_exc)
    mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
    mock_inst.__aexit__ = AsyncMock(return_value=False)
    return mock_inst


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_when_no_admin_secret():
    """No HTTP call is made if aiselect_admin_secret is empty."""
    settings = _make_settings(admin_secret="")
    with patch("src.config.get_settings", return_value=settings):
        with patch("httpx.AsyncClient") as mock_client_cls:
            await _call_aiselect_invite("a@b.com", "Alice", "Acme", "app-1")
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_posts_correct_payload_on_success():
    """On 200, sends correct JSON body and x-admin-secret header."""
    settings = _make_settings(admin_secret="s3cr3t", base_url="https://aiselect.dk")
    mock_inst = _make_mock_client(_http_response(200))

    with patch("src.config.get_settings", return_value=settings):
        with patch("httpx.AsyncClient", return_value=mock_inst):
            await _call_aiselect_invite("bob@example.com", "Bob", "BobCorp", "app-42")

    mock_inst.post.assert_called_once_with(
        "https://aiselect.dk/api/invite",
        json={
            "contactEmail": "bob@example.com",
            "contactName": "Bob",
            "companyName": "BobCorp",
            "planId": "starter",
        },
        headers={"x-admin-secret": "s3cr3t"},
    )


@pytest.mark.asyncio
async def test_strips_trailing_slash_from_base_url():
    """Base URL trailing slash does not produce a double-slash in the invite URL."""
    settings = _make_settings(admin_secret="s3cr3t", base_url="https://aiselect.dk/")
    mock_inst = _make_mock_client(_http_response(200))

    with patch("src.config.get_settings", return_value=settings):
        with patch("httpx.AsyncClient", return_value=mock_inst):
            await _call_aiselect_invite("c@d.com", "Carol", "CarolCo", "app-99")

    url_called = mock_inst.post.call_args[0][0]
    assert url_called == "https://aiselect.dk/api/invite"


@pytest.mark.asyncio
async def test_does_not_raise_on_non_200():
    """Non-200 response is logged but never raises."""
    settings = _make_settings(admin_secret="s3cr3t")
    mock_inst = _make_mock_client(_http_response(401, "Unauthorized"))

    with patch("src.config.get_settings", return_value=settings):
        with patch("httpx.AsyncClient", return_value=mock_inst):
            await _call_aiselect_invite("x@y.com", "X", "XCorp", "app-err")


@pytest.mark.asyncio
async def test_does_not_raise_on_network_error():
    """Network exception is logged but never raised."""
    settings = _make_settings(admin_secret="s3cr3t")
    mock_inst = _make_mock_client(Exception("connection refused"))

    with patch("src.config.get_settings", return_value=settings):
        with patch("httpx.AsyncClient", return_value=mock_inst):
            await _call_aiselect_invite("z@w.com", "Z", "ZCorp", "app-net")
