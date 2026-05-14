from fastapi import Header, HTTPException, status
from src.config import get_settings


async def require_admin_key(x_admin_key: str = Header(..., description="Admin API key")) -> str:
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: ADMIN_API_KEY environment variable is not set",
        )
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin API key")
    return "admin"
