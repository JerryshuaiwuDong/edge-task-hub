"""Default task-form values for edit and clone flows."""

import json

import pytz

from app.models import ScheduleKind


def task_form_schedule_defaults(task=None, *, clone: bool = False) -> dict:
    defaults = {
        "schedule_kind": ScheduleKind.RECURRING.value,
        "pattern": "daily",
        "run_date": "",
        "run_time": "",
        "daily_time": "08:00",
        "weekly_time": "09:00",
        "weekday": 1,
        "every_hours": 1,
        "every_minutes": 5,
        "cron_expr": "0 9 * * 1-5",
        "timezone": "Asia/Shanghai",
    }
    if not task:
        return defaults

    defaults["timezone"] = task.timezone or "Asia/Shanghai"

    if clone:
        return defaults

    kind = task.schedule_kind or ScheduleKind.RECURRING.value
    defaults["schedule_kind"] = kind

    if kind == ScheduleKind.ONE_TIME.value and task.run_at:
        tz = pytz.timezone(task.timezone or "Asia/Shanghai")
        local = pytz.UTC.localize(task.run_at).astimezone(tz)
        defaults["run_date"] = local.strftime("%Y-%m-%d")
        defaults["run_time"] = local.strftime("%H:%M")
        return defaults

    try:
        s = json.loads(task.schedule_simple_json or "{}")
    except json.JSONDecodeError:
        s = {}

    defaults["pattern"] = s.get("pattern") or s.get("type", "daily")
    if "time" in s:
        defaults["daily_time"] = s["time"]
        defaults["weekly_time"] = s["time"]
    elif "hour" in s:
        defaults["daily_time"] = f"{int(s.get('hour', 8)):02d}:{int(s.get('minute', 0)):02d}"
        defaults["weekly_time"] = defaults["daily_time"]
    defaults["weekday"] = int(s.get("weekday", s.get("day", 1)))
    defaults["every_hours"] = int(s.get("every_hours", s.get("interval", 1)))
    defaults["every_minutes"] = int(s.get("every_minutes", s.get("interval", 5)))
    defaults["cron_expr"] = s.get("cron_expr") or task.cron_expr or "0 9 * * 1-5"
    return defaults
