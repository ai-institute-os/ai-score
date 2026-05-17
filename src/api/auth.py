import hashlib
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from src.config import get_settings

_ADMIN_COOKIE = "aiscore_admin_session"


def _verify_admin_cookie(request: Request, admin_api_key: str) -> bool:
    token = request.cookies.get(_ADMIN_COOKIE, "")
    if not token or not admin_api_key:
        return False
    expected = hmac.new(admin_api_key.encode(), b"aiscore-admin-v1", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected)


async def require_admin_key(
    request: Request,
    x_admin_key: Optional[str] = Header(None, description="Admin API key"),
) -> str:
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: ADMIN_API_KEY environment variable is not set",
        )
    if x_admin_key and x_admin_key == settings.admin_api_key:
        return "admin"
    if _verify_admin_cookie(request, settings.admin_api_key):
        return "admin"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
