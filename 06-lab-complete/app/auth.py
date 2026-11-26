"""
API Key authentication (tiêu chí 6).
Header X-API-Key phải trùng AGENT_API_KEY; thiếu hoặc sai -> HTTP 401.
"""
import hmac
from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency kiểm tra X-API-Key dùng so sánh constant-time."""
    expected = settings.agent_api_key
    if not api_key or not expected or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide header: X-API-Key",
        )
    return api_key
