"""Schedule helpers for cron text, display labels, and next-run time."""

import json
from datetime import datetime
from typing import Any

import pytz
from croniter import croniter

from app.models import ScheduleKind


def parse_time_hhmm(time_str: str) -> tuple[int, int]:
    parts = (time_str or "08:00").strip().split(":")
    hour = int(parts[0]) if parts else 8
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour % 24, minute % 60


def pattern_to_cron(pattern: str, fields: dict[str, Any]) -> str:
    if pattern == "daily":
        hour, minute = parse_time_hhmm(fields.get("time", "08:00"))
        return f"{minute} {hour} * * *"
    if pattern == "weekly":
        hour, minute = parse_time_hhmm(fields.get("time", "09:00"))
        weekday = int(fields.get("weekday", 1))
        return f"{minute} {hour} * * {weekday}"
    if pattern == "hourly":
        n = max(1, min(24, int(fields.get("every_hours", 1))))
        return f"0 */{n} * * *"
    if pattern == "minutely":
        n = max(1, min(1440, int(fields.get("every_minutes", 5))))
        return f"*/{n} * * * *"
    if pattern == "cron":
        expr = (fields.get("cron_expr") or "").strip()
        if not expr:
            raise ValueError("Cron expression is required for custom cron pattern.")
        validate_cron(expr)
        return expr
    return simple_to_cron_legacy(fields)


def simple_to_cron_legacy(simple: dict[str, Any]) -> str:
    kind = simple.get("pattern") or simple.get("type", "daily")
    if kind == "daily":
        if "time" in simple:
            hour, minute = parse_time_hhmm(simple["time"])
        else:
            hour = int(simple.get("hour", 8))
            minute = int(simple.get("minute", 0))
        return f"{minute} {hour} * * *"
    if kind == "weekly":
        if "time" in simple:
            hour, minute = parse_time_hhmm(simple["time"])
        else:
            hour = int(simple.get("hour", 9))
            minute = int(simple.get("minute", 0))
        day = int(simple.get("weekday", simple.get("day", 1)))
        return f"{minute} {hour} * * {day}"
    if kind in ("minutely", "every_minutes"):
        interval = max(1, int(simple.get("every_minutes", simple.get("interval", 5))))
        return f"*/{interval} * * * *"
    if kind in ("hourly", "every_hours"):
        interval = max(1, int(simple.get("every_hours", simple.get("interval", 1))))
        return f"0 */{interval} * * *"
    if kind == "cron":
        return pattern_to_cron("cron", simple)
    raise ValueError(f"Unsupported schedule pattern: {kind}")


def simple_to_cron(simple: dict[str, Any]) -> str:
    if simple.get("pattern"):
        return pattern_to_cron(simple["pattern"], simple)
    return simple_to_cron_legacy(simple)


def validate_cron(expr: str) -> None:
    try:
        croniter(expr.strip())
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc


def format_schedule_label(task) -> str:
    kind = getattr(task, "schedule_kind", ScheduleKind.RECURRING.value) or ScheduleKind.RECURRING.value
    if kind == ScheduleKind.ONE_TIME.value:
        run_at = getattr(task, "run_at", None)
        if not run_at:
            return "One-time (not scheduled)"
        tz_name = task.timezone or "Asia/Shanghai"
        try:
            tz = pytz.timezone(tz_name)
            local = pytz.UTC.localize(run_at).astimezone(tz)
        except Exception:
            local = run_at
        return local.strftime("%Y-%m-%d %H:%M")

    cron = task.cron_expr or ""
    simple_json = task.schedule_simple_json or ""
    if simple_json:
        try:
            s = json.loads(simple_json)
            pattern = s.get("pattern") or s.get("type")
            if pattern == "daily":
                h, m = parse_time_hhmm(s.get("time", "08:00"))
                return f"Daily at {h:02d}:{m:02d}"
            if pattern == "weekly":
                days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
                wd = int(s.get("weekday", s.get("day", 1))) % 7
                h, m = parse_time_hhmm(s.get("time", "09:00"))
                return f"{days[wd]} at {h:02d}:{m:02d}"
            if pattern in ("hourly", "every_hours"):
                n = s.get("every_hours", s.get("interval", 1))
                return f"Every {n} hour{'s' if int(n) != 1 else ''}"
            if pattern in ("minutely", "every_minutes"):
                n = s.get("every_minutes", s.get("interval", 5))
                return f"Every {n} minutes"
            if pattern == "cron":
                return f"Cron: {s.get('cron_expr', cron)}"
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return cron or "—"


def cron_to_label(cron_expr: str | None, simple_json: str = "") -> str:
    class _T:
        schedule_kind = ScheduleKind.RECURRING.value
        cron_expr = cron_expr or ""
        schedule_simple_json = simple_json
        timezone = "Asia/Shanghai"
        run_at = None

    return format_schedule_label(_T())


def parse_run_at_local(run_date: str, run_time: str, timezone: str) -> datetime:
    if not run_date or not run_time:
        raise ValueError("Date and time are required for one-time tasks.")
    tz = pytz.timezone(timezone or "Asia/Shanghai")
    naive = datetime.strptime(f"{run_date} {run_time}", "%Y-%m-%d %H:%M")
    local_dt = tz.localize(naive)
    if local_dt <= datetime.now(tz):
        raise ValueError("One-time run time must be in the future.")
    return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)


def format_next_run_display(task, next_utc: datetime) -> str:
    if task.schedule_kind == ScheduleKind.ONE_TIME.value:
        tz = pytz.timezone(task.timezone or "Asia/Shanghai")
        local = pytz.UTC.localize(next_utc).astimezone(tz)
        return local.strftime("%a, %b %d at %H:%M")
    return format_schedule_label(task)


def get_next_run_utc(task, *, after: datetime | None = None) -> datetime | None:
    after = after or datetime.utcnow()
    if not task.enabled:
        return None
    if task.schedule_kind == ScheduleKind.ONE_TIME.value:
        if task.run_at and task.run_at > after:
            return task.run_at
        return None
    cron = (task.cron_expr or "").strip()
    if not cron:
        return None
    try:
        tz = pytz.timezone(task.timezone or "Asia/Shanghai")
        base = pytz.UTC.localize(after).astimezone(tz)
        itr = croniter(cron, base)
        nxt = itr.get_next(datetime)
        return nxt.astimezone(pytz.UTC).replace(tzinfo=None)
    except Exception:
        return None


def get_dashboard_next_scheduled(db, task_model) -> str:
    tasks = db.query(task_model).filter(task_model.enabled.is_(True)).all()
    best: tuple[datetime, object] | None = None
    for t in tasks:
        nxt = get_next_run_utc(t)
        if nxt and (best is None or nxt < best[0]):
            best = (nxt, t)
    if not best:
        return "—"
    return format_next_run_display(best[1], best[0])
