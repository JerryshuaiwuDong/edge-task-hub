"""AI prompt variable replacement."""

from datetime import datetime

import pytz


def render_prompt(template: str, task_name: str, timezone: str = "Asia/Shanghai") -> str:
    try:
        tz = pytz.timezone(timezone or "Asia/Shanghai")
        now = datetime.now(tz)
    except Exception:
        now = datetime.utcnow()
    weekday = now.strftime("%A")
    return (
        template.replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H:%M"))
        .replace("{weekday}", weekday)
        .replace("{task_name}", task_name or "Task")
    )
