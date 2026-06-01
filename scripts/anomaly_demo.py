#!/usr/bin/env python3
"""Collect an Isolation Forest anomaly-demo snapshot for the report."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "anomaly-demo-notes.md"


def api(path: str, timeout: int = 60) -> Any:
    request = urllib.request.Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Edge Task Hub is not reachable at {BASE_URL}: {exc}") from exc


def spin(stop: mp.Event) -> None:
    value = 0.1
    while not stop.is_set():
        value = math.sin(value) * math.cos(value) + 0.5


def run_stress(seconds: int, workers: int) -> None:
    if seconds <= 0 or workers <= 0:
        return
    stop = mp.Event()
    procs = [mp.Process(target=spin, args=(stop,)) for _ in range(workers)]
    for proc in procs:
        proc.start()
    try:
        time.sleep(seconds)
    finally:
        stop.set()
        for proc in procs:
            proc.join(timeout=3)
        for proc in procs:
            if proc.is_alive():
                proc.terminate()


def collect_snapshot(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "timestamp": now_iso(),
        "system": api("/api/system/snapshot"),
        "stats": api("/api/anomaly/stats"),
        "events": api("/api/anomaly/events?limit=5").get("events", []),
    }


def write_doc(before: dict[str, Any], after: dict[str, Any], *, stress_seconds: int, workers: int) -> None:
    bsys = before["system"]
    asys = after["system"]
    bstats = before["stats"]
    astats = after["stats"]
    lines = [
        "# Anomaly Detection Demo Notes",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Goal",
        "",
        "Show the non-LLM model path: Isolation Forest classifies Raspberry Pi system behavior using local metrics.",
        "",
        "## Demo Run",
        "",
        f"- Stress seconds: `{stress_seconds}`",
        f"- Worker processes: `{workers}`",
        f"- Model trained before/after: `{bstats.get('model_trained')}` -> `{astats.get('model_trained')}`",
        f"- Samples before/after: `{bstats.get('samples_collected')}` -> `{astats.get('samples_collected')}`",
        f"- 24h anomalies before/after: `{bstats.get('anomalies_24h')}` -> `{astats.get('anomalies_24h')}`",
        "",
        "## System Snapshot",
        "",
        "| Metric | Before | After |",
        "| --- | ---: | ---: |",
        f"| CPU % | {bsys.get('cpu_percent')} | {asys.get('cpu_percent')} |",
        f"| Memory % | {bsys.get('memory_percent')} | {asys.get('memory_percent')} |",
        f"| Disk % | {bsys.get('disk_percent')} | {asys.get('disk_percent')} |",
        f"| Temperature C | {bsys.get('cpu_temp_c')} | {asys.get('cpu_temp_c')} |",
        "",
        "## Recent Events",
        "",
    ]
    events = after.get("events") or []
    if not events:
        lines.append("No recent anomaly events returned by the API during this run.")
    else:
        lines.extend(
            [
                "| Time | Score | CPU | Memory | Disk | Temp | Likely cause |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for event in events:
            lines.append(
                f"| {event.get('timestamp')} | {event.get('score')} | {event.get('cpu')} | "
                f"{event.get('mem')} | {event.get('disk')} | {event.get('temp')} | {event.get('likely_cause')} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This is the lightweight model path in the EdgeAI project. It does not need Ollama; it uses local system metrics and an Isolation Forest model to classify unusual device behavior.",
        ]
    )
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-seconds", type=int, default=45)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    before = collect_snapshot("before")
    run_stress(args.stress_seconds, args.workers)
    time.sleep(2)
    after = collect_snapshot("after")
    write_doc(before, after, stress_seconds=args.stress_seconds, workers=args.workers)

    result = {
        "before": before,
        "after": after,
        "doc": str(DOC_PATH),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
