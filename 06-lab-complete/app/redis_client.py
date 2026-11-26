"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
KHÔNG ping Redis lúc import để app vẫn khởi động được khi Redis chưa sẵn sàng.
"""
import redis
from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho endpoint /ready."""
    try:
        return bool(r.ping())
    except Exception:
        return False


def close_redis() -> None:
    """Đóng connection pool khi graceful shutdown."""
    try:
        r.close()
    except Exception:
        pass
