"""News summarization with optional local model backends and rule fallback."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from app.ai.model_runtime import (
    ModelResult,
    generate_ollama,
    generate_openclaw,
    ollama_running,
    openclaw_running,
)
from app.config import settings


STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "has", "have", "will", "about", "after", "into", "over", "under", "news",
}

EDGE_SUMMARY_MAX_TOKENS = 64


def summarize_news(
    items: list[dict[str, Any]],
    *,
    title: str = "News Summary",
    mode: str | None = None,
    model: str | None = None,
    max_items: int = 5,
    timeout: int | None = None,
) -> dict[str, Any]:
    selected = rank_items(items)[:max_items]
    summary_mode = normalize_mode(mode or settings.news_summary_mode)
    target_timeout = timeout or settings.news_summary_timeout_seconds
    max_tokens = settings.news_summary_max_tokens or EDGE_SUMMARY_MAX_TOKENS

    if not selected:
        return {
            "title": title,
            "content": "No news items are available to summarize.",
            "backend": "none",
            "mode": summary_mode,
            "fallback": False,
            "error": None,
            "elapsed_seconds": 0,
        }

    if summary_mode == "rules":
        return _rule_result(title, selected, summary_mode)

    prompt = build_news_prompt(title, selected)
    model_result: ModelResult | None = None

    if summary_mode == "ollama" or (
        summary_mode == "auto" and (settings.enable_ollama or ollama_running())
    ):
        model_result = generate_ollama(
            prompt,
            model=model or settings.news_summary_model,
            max_tokens=max_tokens,
            timeout=target_timeout,
        )
    elif summary_mode == "openclaw" or (
        summary_mode == "auto" and (settings.enable_openclaw or openclaw_running())
    ):
        model_result = generate_openclaw(prompt, timeout=target_timeout)

    if model_result and model_result.ok and model_result.text:
        content = _append_sources(model_result.text, selected)
        return {
            "title": title,
            "content": content,
            "backend": model_result.backend,
            "model": model_result.model,
            "mode": summary_mode,
            "fallback": False,
            "error": None,
            "elapsed_seconds": model_result.elapsed_seconds,
            "tokens_per_second": model_result.eval_tokens_per_second,
        }

    fallback = _rule_result(title, selected, summary_mode)
    fallback["fallback"] = True
    fallback["attempted_backend"] = model_result.backend if model_result else None
    fallback["attempted_model"] = model_result.model if model_result else None
    fallback["error"] = (
        model_result.error
        if model_result and model_result.error
        else "The local model returned an empty response."
        if model_result
        else "No model backend is running for auto mode; used local rules."
    )
    fallback["elapsed_seconds"] = model_result.elapsed_seconds if model_result else 0
    return fallback


def normalize_mode(mode: str) -> str:
    value = (mode or "auto").strip().lower()
    return value if value in {"auto", "ollama", "openclaw", "rules"} else "auto"


def rank_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(item: dict[str, Any]) -> tuple[int, str]:
        published = item.get("timestamp") or 0
        return (int(published), item.get("title", ""))

    return sorted(items, key=score, reverse=True)


def build_news_prompt(title: str, items: list[dict[str, Any]]) -> str:
    lines = [
        "You are a local news summary assistant running on a Raspberry Pi.",
        "Use only the provided titles. Do not invent facts.",
        "Return English output with: a short title, 2-3 concise bullet points, and one overall judgement sentence.",
        f"Task: {title}",
        "Titles:",
    ]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item.get('title', 'Untitled')}")
    return "\n".join(lines)


def _rule_result(title: str, items: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    keywords = extract_keywords([item.get("title", "") for item in items])
    headline = " / ".join(keywords[:3]) if keywords else title
    bullets = []
    for item in items[:5]:
        source = item.get("source") or "Unknown source"
        bullets.append(f"- {item.get('title', 'Untitled')} ({source})")
    content = "\n".join(
        [
            f"### {headline[:40]}",
            "",
            "Local rule summary:",
            *bullets,
            "",
            "Overall judgement: these items were grouped locally by time and source on the edge device.",
        ]
    )
    return {
        "title": title,
        "content": _append_sources(content, items),
        "backend": "rules",
        "model": None,
        "mode": mode,
        "fallback": False,
        "error": None,
        "elapsed_seconds": 0,
        "tokens_per_second": None,
    }


def _append_sources(text: str, items: list[dict[str, Any]]) -> str:
    source_lines = []
    for index, item in enumerate(items[:10], 1):
        link = item.get("link")
        if link:
            source_lines.append(f"{index}. [{item.get('title', 'Untitled')}]({link})")
        else:
            source_lines.append(f"{index}. {item.get('title', 'Untitled')}")
    return f"{text.strip()}\n\nSource links:\n" + "\n".join(source_lines)


def extract_keywords(titles: list[str]) -> list[str]:
    words: list[str] = []
    for title in titles:
        words.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9-]{2,}", title))
    counts = Counter(
        word.lower()
        for word in words
        if word.lower() not in STOPWORDS and len(word.strip()) >= 2
    )
    return [word for word, _ in counts.most_common(5)]


def format_run_note(summary: dict[str, Any]) -> str:
    parts = [
        f"summary_mode={summary.get('mode')}",
        f"backend={summary.get('backend')}",
        f"elapsed={summary.get('elapsed_seconds')}s",
    ]
    if summary.get("model"):
        parts.append(f"model={summary['model']}")
    if summary.get("fallback"):
        parts.append("fallback=true")
    if summary.get("attempted_backend"):
        parts.append(f"attempted_backend={summary['attempted_backend']}")
    if summary.get("attempted_model"):
        parts.append(f"attempted_model={summary['attempted_model']}")
    if summary.get("error"):
        parts.append(f"error={summary['error']}")
    if summary.get("tokens_per_second"):
        parts.append(f"tokens/s={summary['tokens_per_second']}")
    return " | ".join(parts)


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
