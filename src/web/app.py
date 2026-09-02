import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

logger = logging.getLogger("OmniBot.web")

_start_time: float = 0.0

_STATUS_API_TOKEN = os.getenv("STATUS_API_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()
    logger.info("Health check server started on :8080")
    yield
    logger.info("Health check server stopped")


app = FastAPI(title="OmniBot", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "omnibot"}


@app.get("/api/status")
async def status(x_api_token: str | None = Header(default=None)):
    if not _STATUS_API_TOKEN or x_api_token != _STATUS_API_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")

    from ..bot import bot

    uptime_seconds = int(time.time() - _start_time) if _start_time else 0
    return {
        "status": "ok",
        "uptime_seconds": uptime_seconds,
        "guilds": len(bot.guilds) if bot.is_ready() else 0,
        "latency_ms": int(bot.latency * 1000) if bot.is_ready() else -1,
        "lavalink_connected": bot._lavalink_ready,
        "user": str(bot.user) if bot.is_ready() else "starting",
    }
