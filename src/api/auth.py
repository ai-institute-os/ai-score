import hashlib
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, status

_ADMIN_COOKIE = "aiscore_admin_session"
_ADMIN_PASSWORD = "admin"  # temporary hardcode — replace with env var later


def _verify_admin_cookie(request: Request) -> bool:
    token = request.cookies.get(_ADMIN_COOKIE, "")
    if not token:
        return False
    expected = hmac.new(_ADMIN_PASSWORD.encode(), b"aiscore-admin-v1", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected)


async def require_admin_key(
    request: Request,
    x_admin_key: Optional[str] = Header(None, description="Admin API key"),
) -> str:
    if x_admin_key and x_admin_key == _ADMIN_PASSWORD:
        return "admin"
    if _verify_admin_cookie(request):
        return "admin"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
