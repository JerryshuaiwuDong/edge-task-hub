import json
import logging
import re
from datetime import datetime
from pathlib import Path

from app.external_sources.base import ExternalSource, ExternalTask
from app.external_sources.cron_display import cron_to_display

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/home/pi3/pi-automation-scheduler/config/tasks.json")
LOG_PATH = Path("/home/pi3/pi-automation-scheduler/logs/scheduler.log")

TYPE_MAP = {
    "system-report": "feishu_notify",
    "time-announcement": "feishu_notify",
    "static-message": "feishu_notify",
    "rss-news": "rss",
    "backup": "backup",
}


def _map_task_type(raw: str, task_id: str) -> str:
    if raw in TYPE_MAP:
        return TYPE_MAP[raw]
    if "rss" in task_id or "news" in task_id:
        return "rss"
    if "backup" in task_id:
        return "backup"
    return "unknown"


def _parse_log_runs(log_path: Path) -> dict[str, dict]:
    """Extract the latest run for each task id from scheduler.log."""
    if not log_path.is_file():
        return {}

    pending: dict[str, datetime] = {}
    results: dict[str, dict] = {}

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.warning("Cannot read pi-scheduler log: %s", exc)
        return {}

    for line in lines[-2000:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = row.get("message", "")
        meta = row.get("meta") or {}
        tid = meta.get("id")
        if not tid:
            continue

        ts_raw = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            ts = None

        if msg == "task started" and ts:
            pending[tid] = ts
        elif msg in ("task finished", "task failed"):
            status = "success" if msg == "task finished" else "failed"
            excerpt = line[:200]
            if msg == "task failed":
                err = meta.get("error", "")
                if err:
                    excerpt = f"failed: {err}"[:200]
            started = pending.get(tid, ts)
            if ts and (tid not in results or ts > results[tid].get("_ts", datetime.min)):
                results[tid] = {
                    "_ts": ts,
                    "last_run_at": started or ts,
                    "last_run_status": status,
                    "last_run_excerpt": excerpt,
                }

    for tid in list(results.keys()):
        results[tid].pop("_ts", None)
    return results


class PiSchedulerSource(ExternalSource):
    source_id = "pi-scheduler"
    source_label = "pi-automation-scheduler"
    source_color = "amber"
    config_path = str(CONFIG_PATH)

    def fetch_tasks(self) -> list[ExternalTask]:
        if not CONFIG_PATH.is_file():
            logger.warning("pi-automation-scheduler config not found: %s", CONFIG_PATH)
            return []

        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse tasks.json: %s", exc)
            return []

        task_list = data.get("tasks", [])
        if not isinstance(task_list, list):
            return []

        timezone = data.get("timezone", "Asia/Shanghai")
        log_runs = _parse_log_runs(LOG_PATH)
        out: list[ExternalTask] = []

        for entry in task_list:
            if not isinstance(entry, dict):
                continue
            tid = entry.get("id", "unknown")
            title = entry.get("title") or tid
            cron = entry.get("cron", "")
            raw_type = entry.get("type", "unknown")
            enabled = bool(entry.get("enabled", True))
            run_info = log_runs.get(tid, {})

            out.append(
                ExternalTask(
                    source_id=self.source_id,
                    source_label=self.source_label,
                    source_color=self.source_color,
                    name=title,
                    task_type=_map_task_type(raw_type, tid),
                    schedule_display=cron_to_display(cron),
                    schedule_raw=cron,
                    timezone=timezone,
                    enabled=enabled,
                    last_run_at=run_info.get("last_run_at"),
                    last_run_status=run_info.get("last_run_status", "unknown"),
                    last_run_excerpt=run_info.get("last_run_excerpt"),
                    config_path=str(CONFIG_PATH),
                    external_key=tid,
                )
            )
        return out
