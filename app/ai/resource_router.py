"""Resource-aware model routing status for the EdgeAI demo."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy.orm import Session

from app.ai.model_runtime import ollama_running, recent_benchmark
from app.config import settings
from app.models import SystemMetric

MANIFEST_ROOTS = [
    Path("/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library"),
    Path.home() / ".ollama/models/manifests/registry.ollama.ai/library",
]
MAIN_MODEL = settings.news_summary_model
REJECTED_MODEL = "qwen3.5:0.8b"
FAST_MODEL = "qwen3:0.6b"
MIN_LLM_MEMORY_MB = 1500
MIN_QWEN3_DOWNLOAD_GB = 1.0


def build_router_status(db: Session | None = None) -> dict[str, Any]:
    snap = resource_snapshot()
    installed = installed_models()
    rejected = latest_model_benchmark(REJECTED_MODEL, tasks={"news_summary"})
    main = latest_model_benchmark(MAIN_MODEL, tasks={"news_summary"}) or recent_benchmark()
    healthy_for_llm = snap["memory_available_mb"] >= MIN_LLM_MEMORY_MB
    running = ollama_running()

    if running and healthy_for_llm and MAIN_MODEL in installed:
        selected_backend = "ollama"
        selected_model = MAIN_MODEL
        reason = "Ollama is running, memory is sufficient, and news summaries now prefer quality over a strict 30-second cold-start target."
    elif not running:
        selected_backend = "rules"
        selected_model = None
        reason = "Ollama is stopped; use rules until the local model service is started for a demo."
    elif not healthy_for_llm:
        selected_backend = "rules"
        selected_model = None
        reason = f"Available memory is below {MIN_LLM_MEMORY_MB} MB; use rules to protect the edge device."
    else:
        selected_backend = "rules"
        selected_model = None
        reason = "The selected news-summary model is not installed; use rules as the deterministic path."

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "snapshot": snap,
        "installed_models": installed,
        "selected_backend": selected_backend,
        "selected_model": selected_model,
        "decision_reason": reason,
        "policy": {
            "min_llm_memory_mb": MIN_LLM_MEMORY_MB,
            "min_qwen3_download_gb": MIN_QWEN3_DOWNLOAD_GB,
            "ollama_keep_alive": settings.ollama_keep_alive,
            "ollama_num_ctx": settings.ollama_num_ctx,
            "dangerous_actions_forbidden": [
                "drop_caches",
                "swapoff",
                "automatic process kill",
                "automatic service restart",
            ],
        },
        "candidates": [
            {
                "name": REJECTED_MODEL,
                "type": "local_llm",
                "installed": REJECTED_MODEL in installed,
                "status": "rejected",
                "reason": "Historical benchmark showed weak quality and slow cold-start behavior for this project.",
                "evidence": benchmark_evidence(rejected),
            },
            {
                "name": MAIN_MODEL,
                "type": "local_llm",
                "installed": MAIN_MODEL in installed,
                "status": "selected" if selected_model == MAIN_MODEL else "available",
                "reason": "Quality-first local model for daily news summaries and reminder parsing fallback.",
                "evidence": benchmark_evidence(main),
            },
            {
                "name": FAST_MODEL,
                "type": "local_llm_candidate",
                "installed": FAST_MODEL in installed,
                "status": "fast_candidate" if FAST_MODEL in installed else "download_gated",
                "reason": qwen3_reason(snap, installed),
                "evidence": benchmark_evidence(
                    latest_model_benchmark(FAST_MODEL, tasks={"news_summary"})
                    or latest_model_benchmark(FAST_MODEL, tasks={"model_storage_management"})
                ),
            },
            {
                "name": "rules",
                "type": "deterministic_fallback",
                "installed": True,
                "status": "selected" if selected_backend == "rules" else "fallback",
                "reason": "Fast deterministic fallback when Ollama is stopped or unavailable.",
                "evidence": {"elapsed_seconds": 0, "tokens_per_second": None},
            },
            {
                "name": "Isolation Forest",
                "type": "system_status_model",
                "installed": True,
                "status": "device_health_model",
                "reason": "Analyzes CPU, memory, disk, temperature, and network metrics; it is not a news summarizer.",
                "evidence": anomaly_evidence(db),
            },
        ],
    }


def resource_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    return {
        "memory_percent": round(vm.percent, 1),
        "memory_available_mb": round(vm.available / (1024**2), 1),
        "swap_percent": round(swap.percent, 1),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "ollama_running": ollama_running(),
    }


def installed_models() -> list[str]:
    models: set[str] = set()
    for root in MANIFEST_ROOTS:
        if not root.exists():
            continue
        for path in root.glob("*/*"):
            if path.is_file():
                models.add(f"{path.parent.name}:{path.name}")
    return sorted(models)


def latest_model_benchmark(model: str, *, tasks: set[str] | None = None) -> dict[str, Any] | None:
    selected = None
    data_dir = Path(__file__).resolve().parents[2] / "data"
    for path in (data_dir / "llm_benchmarks.jsonl", data_dir / "model_comparison.jsonl"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("model") == model and (tasks is None or record.get("task") in tasks):
                selected = record
    return selected


def benchmark_evidence(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {
            "ok": None,
            "elapsed_seconds": None,
            "tokens_per_second": None,
            "failure_reason": "No benchmark record yet.",
        }
    return {
        "ok": record.get("ok"),
        "elapsed_seconds": record.get("wall_seconds") or record.get("elapsed_seconds"),
        "tokens_per_second": record.get("eval_tokens_per_second") or record.get("tokens_per_second"),
        "failure_reason": clean_reason(record.get("failure_reason")),
    }


def clean_reason(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    for spinner in "⠋⠙⠹⠸⠼":
        text = text.replace(spinner, "")
    return " ".join(text.split())


def qwen3_reason(snapshot: dict[str, Any], installed: list[str]) -> str:
    if FAST_MODEL in installed:
        return "Installed as the fast local model candidate for short reminders and quick summaries."
    evidence = latest_model_benchmark(FAST_MODEL, tasks={"model_storage_management"})
    if evidence and evidence.get("failure_reason"):
        return "Download was attempted after freeing disk, but the Ollama registry TLS certificate could not be verified."
    if snapshot["disk_free_gb"] < MIN_QWEN3_DOWNLOAD_GB:
        return f"Not downloaded because free disk is below {MIN_QWEN3_DOWNLOAD_GB} GB."
    return "Download is allowed when disk space is sufficient."


def anomaly_evidence(db: Session | None) -> dict[str, Any]:
    if db is None:
        return {"samples_collected": None, "anomalies_24h": None}
    since = datetime.utcnow() - timedelta(hours=24)
    total = db.query(SystemMetric).count()
    anomalies = (
        db.query(SystemMetric)
        .filter(SystemMetric.timestamp >= since)
        .filter(SystemMetric.is_anomaly.is_(True))
        .count()
    )
    return {"samples_collected": total, "anomalies_24h": anomalies}
