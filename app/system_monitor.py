import socket
import subprocess
import time
from collections import deque
from datetime import datetime, timezone

import psutil

from app.config import settings

# Five-second sampling keeps about one hour of points in memory.
CPU_RING: deque[dict] = deque(maxlen=720)
_last_sample_ts = 0.0


def _read_cpu_temp_c() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except OSError:
        return None


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _systemd_user_active(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def sample_cpu_ring():
    global _last_sample_ts
    now = time.time()
    if now - _last_sample_ts < 5:
        return
    _last_sample_ts = now
    CPU_RING.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cpu_percent": psutil.cpu_percent(interval=None),
        }
    )


def get_snapshot() -> dict:
    sample_cpu_ring()
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
        "memory_percent": round(vm.percent, 1),
        "memory_used_gb": round(vm.used / (1024**3), 2),
        "memory_total_gb": round(vm.total / (1024**3), 2),
        "disk_percent": round(disk.percent, 1),
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "cpu_temp_c": _read_cpu_temp_c(),
    }


def get_cpu_history() -> list[dict]:
    sample_cpu_ring()
    return list(CPU_RING)


def get_services_status() -> list[dict]:
    return [
        {
            "name": "Ollama",
            "port": 11434,
            "status": "running" if _port_open("127.0.0.1", 11434) else "stopped",
            "detail": "127.0.0.1:11434",
            "configured": settings.enable_ollama,
        },
        {
            "name": "OpenClaw",
            "port": 18789,
            "status": "running" if _port_open("127.0.0.1", 18789) else "stopped",
            "detail": "127.0.0.1:18789",
            "configured": settings.enable_openclaw,
        },
        {
            "name": "pi-automation-scheduler",
            "port": None,
            "status": _systemd_user_active("pi-automation-scheduler.service"),
            "detail": "systemd user unit",
            "configured": False,
        },
    ]
