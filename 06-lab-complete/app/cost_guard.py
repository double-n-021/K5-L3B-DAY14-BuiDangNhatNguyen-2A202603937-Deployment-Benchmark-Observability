"""
Cost guard (tiêu chí 8) — Theo dõi chi phí LLM trong Redis.
Tổng chi phí >= DAILY_BUDGET_USD -> HTTP 402 Payment Required.
"""
from datetime import datetime, timezone
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
BUDGET_TTL_SECONDS = 48 * 3600


def _budget_key() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{today}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget -> raise HTTP 402."""
    try:
        raw = r.get(_budget_key())
        current_usd = float(raw) if raw is not None else 0.0
    except RedisError:
        raise HTTPException(
            status_code=503,
            detail="Cost guard backend temporarily unavailable.",
        )

    if current_usd >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily LLM budget exceeded",
                "used_usd": round(current_usd, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí vào Redis bằng INCRBYFLOAT."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    key = _budget_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, BUDGET_TTL_SECONDS)
        pipe.execute()
    except RedisError:
        pass
    return round(cost, 8)
