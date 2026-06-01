import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from app.external_sources.base import ExternalSource, ExternalTask, SourceInfo, SourceWarning
from app.external_sources.openclaw import OpenClawSource
from app.external_sources.pi_scheduler import LOG_PATH as PI_LOG_PATH
from app.external_sources.pi_scheduler import PiSchedulerSource
from app.external_sources.system_cron import SystemCronSource

logger = logging.getLogger(__name__)

SOURCES: list[ExternalSource] = [
    PiSchedulerSource(),
    OpenClawSource(),
    SystemCronSource(),
]


def list_all_external_tasks() -> tuple[list[ExternalTask], list[SourceWarning]]:
    tasks: list[ExternalTask] = []
    warnings: list[SourceWarning] = []
    for source in SOURCES:
        try:
            tasks.extend(source.fetch_tasks())
            warnings.extend(source.fetch_warnings())
        except Exception as exc:
            logger.exception("External source %s failed", source.source_id)
            warnings.append(
                SourceWarning(
                    source=source.source_id,
                    message=str(exc)[:200],
                )
            )
    return tasks, warnings


def summarize_external(tasks: list[ExternalTask]) -> dict:
    by_source: dict[str, int] = {}
    enabled = 0
    for t in tasks:
        by_source[t.source_id] = by_source.get(t.source_id, 0) + 1
        if t.enabled:
            enabled += 1
    return {
        "by_source": by_source,
        "total": len(tasks),
        "enabled": enabled,
    }


def _systemd_user_status(unit: str) -> tuple[str, str]:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
        )
        status = (r.stdout or r.stderr or "unknown").strip()
        return status, f"systemd user unit: {unit}"
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return "unknown", str(exc)


def _openclaw_gateway_active() -> tuple[str, str]:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 18789), timeout=0.5):
            return "active", "Gateway listening on 127.0.0.1:18789"
    except OSError:
        return "inactive", "Gateway not reachable on 127.0.0.1:18789"


def list_source_catalog(
    external_tasks: list[ExternalTask],
    internal_count: int,
    internal_enabled: int,
) -> list[SourceInfo]:
    ext_by = {}
    ext_enabled = {}
    for t in external_tasks:
        ext_by[t.source_id] = ext_by.get(t.source_id, 0) + 1
        if t.enabled:
            ext_enabled[t.source_id] = ext_enabled.get(t.source_id, 0) + 1

    pi_status, pi_detail = _systemd_user_status("pi-automation-scheduler.service")
    oc_status, oc_detail = _openclaw_gateway_active()

    catalog = [
        SourceInfo(
            source_id="edge-task-hub",
            source_label="Edge Task Hub",
            source_color="indigo",
            status="active",
            status_detail="Managed by this application",
            task_count=internal_count,
            enabled_count=internal_enabled,
            config_path="/home/pi3/edge-task-hub/data/edge_task_hub.db",
            log_path=None,
            service_unit="edge-task-hub.service",
            readonly=False,
        ),
        SourceInfo(
            source_id="pi-scheduler",
            source_label="pi-automation-scheduler",
            source_color="amber",
            status=pi_status,
            status_detail=pi_detail,
            task_count=ext_by.get("pi-scheduler", 0),
            enabled_count=ext_enabled.get("pi-scheduler", 0),
            config_path="/home/pi3/pi-automation-scheduler/config/tasks.json",
            log_path=str(PI_LOG_PATH),
            service_unit="pi-automation-scheduler.service",
            readonly=True,
        ),
        SourceInfo(
            source_id="openclaw",
            source_label="OpenClaw",
            source_color="violet",
            status=oc_status,
            status_detail=oc_detail + " · cron via CLI",
            task_count=ext_by.get("openclaw", 0),
            enabled_count=ext_enabled.get("openclaw", 0),
            config_path="/home/pi3/.openclaw/openclaw.json",
            log_path="/tmp/openclaw/",
            service_unit="openclaw-gateway.service",
            readonly=True,
        ),
        SourceInfo(
            source_id="system-cron",
            source_label="System crontab",
            source_color="slate",
            status="active",
            status_detail="User crontab for pi3",
            task_count=ext_by.get("system-cron", 0),
            enabled_count=ext_enabled.get("system-cron", 0),
            config_path="crontab -l",
            log_path=None,
            service_unit=None,
            readonly=True,
        ),
    ]
    return catalog


def parse_pi_scheduler_recent_activity(limit: int = 20) -> list[dict]:
    """Parse recent pi-scheduler log activity for the merged dashboard view."""
    path = PI_LOG_PATH
    if not path.is_file():
        return []

    entries: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
    except OSError:
        return []

    names: dict[str, str] = {}
    try:
        import json as _json
        from pathlib import Path as P

        cfg = P("/home/pi3/pi-automation-scheduler/config/tasks.json")
        if cfg.is_file():
            data = _json.loads(cfg.read_text())
            for t in data.get("tasks", []):
                names[t.get("id", "")] = t.get("title", t.get("id", ""))
    except Exception:
        pass

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = row.get("message", "")
        if msg not in ("task finished", "task failed", "task started"):
            continue
        meta = row.get("meta") or {}
        tid = meta.get("id", "?")
        ts_raw = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        status = "running"
        if msg == "task finished":
            status = "success"
        elif msg == "task failed":
            status = "failed"
        entries.append(
            {
                "task_name": names.get(tid, tid),
                "source_id": "pi-scheduler",
                "source_label": "pi-scheduler",
                "status": status,
                "started_at": ts.isoformat() + "Z",
                "duration_ms": None,
            }
        )
        if len(entries) >= limit:
            break
    return entries
