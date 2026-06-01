"""RSS fetching helpers with demo fallback support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import feedparser
import requests


USER_AGENT = "EdgeTaskHub/1.0 RaspberryPi EdgeAI Demo"


class RssFetchError(RuntimeError):
    """Raised when an RSS feed cannot be fetched and no fallback is available."""


@dataclass
class RssFetchResult:
    feed_title: str
    items: list[dict[str, Any]]
    feed_fallback: bool = False
    feed_error: str | None = None


def fetch_rss_items(
    feed_url: str,
    *,
    limit: int = 5,
    fallback_items: list[dict[str, Any]] | None = None,
    timeout: int = 15,
) -> RssFetchResult:
    """Fetch RSS via requests, parse entries, and optionally use local demo data."""
    clean_url = (feed_url or "").strip()
    if not clean_url:
        return _fallback_or_raise("RSS feed URL is required.", fallback_items, limit)

    try:
        content, warning = _download_feed(clean_url, timeout=timeout)
        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            raise RssFetchError(_short_error(parsed.bozo_exception))
        if not parsed.entries:
            raise RssFetchError("RSS feed returned no entries.")
        feed_title = getattr(parsed.feed, "title", "") or clean_url
        return RssFetchResult(
            feed_title=feed_title,
            items=[_entry_to_item(entry, feed_title) for entry in parsed.entries[:limit]],
            feed_fallback=False,
            feed_error=warning,
        )
    except Exception as exc:  # noqa: BLE001
        return _fallback_or_raise(_short_error(exc), fallback_items, limit)


def _download_feed(feed_url: str, *, timeout: int) -> tuple[bytes, str | None]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        response = requests.get(feed_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.content, None
    except requests.exceptions.SSLError as exc:
        warning = f"SSL verification failed; retried without certificate verification: {_short_error(exc)}"
        response = requests.get(feed_url, headers=headers, timeout=timeout, verify=False)
        response.raise_for_status()
        return response.content, warning


def _fallback_or_raise(
    error: str,
    fallback_items: list[dict[str, Any]] | None,
    limit: int,
) -> RssFetchResult:
    if not fallback_items:
        raise RssFetchError(error)
    return RssFetchResult(
        feed_title="Local demo fallback",
        items=[_normalize_fallback_item(item) for item in fallback_items[:limit]],
        feed_fallback=True,
        feed_error=error,
    )


def _entry_to_item(entry: Any, feed_title: str) -> dict[str, Any]:
    return {
        "title": getattr(entry, "title", "Untitled"),
        "link": getattr(entry, "link", ""),
        "source": feed_title,
        "timestamp": parse_entry_timestamp(entry),
    }


def _normalize_fallback_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title") or "Untitled",
        "link": item.get("link") or "",
        "source": item.get("source") or "Local demo fallback",
        "timestamp": int(item.get("timestamp") or 0),
    }


def parse_entry_timestamp(entry: Any) -> int:
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            return int(datetime(*value[:6]).timestamp())
    for attr in ("published", "updated", "pubDate", "isoDate"):
        value = getattr(entry, attr, "")
        if value:
            try:
                return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
    return 0


def _short_error(exc: object) -> str:
    return " ".join(str(exc).split())[:300]
