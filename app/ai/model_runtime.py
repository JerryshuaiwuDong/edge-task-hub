"""Runtime helpers for optional local model backends."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

from app.config import settings


@dataclass
class ModelResult:
    ok: bool
    text: str
    backend: str
    model: str | None
    elapsed_seconds: float
    error: str | None = None
    total_seconds: float | None = None
    load_seconds: float | None = None
    eval_seconds: float | None = None
    eval_count: int | None = None
    eval_tokens_per_second: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ollama_running() -> bool:
    return port_open("127.0.0.1", 11434)


def openclaw_running() -> bool:
    return port_open("127.0.0.1", 18789)


def ns_to_seconds(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 1_000_000_000, 3)


def generate_ollama(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 256,
    timeout: int | None = None,
    num_ctx: int | None = None,
    keep_alive: str | None = None,
) -> ModelResult:
    model_name = model or settings.ollama_model
    request_timeout = timeout or settings.model_speed_target_seconds
    started = time.monotonic()
    if not ollama_running():
        return ModelResult(
            ok=False,
            text="",
            backend="ollama",
            model=model_name,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error="Ollama is not running on 127.0.0.1:11434",
        )

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": keep_alive if keep_alive is not None else settings.ollama_keep_alive,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": num_ctx or settings.ollama_num_ctx,
        },
    }
    try:
        response = requests.post(settings.ollama_url, json=payload, timeout=request_timeout)
        response.raise_for_status()
        data = response.json()
        elapsed = round(time.monotonic() - started, 3)
        eval_count = data.get("eval_count") or 0
        eval_duration = data.get("eval_duration") or 0
        speed = eval_count / (eval_duration / 1_000_000_000) if eval_duration else None
        return ModelResult(
            ok=True,
            text=(data.get("response") or "").strip(),
            backend="ollama",
            model=model_name,
            elapsed_seconds=elapsed,
            total_seconds=ns_to_seconds(data.get("total_duration")),
            load_seconds=ns_to_seconds(data.get("load_duration")),
            eval_seconds=ns_to_seconds(eval_duration),
            eval_count=eval_count,
            eval_tokens_per_second=round(speed, 3) if speed else None,
        )
    except requests.Timeout:
        return ModelResult(
            ok=False,
            text="",
            backend="ollama",
            model=model_name,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error=f"Ollama timeout after {request_timeout}s",
        )
    except requests.RequestException as exc:
        return ModelResult(
            ok=False,
            text="",
            backend="ollama",
            model=model_name,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error=str(exc),
        )


def generate_openclaw(
    prompt: str,
    *,
    timeout: int | None = None,
) -> ModelResult:
    request_timeout = timeout or settings.model_speed_target_seconds
    started = time.monotonic()
    if not openclaw_running():
        return ModelResult(
            ok=False,
            text="",
            backend="openclaw",
            model=settings.ollama_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error="OpenClaw Gateway is not running on 127.0.0.1:18789",
        )

    cli = Path(settings.openclaw_cli)
    if not cli.exists():
        return ModelResult(
            ok=False,
            text="",
            backend="openclaw",
            model=settings.ollama_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error=f"OpenClaw CLI not found: {cli}",
        )

    cmd = [
        str(cli),
        "agent",
        "--message",
        prompt,
        "--json",
        "--timeout",
        str(request_timeout),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=request_timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ModelResult(
            ok=False,
            text="",
            backend="openclaw",
            model=settings.ollama_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            error=f"OpenClaw timeout after {request_timeout}s",
        )

    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        return ModelResult(
            ok=False,
            text="",
            backend="openclaw",
            model=settings.ollama_model,
            elapsed_seconds=elapsed,
            error=(proc.stderr or proc.stdout or "OpenClaw command failed").strip()[:1000],
        )

    text = proc.stdout.strip()
    try:
        data = json.loads(text)
        text = (
            data.get("text")
            or data.get("message")
            or data.get("response")
            or data.get("content")
            or text
        )
    except json.JSONDecodeError:
        pass
    return ModelResult(
        ok=True,
        text=str(text).strip(),
        backend="openclaw",
        model=settings.ollama_model,
        elapsed_seconds=elapsed,
    )


def recent_benchmark(path: str = "data/llm_benchmarks.jsonl") -> dict[str, Any] | None:
    benchmark_path = Path(path)
    if not benchmark_path.is_absolute():
        benchmark_path = Path(__file__).resolve().parents[2] / benchmark_path
    if not benchmark_path.exists():
        return None
    try:
        lines = [line for line in benchmark_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None
    except (OSError, json.JSONDecodeError):
        return None
