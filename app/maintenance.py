"""Resource-aware project maintenance helpers."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil

from app.config import BASE_DIR, DATA_DIR
from app.database import SessionLocal
from app.models import SystemMetric, TaskRun

logger = logging.getLogger(__name__)

LOG_PATH = DATA_DIR / "maintenance_log.jsonl"
RETENTION_DAYS = 7
AUTO_COOLDOWN_SECONDS = 6 * 60 * 60
MEMORY_AUTO_THRESHOLD = 85.0
DISK_AUTO_THRESHOLD = 90.0
ANOMALY_MEMORY_THRESHOLD = 80.0
SAFE_CLEAN_ROOTS = [BASE_DIR / "app", BASE_DIR / "scripts"]


def snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    proc = psutil.Process()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
        "memory_percent": round(vm.percent, 1),
        "memory_available_mb": round(vm.available / (1024**2), 1),
        "memory_used_mb": round(vm.used / (1024**2), 1),
        "swap_percent": round(swap.percent, 1),
        "swap_used_mb": round(swap.used / (1024**2), 1),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "cpu_temp_c": _read_temp_c(),
        "edge_task_hub_rss_mb": round(proc.memory_info().rss / (1024**2), 1),
        "ollama_rss_mb": _process_rss_mb("ollama"),
    }


def get_status(db) -> dict[str, Any]:
    logs = read_logs(limit=20)
    last_auto = next((entry for entry in logs if entry.get("trigger") == "auto"), None)
    return {
        "snapshot": snapshot(),
        "policy": {
            "mode": "conservative_auto_project_cleanup",
            "retention_days": RETENTION_DAYS,
            "auto_cooldown_hours": round(AUTO_COOLDOWN_SECONDS / 3600, 1),
            "memory_auto_threshold": MEMORY_AUTO_THRESHOLD,
            "disk_auto_threshold": DISK_AUTO_THRESHOLD,
            "anomaly_memory_threshold": ANOMALY_MEMORY_THRESHOLD,
            "safe_roots": [str(path.relative_to(BASE_DIR)) for path in SAFE_CLEAN_ROOTS],
            "forbidden_actions": [
                "drop_caches",
                "swapoff",
                "system directory cleanup",
                "automatic process kill",
                "automatic service restart",
            ],
        },
        "last_auto_cleanup": last_auto,
        "preview": build_preview(db),
        "recent_logs": logs,
    }


def build_preview(db) -> dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    pycache_dirs = _find_pycache_dirs()
    pycache_stats = [_path_stats(path) for path in pycache_dirs]
    old_metrics = db.query(SystemMetric).filter(SystemMetric.timestamp < cutoff).count()
    old_runs = db.query(TaskRun).filter(TaskRun.started_at < cutoff).count()
    estimated_bytes = sum(item["bytes"] for item in pycache_stats)
    return {
        "cutoff_utc": cutoff.isoformat() + "Z",
        "estimated_bytes": estimated_bytes,
        "estimated_mb": round(estimated_bytes / (1024**2), 3),
        "pycache_dirs": [
            {
                "path": _rel(path),
                "files": stats["files"],
                "bytes": stats["bytes"],
            }
            for path, stats in zip(pycache_dirs, pycache_stats)
        ],
        "old_system_metrics": old_metrics,
        "old_task_runs": old_runs,
        "actions": [
            "delete Python __pycache__ directories under app/ and scripts/",
            f"delete system_metrics older than {RETENTION_DAYS} days",
            f"delete task_runs older than {RETENTION_DAYS} days",
        ],
    }


def run_cleanup(db, *, trigger: str, confirmed: bool = False, reason: str | None = None) -> dict[str, Any]:
    if trigger == "manual" and not confirmed:
        raise ValueError("Manual cleanup requires confirm=true")

    started = time.monotonic()
    before = snapshot()
    preview = build_preview(db)
    errors: list[str] = []
    deleted_dirs = 0
    deleted_files = 0
    deleted_bytes = 0

    for item in preview["pycache_dirs"]:
        path = (BASE_DIR / item["path"]).resolve()
        if not _safe_cleanup_path(path):
            errors.append(f"refused unsafe path: {path}")
            continue
        try:
            shutil.rmtree(path)
            deleted_dirs += 1
            deleted_files += int(item["files"])
            deleted_bytes += int(item["bytes"])
        except OSError as exc:
            errors.append(f"{_rel(path)}: {exc}")

    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    try:
        old_metrics = (
            db.query(SystemMetric)
            .filter(SystemMetric.timestamp < cutoff)
            .delete(synchronize_session=False)
        )
        old_runs = (
            db.query(TaskRun)
            .filter(TaskRun.started_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive DB rollback
        db.rollback()
        old_metrics = 0
        old_runs = 0
        errors.append(f"database cleanup failed: {exc}")

    after = snapshot()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "reason": reason or "manual project maintenance",
        "status": "partial" if errors else "success",
        "duration_ms": round((time.monotonic() - started) * 1000),
        "before": before,
        "after": after,
        "preview": preview,
        "result": {
            "deleted_pycache_dirs": deleted_dirs,
            "deleted_files": deleted_files,
            "deleted_bytes": deleted_bytes,
            "deleted_mb": round(deleted_bytes / (1024**2), 3),
            "deleted_system_metrics": old_metrics,
            "deleted_task_runs": old_runs,
        },
        "errors": errors,
    }
    append_log(entry)
    return entry


def maybe_auto_cleanup(metric: SystemMetric | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        decision = auto_cleanup_decision(metric)
        if not decision["should_run"]:
            return {"ran": False, **decision}
        result = run_cleanup(db, trigger="auto", confirmed=True, reason="; ".join(decision["reasons"]))
        return {"ran": True, **decision, "cleanup": result}
    finally:
        db.close()


def auto_cleanup_decision(metric: SystemMetric | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    last_auto = _last_auto_log()
    if last_auto:
        last_ts = _parse_ts(last_auto.get("timestamp"))
        if last_ts and (now - last_ts).total_seconds() < AUTO_COOLDOWN_SECONDS:
            return {
                "should_run": False,
                "reasons": [],
                "blocked_by_cooldown": True,
                "last_auto_cleanup": last_auto,
            }

    snap = snapshot()
    reasons: list[str] = []
    if snap["memory_percent"] >= MEMORY_AUTO_THRESHOLD:
        reasons.append(f"memory {snap['memory_percent']}% >= {MEMORY_AUTO_THRESHOLD}%")
    if snap["disk_percent"] >= DISK_AUTO_THRESHOLD:
        reasons.append(f"disk {snap['disk_percent']}% >= {DISK_AUTO_THRESHOLD}%")
    if metric and metric.is_anomaly and float(metric.mem) >= ANOMALY_MEMORY_THRESHOLD:
        reasons.append(f"anomaly with memory {metric.mem:.1f}% >= {ANOMALY_MEMORY_THRESHOLD}%")

    return {
        "should_run": bool(reasons),
        "reasons": reasons,
        "blocked_by_cooldown": False,
        "last_auto_cleanup": last_auto,
    }


def explain_with_ollama(db) -> dict[str, Any]:
    from app.ai.model_runtime import generate_ollama

    status = get_status(db)
    snap = status["snapshot"]
    preview = status["preview"]
    prompt = "\n".join(
        [
            "You are explaining Raspberry Pi edge-device resource status.",
            "Use simple English. Do not recommend unsafe system cleanup.",
            "Explain the likely resource pressure and whether project-only cleanup is useful.",
            f"CPU: {snap['cpu_percent']}%",
            f"Memory: {snap['memory_percent']}%, available {snap['memory_available_mb']} MB",
            f"Swap: {snap['swap_percent']}%, used {snap['swap_used_mb']} MB",
            f"Disk: {snap['disk_percent']}%, free {snap['disk_free_gb']} GB",
            f"Temperature: {snap['cpu_temp_c']}",
            f"Ollama RSS memory: {snap['ollama_rss_mb']} MB",
            f"Project cleanup preview: {preview['estimated_mb']} MB, "
            f"{preview['old_system_metrics']} old metric rows, {preview['old_task_runs']} old task runs.",
            "Return 3 short bullets: status, safe action, limitation.",
        ]
    )
    result = generate_ollama(prompt, max_tokens=128, timeout=20)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": "llm_explain",
        "status": "success" if result.ok else "failed",
        "model": result.model,
        "elapsed_seconds": result.elapsed_seconds,
        "error": result.error,
        "text": result.text,
    }
    append_log(entry)
    return {"ok": result.ok, "explanation": result.text, "model": result.model, "error": result.error, "elapsed_seconds": result.elapsed_seconds}


def read_logs(*, limit: int = 20) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows[-limit:]))


def append_log(entry: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _find_pycache_dirs() -> list[Path]:
    dirs: list[Path] = []
    for root in SAFE_CLEAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("__pycache__"):
            if path.is_dir() and not path.is_symlink() and _safe_cleanup_path(path):
                dirs.append(path.resolve())
    return sorted(set(dirs))


def _path_stats(path: Path) -> dict[str, int]:
    files = 0
    total = 0
    for root, _, names in os.walk(path):
        for name in names:
            file_path = Path(root) / name
            if file_path.is_symlink():
                continue
            try:
                total += file_path.stat().st_size
                files += 1
            except OSError:
                continue
    return {"files": files, "bytes": total}


def _safe_cleanup_path(path: Path) -> bool:
    resolved = path.resolve()
    if resolved.name != "__pycache__":
        return False
    return any(_is_relative_to(resolved, root.resolve()) for root in SAFE_CLEAN_ROOTS)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except ValueError:
        return str(path)


def _read_temp_c() -> float | None:
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
        return round(int(raw) / 1000.0, 1)
    except (OSError, ValueError):
        return None


def _process_rss_mb(name_part: str) -> float:
    total = 0
    for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
        try:
            name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name_part.lower() in name.lower() or name_part.lower() in cmdline.lower():
                total += proc.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    return round(total / (1024**2), 1)


def _last_auto_log() -> dict[str, Any] | None:
    return next((entry for entry in read_logs(limit=100) if entry.get("trigger") == "auto"), None)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
