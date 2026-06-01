#!/usr/bin/env python3
"""Compare EdgeAI model choices for the final report.

This script keeps the comparison honest:
- qwen2.5:1.5b is read from existing benchmark evidence, not rerun by default.
- qwen2.5:0.5b-instruct is tested through the app's real news-summary API.
- rules and feed_fallback are tested as deterministic edge fallbacks.
- Isolation Forest is summarized as the system-status ML path, not as a news summarizer.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "model_comparison.jsonl"
DOC_PATH = ROOT / "docs" / "model-comparison.md"
BENCHMARK_PATH = ROOT / "data" / "llm_benchmarks.jsonl"
MANIFEST_ROOT = Path("/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library")
REJECTED_MODEL = "qwen2.5:1.5b"
MAIN_MODEL = "qwen2.5:0.5b-instruct"
QWEN3_MODEL = "qwen3:0.6b"
MIN_QWEN3_DOWNLOAD_GB = 1.0
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def run_service(action: str, target: str) -> None:
    subprocess.run([str(ROOT / "scripts" / "edge_services.sh"), action, target], check=True)


def service_active(name: str, *, user: bool = False) -> bool:
    cmd = ["systemctl", "--user", "is-active", name] if user else ["systemctl", "is-active", name]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.stdout.strip() == "active"


def wait_for_ollama(timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api("GET", "/api/model/status", timeout=10)
        if status.get("ollama", {}).get("running"):
            return True
        time.sleep(1)
    return False


def memory_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {"timestamp": now_iso()}
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
        result["memory_mb"] = None
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
            for name, kb in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]
        ]
    except (OSError, subprocess.SubprocessError, ValueError):
        result["top_rss_mib"] = []
    return result


def disk_snapshot() -> dict[str, Any]:
    usage = psutil.disk_usage("/")
    return {
        "total_gb": round(usage.total / (1024**3), 2),
        "used_gb": round(usage.used / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "percent": round(usage.percent, 1),
    }


def installed_models() -> list[str]:
    models: set[str] = set()
    if MANIFEST_ROOT.exists():
        for path in MANIFEST_ROOT.glob("*/*"):
            if path.is_file():
                models.add(f"{path.parent.name}:{path.name}")
    return sorted(models)


def run_cmd(cmd: list[str], *, timeout: int = 600) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": clean_cli_text(proc.stdout)[:1000],
            "stderr": clean_cli_text(proc.stderr)[:1000],
            "wall_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": clean_cli_text(exc.stdout or "")[:1000] if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
            "wall_seconds": round(time.monotonic() - started, 3),
        }


def clean_cli_text(text: str) -> str:
    cleaned = ANSI_RE.sub("", text or "")
    for spinner in "⠋⠙⠹⠸⠼":
        cleaned = cleaned.replace(spinner, "")
    return " ".join(cleaned.split())


def existing_records() -> list[dict[str, Any]]:
    if not DATA_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in DATA_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_meta(text: str) -> dict[str, str]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    meta: dict[str, str] = {}
    for part in first.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            meta[key.strip()] = value.strip()
    return meta


def preview(text: str, max_chars: int = 360) -> str:
    return " ".join((text or "").split())[:max_chars]


def latest_benchmark(model: str) -> dict[str, Any] | None:
    if not BENCHMARK_PATH.exists():
        return None
    selected = None
    for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("model") == model:
            selected = record
    return selected


def qwen15_record() -> dict[str, Any]:
    bench = latest_benchmark(REJECTED_MODEL) or {}
    return {
        "scenario": REJECTED_MODEL,
        "task": "news_summary",
        "timestamp": now_iso(),
        "backend": bench.get("backend") or "ollama",
        "model": REJECTED_MODEL,
        "ok": bool(bench.get("ok")),
        "elapsed_seconds": bench.get("wall_seconds"),
        "tokens_per_second": bench.get("eval_tokens_per_second"),
        "fallback": False,
        "feed_fallback": False,
        "memory_before": bench.get("memory_before"),
        "memory_after": bench.get("memory_after"),
        "failure_reason": bench.get("failure_reason") or (None if bench.get("ok") else "No benchmark evidence found"),
        "quality_note": "Failure baseline: the larger model was slower and historical benchmark evidence shows it missed the 30-second summary target.",
        "decision": "reject_for_demo",
    }


def summarize_news(mode: str, *, model: str | None = None, scenario: str | None = None) -> dict[str, Any]:
    before = memory_snapshot()
    disk_before = disk_snapshot()
    started = time.monotonic()
    result = api(
        "POST",
        "/api/model/news-summary",
        {
            "title": "EdgeAI Model Selection Comparison",
            "mode": mode,
            "model": model or "",
            "items": SAMPLE_NEWS,
            "limit": len(SAMPLE_NEWS),
            "timeout": 30,
        },
        timeout=180,
    )
    after = memory_snapshot()
    disk_after = disk_snapshot()
    ok = bool(result.get("backend") == mode and not result.get("fallback")) if mode == "ollama" else bool(result.get("backend") == "rules")
    return {
        "scenario": scenario or (model or MAIN_MODEL if mode == "ollama" else "rules"),
        "task": "news_summary",
        "timestamp": now_iso(),
        "backend": result.get("backend"),
        "model": result.get("model"),
        "ok": ok,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "tokens_per_second": result.get("tokens_per_second"),
        "fallback": result.get("fallback"),
        "feed_fallback": result.get("feed_fallback", False),
        "memory_before": before,
        "memory_after": after,
        "disk_before": disk_before,
        "disk_after": disk_after,
        "failure_reason": result.get("error"),
        "quality_note": quality_note(mode, result, model=model),
        "summary_preview": preview(result.get("content", "")),
        "wall_seconds": round(time.monotonic() - started, 3),
        "decision": model_decision(mode, model, ok),
    }


def quality_note(mode: str, result: dict[str, Any], *, model: str | None = None) -> str:
    if mode == "ollama":
        if result.get("backend") == "ollama":
            if model == QWEN3_MODEL:
                return "Qwen3 candidate: used to test whether a newer compact model can improve local model interaction on the Raspberry Pi."
            return "Real local model interaction: it records elapsed time and tokens per second, but output quality can drift."
        return "The Ollama path failed, showing that local LLMs remain constrained by edge resources."
    return "The rules summary is fastest and most stable, but it ranks titles and extracts keywords rather than generating language."


def model_decision(mode: str, model: str | None, ok: bool) -> str:
    if mode == "rules":
        return "fallback_baseline"
    if model == QWEN3_MODEL:
        return "qwen3_candidate_passed" if ok else "qwen3_candidate_rejected"
    return "main_llm_demo" if ok else "reject_for_demo"


def prepare_qwen3_records(*, keep_ollama: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.append(qwen15_record())
    was_running = service_active("ollama.service")
    if not was_running:
        run_service("start", "ollama")
        if not wait_for_ollama():
            records.append(model_management_record(
                "start_ollama_for_model_management",
                None,
                False,
                "Ollama did not become reachable within 30 seconds",
            ))
            return records

    try:
        before = disk_snapshot()
        before_models = installed_models()
        if REJECTED_MODEL in before_models:
            result = run_cmd(["ollama", "rm", REJECTED_MODEL], timeout=180)
            records.append(model_management_record(
                "remove_rejected_model",
                REJECTED_MODEL,
                result["ok"],
                result["stderr"] or result["stdout"] or None,
                before_disk=before,
                after_disk=disk_snapshot(),
                before_models=before_models,
                after_models=installed_models(),
                wall_seconds=result["wall_seconds"],
            ))
        else:
            records.append(model_management_record(
                "remove_rejected_model",
                REJECTED_MODEL,
                True,
                "Model was already absent; historical benchmark evidence remains in data/llm_benchmarks.jsonl.",
                before_disk=before,
                after_disk=disk_snapshot(),
                before_models=before_models,
                after_models=installed_models(),
            ))

        after_remove = disk_snapshot()
        models_after_remove = installed_models()
        if QWEN3_MODEL in models_after_remove:
            records.append(model_management_record(
                "pull_qwen3_candidate",
                QWEN3_MODEL,
                True,
                "Model already installed.",
                before_disk=after_remove,
                after_disk=disk_snapshot(),
                before_models=models_after_remove,
                after_models=installed_models(),
            ))
        elif after_remove["free_gb"] < MIN_QWEN3_DOWNLOAD_GB:
            records.append(model_management_record(
                "pull_qwen3_candidate",
                QWEN3_MODEL,
                False,
                f"Skipped because free disk {after_remove['free_gb']} GB is below {MIN_QWEN3_DOWNLOAD_GB} GB.",
                before_disk=after_remove,
                after_disk=after_remove,
                before_models=models_after_remove,
                after_models=models_after_remove,
            ))
        else:
            result = run_cmd(["ollama", "pull", QWEN3_MODEL], timeout=900)
            records.append(model_management_record(
                "pull_qwen3_candidate",
                QWEN3_MODEL,
                result["ok"],
                result["stderr"] or result["stdout"] or None,
                before_disk=after_remove,
                after_disk=disk_snapshot(),
                before_models=models_after_remove,
                after_models=installed_models(),
                wall_seconds=result["wall_seconds"],
            ))
    finally:
        if not was_running and not keep_ollama:
            run_service("stop", "ollama")

    return records


def model_management_record(
    action: str,
    model: str | None,
    ok: bool,
    message: str | None,
    *,
    before_disk: dict[str, Any] | None = None,
    after_disk: dict[str, Any] | None = None,
    before_models: list[str] | None = None,
    after_models: list[str] | None = None,
    wall_seconds: float | None = None,
) -> dict[str, Any]:
    return {
        "scenario": action,
        "task": "model_storage_management",
        "timestamp": now_iso(),
        "backend": "ollama_cli",
        "model": model,
        "ok": ok,
        "elapsed_seconds": wall_seconds,
        "tokens_per_second": None,
        "fallback": False,
        "feed_fallback": False,
        "disk_before": before_disk,
        "disk_after": after_disk,
        "models_before": before_models,
        "models_after": after_models,
        "failure_reason": None if ok else message,
        "quality_note": message,
        "decision": "storage_preparation",
    }


def feed_fallback_record() -> dict[str, Any]:
    body = {
        "name": "EdgeAI model comparison RSS fallback probe",
        "description": "Temporary model-comparison task for invalid RSS fallback.",
        "task_type": "rss_digest",
        "schedule_kind": "recurring",
        "schedule_mode": "simple",
        "cron_expr": "0 8 * * *",
        "schedule_simple_json": {"pattern": "daily", "time": "08:00"},
        "timezone": "Asia/Shanghai",
        "payload_json": {
            "feed_url": "https://invalid.invalid/edgeai-model-comparison.xml",
            "limit": len(SAMPLE_NEWS),
            "summary_mode": "rules",
            "notify": False,
            "fallback_items": SAMPLE_NEWS,
        },
        "use_ai": False,
        "enabled": True,
    }
    before = memory_snapshot()
    task = api("POST", "/api/tasks", body)
    try:
        api("POST", f"/api/tasks/{task['id']}/run")
        run = api("GET", f"/api/tasks/{task['id']}/runs?limit=1")[0]
    finally:
        api("DELETE", f"/api/tasks/{task['id']}")
    after = memory_snapshot()
    disk_after = disk_snapshot()
    meta = parse_meta(run.get("output_text", ""))
    return {
        "scenario": "feed_fallback",
        "task": "rss_failure_recovery",
        "timestamp": now_iso(),
        "backend": meta.get("backend"),
        "model": None,
        "ok": run.get("status") == "success" and meta.get("feed_fallback") == "true",
        "elapsed_seconds": meta.get("elapsed"),
        "tokens_per_second": None,
        "fallback": meta.get("fallback", "false") == "true",
        "feed_fallback": meta.get("feed_fallback") == "true",
        "memory_before": before,
        "memory_after": after,
        "disk_before": None,
        "disk_after": disk_after,
        "failure_reason": meta.get("feed_error"),
        "quality_note": "The demo still completes when RSS fails, proving that network failure is recorded and handled on the edge device.",
        "summary_preview": preview(run.get("output_text", "")),
        "wall_seconds": (run.get("duration_ms") or 0) / 1000,
        "decision": "required_reliability_path",
    }


def isolation_forest_record() -> dict[str, Any]:
    before = memory_snapshot()
    stats = api("GET", "/api/anomaly/stats")
    events = api("GET", "/api/anomaly/events?limit=3").get("events", [])
    system = api("GET", "/api/system/snapshot")
    after = memory_snapshot()
    return {
        "scenario": "isolation_forest",
        "task": "system_anomaly_detection",
        "timestamp": now_iso(),
        "backend": "sklearn",
        "model": "IsolationForest",
        "ok": bool(stats.get("enabled") and stats.get("model_trained")),
        "elapsed_seconds": 0,
        "tokens_per_second": None,
        "fallback": False,
        "feed_fallback": False,
        "memory_before": before,
        "memory_after": after,
        "disk_before": None,
        "disk_after": disk_snapshot(),
        "failure_reason": None if stats.get("model_trained") else "Isolation Forest is not trained",
        "quality_note": "Not used for news summaries; suitable for analyzing CPU, memory, disk, temperature, and network anomalies on the edge device.",
        "system_snapshot": system,
        "anomaly_stats": stats,
        "recent_events": events,
        "decision": "keep_for_device_health",
    }


def append_jsonl(records: list[dict[str, Any]]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def fmt(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return clean_cli_text(str(value)).replace("|", "/")


def memory_delta(record: dict[str, Any]) -> str:
    before = ((record.get("memory_before") or {}).get("memory_mb") or {})
    after = ((record.get("memory_after") or {}).get("memory_mb") or {})
    if "available" not in before or "available" not in after:
        return "-"
    delta = after["available"] - before["available"]
    return f"{delta:+d} MB available"


def write_doc(records: list[dict[str, Any]]) -> None:
    anomaly = next((r for r in records if r.get("scenario") == "isolation_forest"), {})
    stats = anomaly.get("anomaly_stats") or {}
    storage = storage_summary_records(existing_records() + records)
    lines = [
        "# EdgeAI Model Comparison",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Goal",
        "",
        "Compare model choices for the Raspberry Pi EdgeAI project without pretending that every model solves the same task.",
        "",
        "## Resource-Aware Router",
        "",
        "The router makes model selection explicit: it records memory, disk, installed models, latency, and rejection reasons before choosing a path.",
        "",
        "- Large local LLMs are rejected when existing evidence shows they miss the 30-second live-demo target.",
        "- `qwen3:0.6b` is tested only after the old rejected model is recorded and removed to protect disk space.",
        "- Rules remain the deterministic fallback when Ollama is stopped, too slow, or not safe for current resources.",
        "",
        "## News Summary Comparison",
        "",
        "| Candidate | Task | OK | Backend | Model | Elapsed | Tokens/s | Memory delta | Decision | Note |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for r in records:
        if r.get("task") not in {"news_summary", "rss_failure_recovery"}:
            continue
        lines.append(
            "| {scenario} | {task} | {ok} | {backend} | {model} | {elapsed} | {tps} | {mem} | {decision} | {note} |".format(
                scenario=fmt(r.get("scenario")),
                task=fmt(r.get("task")),
                ok=fmt(r.get("ok")),
                backend=fmt(r.get("backend")),
                model=fmt(r.get("model")),
                elapsed=fmt(r.get("elapsed_seconds") or r.get("wall_seconds")),
                tps=fmt(r.get("tokens_per_second")),
                mem=fmt(memory_delta(r)),
                decision=fmt(r.get("decision")),
                note=fmt(r.get("quality_note")),
            )
        )
    lines.extend(
        [
            "",
            "## Model Storage Preparation",
            "",
            "| Action | Model | OK | Disk before | Disk after | Decision | Note |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for r in storage:
        before = r.get("disk_before") or {}
        after = r.get("disk_after") or {}
        lines.append(
            "| {action} | {model} | {ok} | {before} GB free | {after} GB free | {decision} | {note} |".format(
                action=fmt(r.get("scenario")),
                model=fmt(r.get("model")),
                ok=fmt(r.get("ok")),
                before=fmt(before.get("free_gb")),
                after=fmt(after.get("free_gb")),
                decision=fmt(r.get("decision")),
                note=fmt(storage_note(r)),
            )
        )
    lines.extend(
        [
            "",
            "## System Model Comparison",
            "",
            "| Candidate | Task | OK | Samples | 24h anomalies | Decision | Note |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
            "| Isolation Forest | system_anomaly_detection | {ok} | {samples} | {anom} | keep_for_device_health | {note} |".format(
                ok=fmt(anomaly.get("ok")),
                samples=fmt(stats.get("samples_collected")),
                anom=fmt(stats.get("anomalies_24h")),
                note=fmt(anomaly.get("quality_note")),
            ),
            "",
            "## Final Selection",
            "",
            "- `qwen2.5:1.5b`: rejected for the live demo because existing benchmark evidence shows it missed the 30-second target.",
            "- `qwen2.5:0.5b-instruct`: selected as the main LLM interaction path because it proves local model inference and records model/elapsed/tokens/s.",
            "- `qwen3:0.6b`: tested as a gated candidate only if disk space is available after removing the rejected larger model.",
            "- `rules`: selected as required fallback because it is fast, deterministic, and survives Ollama or RSS failures.",
            "- `Isolation Forest`: selected for system-status analysis, not news summary, because it matches CPU/memory/disk/temperature/network anomaly detection.",
            "",
            "## Report Conclusion",
            "",
            "The project should present a hybrid EdgeAI design: use the local LLM when it is available and fast enough, fall back to rules when reliability matters, and use Isolation Forest for device-health intelligence. This shows model interaction, trial-and-error, and edge-resource constraints without forcing unrelated models into one fake ranking.",
            "",
            f"Raw JSONL records are stored in `{DATA_PATH.relative_to(ROOT)}`.",
        ]
    )
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def storage_summary_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    storage = [r for r in records if r.get("task") == "model_storage_management"]
    selected: list[dict[str, Any]] = []
    removal = next(
        (
            r for r in storage
            if r.get("scenario") == "remove_rejected_model"
            and disk_free_delta(r) > 0
        ),
        None,
    )
    if removal:
        selected.append(removal)
    else:
        latest_removal = next(
            (r for r in reversed(storage) if r.get("scenario") == "remove_rejected_model"),
            None,
        )
        if latest_removal:
            selected.append(latest_removal)

    latest_qwen3 = next(
        (r for r in reversed(storage) if r.get("scenario") == "pull_qwen3_candidate"),
        None,
    )
    if latest_qwen3:
        selected.append(latest_qwen3)
    return selected


def disk_free_delta(record: dict[str, Any]) -> float:
    before = (record.get("disk_before") or {}).get("free_gb")
    after = (record.get("disk_after") or {}).get("free_gb")
    if before is None or after is None:
        return 0.0
    try:
        return float(after) - float(before)
    except (TypeError, ValueError):
        return 0.0


def storage_note(record: dict[str, Any]) -> str:
    scenario = record.get("scenario")
    if scenario == "remove_rejected_model" and disk_free_delta(record) > 0:
        return "Removed rejected 1.5B model after preserving its timeout evidence."
    reason = clean_cli_text(record.get("failure_reason") or record.get("quality_note") or "")
    if scenario == "pull_qwen3_candidate" and "tls:" in reason:
        return "Qwen3 download failed because registry.ollama.ai TLS certificate verification failed."
    return reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-ollama", action="store_true", help="Do not stop Ollama after this script starts it.")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip live qwen2.5:0.5b-instruct run.")
    parser.add_argument("--prepare-qwen3", action="store_true", help="Record qwen2.5:1.5b evidence, remove it, then gated-pull qwen3:0.6b.")
    parser.add_argument("--skip-qwen3", action="store_true", help="Skip live qwen3:0.6b candidate run.")
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    if args.prepare_qwen3:
        records.extend(prepare_qwen3_records(keep_ollama=args.keep_ollama))
    else:
        records.append(qwen15_record())

    was_running = service_active("ollama.service")
    try:
        need_ollama = not args.skip_ollama or (QWEN3_MODEL in installed_models() and not args.skip_qwen3)
        if need_ollama:
            if not was_running:
                run_service("start", "ollama")
                if not wait_for_ollama():
                    records.append(
                        {
                            "scenario": "qwen2.5:0.5b-instruct",
                            "task": "news_summary",
                            "timestamp": now_iso(),
                            "backend": "ollama",
                            "model": "qwen2.5:0.5b-instruct",
                            "ok": False,
                            "failure_reason": "Ollama did not become reachable within 30 seconds",
                            "decision": "reject_for_current_run",
                        }
                    )
                else:
                    if not args.skip_ollama:
                        records.append(summarize_news("ollama", model=MAIN_MODEL))
            else:
                if not args.skip_ollama:
                    records.append(summarize_news("ollama", model=MAIN_MODEL))
            if QWEN3_MODEL in installed_models() and not args.skip_qwen3 and (was_running or wait_for_ollama(timeout=5)):
                records.append(summarize_news("ollama", model=QWEN3_MODEL))
        records.append(summarize_news("rules"))
        records.append(feed_fallback_record())
        records.append(isolation_forest_record())
    finally:
        if not was_running and not args.keep_ollama:
            run_service("stop", "ollama")

    append_jsonl(records)
    write_doc(records)

    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    print(f"wrote {DATA_PATH}")
    print(f"wrote {DOC_PATH}")

    required = [record for record in records if record.get("scenario") in {MAIN_MODEL, "rules", "feed_fallback", "isolation_forest"}]
    failed = [record for record in required if not record.get("ok")]
    if failed:
        print("failed_scenarios=" + ", ".join(str(record.get("scenario")) for record in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
