from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.resource_router import build_router_status
from app.ai.model_runtime import (
    generate_ollama,
    generate_openclaw,
    ollama_running,
    openclaw_running,
    recent_benchmark,
)
from app.ai.news_summary import summarize_news
from app.ai.rss_fetcher import RssFetchError, fetch_rss_items
from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/model", tags=["model"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    backend: str = "ollama"
    max_tokens: int = Field(256, ge=16, le=1024)
    timeout: int = Field(default_factory=lambda: settings.model_speed_target_seconds, ge=5, le=300)


class NewsItemIn(BaseModel):
    title: str
    link: str = ""
    source: str = ""
    timestamp: int = 0


class NewsSummaryRequest(BaseModel):
    title: str = "News Summary"
    mode: str = "auto"
    model: str = ""
    feed_url: str = ""
    limit: int = Field(5, ge=1, le=20)
    items: list[NewsItemIn] = Field(default_factory=list)
    timeout: int = Field(default_factory=lambda: settings.news_summary_timeout_seconds, ge=5, le=600)


@router.get("/status")
def model_status():
    return {
        "ollama": {
            "running": ollama_running(),
            "configured": settings.enable_ollama,
            "model": settings.ollama_model,
            "num_ctx": settings.ollama_num_ctx,
            "keep_alive": settings.ollama_keep_alive,
        },
        "openclaw": {
            "running": openclaw_running(),
            "configured": settings.enable_openclaw,
            "gateway_url": settings.openclaw_gateway_url,
        },
        "speed_target_seconds": settings.model_speed_target_seconds,
        "news_summary": {
            "model": settings.news_summary_model,
            "timeout_seconds": settings.news_summary_timeout_seconds,
            "max_tokens": settings.news_summary_max_tokens,
        },
        "candidate_models": [
            item.strip()
            for item in settings.ollama_candidate_models.split(",")
            if item.strip()
        ],
        "recent_benchmark": _public_benchmark(recent_benchmark()),
        "router": build_router_status(),
        "commands": {
            "start_ollama": "cd /home/pi3/edge-task-hub && scripts/edge_services.sh start ollama",
            "stop_ollama": "cd /home/pi3/edge-task-hub && scripts/edge_services.sh stop ollama",
            "start_openclaw": "cd /home/pi3/edge-task-hub && scripts/edge_services.sh start openclaw",
            "stop_openclaw": "cd /home/pi3/edge-task-hub && scripts/edge_services.sh stop openclaw",
        },
    }


def _public_benchmark(record: dict | None) -> dict | None:
    if not record:
        return None
    return {
        "timestamp": record.get("timestamp"),
        "backend": record.get("backend"),
        "model": record.get("model"),
        "task": record.get("task") or record.get("prompt_kind"),
        "ok": record.get("ok"),
        "elapsed_seconds": record.get("wall_seconds") or record.get("elapsed_seconds"),
        "tokens_per_second": record.get("eval_tokens_per_second") or record.get("tokens_per_second"),
    }


@router.post("/chat")
def model_chat(body: ChatRequest):
    backend = body.backend.strip().lower()
    if backend == "ollama":
        result = generate_ollama(
            body.message,
            max_tokens=body.max_tokens,
            timeout=body.timeout,
        )
    elif backend == "openclaw":
        result = generate_openclaw(body.message, timeout=body.timeout)
    else:
        raise HTTPException(status_code=400, detail="backend must be ollama or openclaw")
    return result.as_dict()


@router.get("/router-status")
def model_router_status(db: Session = Depends(get_db)):
    return build_router_status(db)


@router.post("/news-summary")
def model_news_summary(body: NewsSummaryRequest):
    items = [item.model_dump() for item in body.items]
    feed_meta = None
    if body.feed_url:
        try:
            feed = fetch_rss_items(body.feed_url, limit=body.limit)
        except RssFetchError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse feed: {exc}") from exc
        items.extend(feed.items)
        feed_meta = feed
    result = summarize_news(
        items[: body.limit],
        title=body.title,
        mode=body.mode,
        model=body.model.strip() or None,
        max_items=body.limit,
        timeout=body.timeout,
    )
    if feed_meta:
        result["feed_fallback"] = feed_meta.feed_fallback
        result["feed_error"] = feed_meta.feed_error
    return result
