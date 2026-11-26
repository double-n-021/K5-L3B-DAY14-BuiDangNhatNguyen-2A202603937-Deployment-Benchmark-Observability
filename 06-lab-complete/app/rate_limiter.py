"""
Rate limiting (tiêu chí 7) — Sliding Window 60s lưu trên Redis Sorted Set.
State nằm trong Redis nên dùng chung giữa nhiều worker/instance và bền vững sau restart.
"""
import hashlib
import time
import uuid
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _redis_key(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"ratelimit:{digest}"


def check_rate_limit(key: str) -> None:
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = _redis_key(key)
    limit = settings.rate_limit_per_minute

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests per {WINDOW_SECONDS}s).",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except RedisError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiter backend temporarily unavailable.",
        )
