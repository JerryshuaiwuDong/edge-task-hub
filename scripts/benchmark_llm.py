#!/usr/bin/env python3
"""Benchmark local Ollama or OpenClaw generation and append JSONL records."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree


DEFAULT_NEWS_PROMPT = (
    "Summarize these news titles in three English bullet points and give a short title:\n"
    "1. Raspberry Pi publishes a new edge-computing case study\n"
    "2. Local small models gain attention in privacy-preserving workflows\n"
    "3. The course project records model failures and fallback strategies"
)

DEFAULT_CHAT_PROMPT = "Explain in three English bullet points how an edge device interacts with a local model."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["ollama", "openclaw"], default="ollama")
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--url", default="http://127.0.0.1:11434/api/generate")
    parser.add_argument("--openclaw-cli", default="/home/pi3/.npm-global/bin/openclaw")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-kind", choices=["news", "chat"], default="news")
    parser.add_argument("--rss-url", default="")
    parser.add_argument("--rss-limit", type=int, default=5)
    parser.add_argument("--quality-note", default="")
    parser.add_argument("--num-ctx", type=int, default=1024)
    parser.add_argument("--num-predict", type=int, default=96)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--keep-alive", default="0")
    parser.add_argument("--capture-memory", action="store_true")
    parser.add_argument("--output", default="data/llm_benchmarks.jsonl")
    return parser.parse_args()


def ns_to_seconds(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 1_000_000_000, 3)


def build_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt
    if args.rss_url:
        items = fetch_rss_titles(args.rss_url, args.rss_limit)
        lines = ["Summarize these news titles in three English bullet points and give a short title:"]
        lines.extend(f"{index}. {title}" for index, title in enumerate(items, 1))
        return "\n".join(lines)
    return DEFAULT_NEWS_PROMPT if args.prompt_kind == "news" else DEFAULT_CHAT_PROMPT


def fetch_rss_titles(url: str, limit: int) -> list[str]:
    with urlopen(url, timeout=20) as response:
        xml = response.read()
    root = ElementTree.fromstring(xml)
    titles: list[str] = []
    for item in root.findall(".//item"):
        title = item.findtext("title")
        if title:
            titles.append(title.strip())
        if len(titles) >= limit:
            break
    if not titles:
        raise RuntimeError("RSS feed returned no item titles")
    return titles


def memory_snapshot() -> dict:
    result: dict = {}
    try:
        free = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5, check=False)
        lines = free.stdout.splitlines()
        if len(lines) >= 2:
            cols = lines[1].split()
            result["memory_mb"] = {
                "total": int(cols[1]),
                "used": int(cols[2]),
                "free": int(cols[3]),
                "available": int(cols[6]) if len(cols) > 6 else None,
            }
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        ps = subprocess.run(
            ["ps", "-eo", "comm,rss", "--no-headers"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        totals: dict[str, int] = {}
        for line in ps.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                totals[parts[0]] = totals.get(parts[0], 0) + int(parts[1])
        result["top_rss_mib"] = [
            {"process": name, "rss_mib": round(kb / 1024, 1)}
            for name, kb in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]
        ]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return result


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def benchmark_ollama(args: argparse.Namespace, prompt: str) -> dict:
    if not port_open("127.0.0.1", 11434):
        return {
            "ok": False,
            "wall_seconds": 0,
            "failure_reason": "Ollama is not running on 127.0.0.1:11434",
        }
    payload = {
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": args.keep_alive,
        "options": {
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
        },
    }
    started = time.monotonic()
    req = Request(
        args.url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=args.timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    total_wall = time.monotonic() - started
    eval_count = data.get("eval_count") or 0
    eval_duration = data.get("eval_duration") or 0
    token_per_second = eval_count / (eval_duration / 1_000_000_000) if eval_duration else None
    return {
        "ok": True,
        "wall_seconds": round(total_wall, 3),
        "ollama_total_seconds": ns_to_seconds(data.get("total_duration")),
        "load_seconds": ns_to_seconds(data.get("load_duration")),
        "prompt_eval_seconds": ns_to_seconds(data.get("prompt_eval_duration")),
        "eval_seconds": ns_to_seconds(eval_duration),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": eval_count,
        "eval_tokens_per_second": round(token_per_second, 3) if token_per_second else None,
        "done_reason": data.get("done_reason"),
        "response_preview": (data.get("response") or "").strip()[:500],
    }


def benchmark_openclaw(args: argparse.Namespace, prompt: str) -> dict:
    if not port_open("127.0.0.1", 18789):
        return {
            "ok": False,
            "wall_seconds": 0,
            "failure_reason": "OpenClaw Gateway is not running on 127.0.0.1:18789",
        }
    started = time.monotonic()
    proc = subprocess.run(
        [
            args.openclaw_cli,
            "agent",
            "--message",
            prompt,
            "--json",
            "--timeout",
            str(args.timeout),
        ],
        capture_output=True,
        text=True,
        timeout=args.timeout + 5,
        check=False,
    )
    wall = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        return {
            "ok": False,
            "wall_seconds": wall,
            "failure_reason": (proc.stderr or proc.stdout or "OpenClaw command failed").strip()[:1000],
        }
    text = proc.stdout.strip()
    try:
        data = json.loads(text)
        response = data.get("text") or data.get("message") or data.get("response") or text
    except json.JSONDecodeError:
        response = text
    return {
        "ok": True,
        "wall_seconds": wall,
        "response_preview": str(response).strip()[:500],
    }


def main() -> int:
    args = parse_args()
    record: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "model": args.model,
        "prompt_kind": args.prompt_kind,
        "rss_url": args.rss_url or None,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "keep_alive": args.keep_alive,
        "quality_note": args.quality_note or None,
        "ok": False,
    }

    try:
        prompt = build_prompt(args)
        record["prompt_preview"] = prompt[:500]
        if args.capture_memory:
            record["memory_before"] = memory_snapshot()
        if args.backend == "ollama":
            record.update(benchmark_ollama(args, prompt))
        else:
            record.update(benchmark_openclaw(args, prompt))
        if args.capture_memory:
            record["memory_after"] = memory_snapshot()
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        record.update({"failure_reason": str(exc)})
        if args.capture_memory:
            record["memory_after"] = memory_snapshot()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
