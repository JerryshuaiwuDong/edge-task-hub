#!/usr/bin/env python3
"""Evaluate EdgeAI news summary paths for the iteration report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "news_summary_eval.jsonl"
DOC_PATH = ROOT / "docs" / "news-summary-evaluation.md"

SAMPLE_NEWS = [
    {
        "title": "Raspberry Pi publishes a new edge-computing case study",
        "link": "local://edge-case",
        "source": "EdgeAI local sample",
    },
    {
        "title": "Local small models gain attention in privacy-preserving workflows",
        "link": "local://local-model",
        "source": "EdgeAI local sample",
    },
    {
        "title": "The course project records model failures and fallback strategies",
        "link": "local://fallback",
        "source": "EdgeAI local sample",
    },
]


def api(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 180) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Edge Task Hub is not reachable at {BASE_URL}: {exc}") from exc
    return json.loads(raw) if raw else {}


def service_active(name: str, *, user: bool = False) -> bool:
    cmd = ["systemctl", "--user", "is-active", name] if user else ["systemctl", "is-active", name]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.stdout.strip() == "active"


def run_service(action: str, target: str) -> None:
    subprocess.run([str(ROOT / "scripts" / "edge_services.sh"), action, target], check=True)


def wait_for_ollama(timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api("GET", "/api/model/status", timeout=10)
        if status.get("ollama", {}).get("running"):
            return True
        time.sleep(1)
    return False


def summarize(mode: str) -> dict[str, Any]:
    started = time.monotonic()
    result = api(
        "POST",
        "/api/model/news-summary",
        {
            "title": "EdgeAI News Summary Evaluation",
            "mode": mode,
            "items": SAMPLE_NEWS,
            "limit": len(SAMPLE_NEWS),
            "timeout": 30,
        },
        timeout=180,
    )
    return {
        "scenario": mode,
        "timestamp": now_iso(),
        "ok": summary_ok(mode, result),
        "backend": result.get("backend"),
        "model": result.get("model"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "tokens_per_second": result.get("tokens_per_second"),
        "fallback": result.get("fallback"),
        "feed_fallback": result.get("feed_fallback", False),
        "error": result.get("error"),
        "wall_seconds": round(time.monotonic() - started, 3),
        "quality_note": quality_note(mode, result),
        "summary_preview": preview(result.get("content", "")),
    }


def summary_ok(mode: str, result: dict[str, Any]) -> bool:
    backend = result.get("backend")
    if mode == "ollama":
        return bool(
            backend == "ollama"
            and result.get("model") == "qwen2.5:0.5b-instruct"
            and not result.get("fallback")
            and result.get("elapsed_seconds") is not None
            and result.get("tokens_per_second")
        )
    if mode == "rules":
        return backend == "rules" and not result.get("fallback")
    return bool(backend)


def run_feed_fallback_probe() -> dict[str, Any]:
    body = {
        "name": "EdgeAI news eval feed fallback probe",
        "description": "Temporary evaluation task for invalid RSS fallback.",
        "task_type": "rss_digest",
        "schedule_kind": "recurring",
        "schedule_mode": "simple",
        "cron_expr": "0 8 * * *",
        "schedule_simple_json": {"pattern": "daily", "time": "08:00"},
        "timezone": "Asia/Shanghai",
        "payload_json": {
            "feed_url": "https://invalid.invalid/edgeai-news-eval.xml",
            "limit": len(SAMPLE_NEWS),
            "summary_mode": "rules",
            "notify": False,
            "fallback_items": SAMPLE_NEWS,
        },
        "use_ai": False,
        "enabled": True,
    }
    task = api("POST", "/api/tasks", body)
    try:
        api("POST", f"/api/tasks/{task['id']}/run")
        run = api("GET", f"/api/tasks/{task['id']}/runs?limit=1")[0]
    finally:
        api("DELETE", f"/api/tasks/{task['id']}")
    meta = parse_meta(run.get("output_text", ""))
    return {
        "scenario": "feed_fallback",
        "timestamp": now_iso(),
        "ok": run.get("status") == "success" and meta.get("feed_fallback", "false") == "true",
        "backend": meta.get("backend"),
        "model": meta.get("model"),
        "elapsed_seconds": meta.get("elapsed"),
        "tokens_per_second": meta.get("tokens/s"),
        "fallback": meta.get("fallback", "false") == "true",
        "feed_fallback": meta.get("feed_fallback", "false") == "true",
        "error": meta.get("feed_error"),
        "wall_seconds": (run.get("duration_ms") or 0) / 1000,
        "quality_note": "The local rules path still produces a summary when RSS fails, so it is useful as a classroom-demo fallback.",
        "summary_preview": preview(run.get("output_text", "")),
    }


def parse_meta(text: str) -> dict[str, str]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    meta: dict[str, str] = {}
    for part in first.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            meta[key.strip()] = value.strip()
    return meta


def quality_note(mode: str, result: dict[str, Any]) -> str:
    if mode == "ollama":
        if result.get("backend") == "ollama":
            return "The LLM path records model metrics, but very small models can drift in format or content quality."
        return "The Ollama path did not succeed, so the system used the rules summary."
    return "The rules summary is fast and stable, but it mainly ranks titles and extracts keywords."


def preview(text: str, max_chars: int = 500) -> str:
    return " ".join(text.split())[:max_chars]


def append_jsonl(records: list[dict[str, Any]]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_doc(records: list[dict[str, Any]]) -> None:
    lines = [
        "# News Summary Evaluation",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Goal",
        "",
        "Compare LLM summary, rules summary, and RSS failure fallback on the same EdgeAI news set.",
        "",
        "## Results",
        "",
        "| Scenario | Backend | Model | Elapsed | Tokens/s | Fallback | RSS fallback | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        lines.append(
            "| {scenario} | {backend} | {model} | {elapsed} | {tps} | {fallback} | {feed_fallback} | {note} |".format(
                scenario=r.get("scenario"),
                backend=r.get("backend") or "-",
                model=r.get("model") or "-",
                elapsed=r.get("elapsed_seconds") or r.get("wall_seconds") or "-",
                tps=r.get("tokens_per_second") or "-",
                fallback=r.get("fallback"),
                feed_fallback=r.get("feed_fallback"),
                note=str(r.get("quality_note", "")).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `ollama` proves real local model interaction on the Raspberry Pi.",
            "- `rules` proves a fast deterministic fallback when the model is stopped or too slow.",
            "- `feed_fallback` proves external RSS/network failure does not break the workflow.",
            "",
            "Raw JSONL records are stored in `data/news_summary_eval.jsonl`.",
        ]
    )
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ollama", action="store_true", help="Only run rules and feed fallback.")
    parser.add_argument("--keep-ollama", action="store_true", help="Do not stop Ollama after a managed run.")
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    was_running = service_active("ollama.service")
    try:
        if not args.skip_ollama:
            if not was_running:
                run_service("start", "ollama")
                if not wait_for_ollama():
                    raise SystemExit("Ollama did not become reachable within 30 seconds")
            records.append(summarize("ollama"))
        records.append(summarize("rules"))
        records.append(run_feed_fallback_probe())
        append_jsonl(records)
        write_doc(records)
    finally:
        if not args.skip_ollama and not was_running and not args.keep_ollama:
            run_service("stop", "ollama")

    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    print(f"wrote {DATA_PATH}")
    print(f"wrote {DOC_PATH}")
    failed = [record for record in records if not record.get("ok")]
    if failed:
        print("failed_scenarios=" + ", ".join(str(record.get("scenario")) for record in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
