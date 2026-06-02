"""Optional API-key authentication.

If `API_KEY` is set, every request must carry a matching `X-API-Key` header.
If it is empty, auth is disabled (intended for local development only).
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings

settings = get_settings()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        return  # auth disabled
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
