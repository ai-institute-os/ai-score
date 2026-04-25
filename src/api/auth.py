from fastapi import Header, HTTPException
from src.config import get_settings


async def require_admin_key(x_admin_key: str = Header(..., description="Admin API key")) -> str:
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API key not configured on server")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin API key")
    return "admin"
