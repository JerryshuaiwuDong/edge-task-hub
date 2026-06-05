from datetime import datetime, timedelta

import pytz

from app.ai.news_summary import format_run_note, summarize_news
from app.ai.rss_fetcher import RssFetchError, fetch_rss_items
from app.models import Task
from app.notifier import send_markdown


def _payload_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def run(task: Task, payload: dict) -> tuple[str, str, str]:
    feed_url = payload.get("feed_url", "").strip()
    limit = int(payload.get("limit", 5))
    fetch_limit = int(payload.get("fetch_limit") or limit)
    summary_mode = payload.get("summary_mode", "auto")
    notify = _payload_bool(payload.get("notify"), True)
    try:
        feed = fetch_rss_items(
            feed_url,
            limit=fetch_limit,
            fallback_items=payload.get("fallback_items") or None,
        )
    except RssFetchError as exc:
        return "failed", "", f"Failed to parse feed: {exc}"

    if not feed.items:
        return "success", "No entries found in feed.", ""

    items = _filter_items(feed.items, payload, task.timezone or "Asia/Shanghai")
    if not items:
        return "success", "No news items matched the configured date window.", ""

    min_sources = max(0, int(payload.get("min_sources") or 0))
    if min_sources and limit < min_sources:
        return "failed", "", f"Task limit {limit} is lower than required source count {min_sources}."
    items = _select_source_diverse_items(items, limit)
    source_count = _source_count(items)
    if min_sources and source_count < min_sources:
        detail = f"Only {source_count} distinct news sources matched; at least {min_sources} are required."
        if feed.feed_error:
            detail = f"{detail} Feed error: {feed.feed_error}"
        return "failed", "", detail

    summary = summarize_news(
        items,
        title=task.name or "RSS Digest",
        mode=summary_mode,
        model=payload.get("model") or None,
        max_items=limit,
        timeout=int(payload.get("timeout") or 0) or None,
    )
    content = summary["content"]
    header = task.name or "RSS Digest"
    note = _format_feed_note(
        format_run_note(summary),
        feed.feed_fallback,
        feed.feed_error,
        source_count,
    )
    if not notify:
        return "success", f"{note}\nNotification skipped.\nProcessed {len(items)} items.\n\n{content}", ""

    ok, detail = send_markdown(header, content)
    if ok:
        return "success", f"{note}\nSent {len(items)} items.\n{detail}\n\n{content}", ""
    return "failed", f"{note}\nNotification attempted but failed.\n\n{content}", detail


def _format_feed_note(
    base_note: str,
    feed_fallback: bool,
    feed_error: str | None,
    source_count: int,
) -> str:
    parts = [
        base_note,
        f"sources={source_count}",
        f"feed_fallback={str(feed_fallback).lower()}",
    ]
    if feed_error:
        parts.append(f"feed_error={feed_error}")
    return " | ".join(parts)


def _filter_items(items: list[dict], payload: dict, timezone: str) -> list[dict]:
    if payload.get("date_window") != "previous_day":
        return items
    tz = pytz.timezone(timezone or "Asia/Shanghai")
    today = datetime.now(tz).date()
    start = tz.localize(datetime.combine(today - timedelta(days=1), datetime.min.time()))
    end = tz.localize(datetime.combine(today, datetime.min.time()))
    filtered = []
    for item in items:
        timestamp = int(item.get("timestamp") or 0)
        if not timestamp:
            continue
        published = datetime.fromtimestamp(timestamp, tz)
        if start <= published < end:
            filtered.append(item)
    return filtered


def _select_source_diverse_items(items: list[dict], limit: int) -> list[dict]:
    ranked = sorted(
        items,
        key=lambda item: (int(item.get("timestamp") or 0), item.get("title", "")),
        reverse=True,
    )
    selected = []
    deferred = []
    seen_sources: set[str] = set()
    for item in ranked:
        source = str(item.get("source") or "Unknown source").strip()
        key = source.casefold()
        if key not in seen_sources:
            selected.append(item)
            seen_sources.add(key)
        else:
            deferred.append(item)
        if len(selected) >= limit:
            return selected
    return (selected + deferred)[:limit]


def _source_count(items: list[dict]) -> int:
    return len(
        {
            str(item.get("source") or "Unknown source").strip().casefold()
            for item in items
        }
    )
