"""
Production AI Agent — Part 6 Final Project.
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Đảm bảo mọi dòng log của app đều là 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logger() -> logging.Logger:
    app_logger = logging.getLogger("production_agent")
    app_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logger()
START_TIME = time.time()
_is_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời startup & graceful shutdown (SIGTERM)."""
    global _is_ready
    _is_ready = True
    logger.info(
        "agent_startup",
        extra={
            "extra_data": {
                "event": "startup",
                "environment": settings.environment,
                "port": settings.port,
            }
        },
    )
    yield
    _is_ready = False
    logger.info("agent_shutdown", extra={"extra_data": {"event": "shutdown_start"}})
    close_redis()
    logger.info("agent_shutdown_done", extra={"extra_data": {"event": "shutdown_complete"}})


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "http_request",
        extra={
            "extra_data": {
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": elapsed_ms,
            }
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Không bao giờ trả stack trace nội bộ ra cho client."""
    logger.error(
        "unhandled_exception",
        extra={
            "extra_data": {
                "event": "error",
                "path": request.url.path,
                "error_type": type(exc).__name__,
            }
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process sống, kể cả khi Redis down."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
    }


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng và kết nối được Redis; ngược lại 503."""
    if not _is_ready or not redis_healthy():
        raise HTTPException(status_code=503, detail="Agent not ready (Redis unavailable)")
    return {"ready": True, "redis": "connected"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Protected endpoint: Auth (401) -> Rate Limit (429) -> Cost Guard (402) -> LLM."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)

    logger.info(
        "ask_completed",
        extra={
            "extra_data": {
                "event": "ask",
                "question_len": len(body.question),
                "answer_len": len(answer),
                "cost_usd": cost_usd,
            }
        },
    )
    return {
        "question": body.question,
        "answer": answer,
        "environment": settings.environment,
    }
