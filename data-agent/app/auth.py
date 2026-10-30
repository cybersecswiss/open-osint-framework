"""
X-Framework-Key header check. Constant-time comparison to avoid
timing-side-channel leaks of the secret length / first matching bytes.
"""
import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_framework_key(x_framework_key: str = Header(..., alias="X-Framework-Key")):
    if not secrets.compare_digest(x_framework_key, settings.framework_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid framework key",
        )
    return True
