from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytz


TIME_RE = r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)"
DATE_RE = r"(?P<date>\d{4}-\d{2}-\d{2})"


@dataclass(frozen=True)
class ReminderSpec:
    message: str
    schedule_kind: str
    cron_expr: str
    schedule_simple_json: dict[str, str]
    run_at: datetime | None
    timezone: str = "Asia/Shanghai"


def parse_reminder_command(
    text: str,
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Shanghai",
) -> ReminderSpec:
    clean = " ".join((text or "").strip().split())
    if not clean:
        raise ValueError("Message is empty.")

    tz = pytz.timezone(timezone or "Asia/Shanghai")
    local_now = _local_now(now, tz)
    lower = clean.lower()

    daily = re.match(
        rf"^(?:remind(?: me)?|reminder)\s+(?:every day|daily)\s+(?:at\s+)?{TIME_RE}\s+(?:to\s+)?(?P<message>.+)$",
        lower,
    )
    if daily:
        hour = int(daily.group("hour"))
        minute = int(daily.group("minute"))
        message = _extract_message(clean, daily.start("message"))
        return ReminderSpec(
            message=message,
            schedule_kind="recurring",
            cron_expr=f"{minute} {hour} * * *",
            schedule_simple_json={"pattern": "daily", "time": f"{hour:02d}:{minute:02d}"},
            run_at=None,
            timezone=timezone,
        )

    relative = re.match(
        rf"^(?:remind(?: me)?|reminder)\s+(?P<day>today|tomorrow)\s+(?:at\s+)?{TIME_RE}\s+(?:to\s+)?(?P<message>.+)$",
        lower,
    )
    if relative:
        target_day = local_now.date() + (timedelta(days=1) if relative.group("day") == "tomorrow" else timedelta())
        hour = int(relative.group("hour"))
        minute = int(relative.group("minute"))
        message = _extract_message(clean, relative.start("message"))
        return _one_time_spec(target_day, hour, minute, message, tz, timezone, local_now)

    absolute = re.match(
        rf"^(?:remind(?: me)?|reminder)\s+{DATE_RE}\s+(?:at\s+)?{TIME_RE}\s+(?:to\s+)?(?P<message>.+)$",
        lower,
    )
    if absolute:
        target_day = date.fromisoformat(absolute.group("date"))
        hour = int(absolute.group("hour"))
        minute = int(absolute.group("minute"))
        message = _extract_message(clean, absolute.start("message"))
        return _one_time_spec(target_day, hour, minute, message, tz, timezone, local_now)

    raise ValueError(
        "Use one of these formats: 'remind me tomorrow at 12:00 to eat lunch', "
        "'remind me every day at 23:30 to sleep', or "
        "'remind me 2026-05-29 at 12:00 to eat lunch'."
    )


def _local_now(now: datetime | None, tz) -> datetime:
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return tz.localize(now)
    return now.astimezone(tz)


def _extract_message(original: str, start_index: int) -> str:
    message = original[start_index:].strip()
    if message.lower().startswith("to "):
        message = message[3:].strip()
    if not message:
        raise ValueError("Reminder message is required.")
    return message


def _one_time_spec(
    target_day: date,
    hour: int,
    minute: int,
    message: str,
    tz,
    timezone: str,
    local_now: datetime,
) -> ReminderSpec:
    local_dt = tz.localize(datetime.combine(target_day, time(hour=hour, minute=minute)))
    if local_dt <= local_now:
        raise ValueError("Reminder time must be in the future.")
    run_at = local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
    return ReminderSpec(
        message=message,
        schedule_kind="one_time",
        cron_expr="",
        schedule_simple_json={},
        run_at=run_at,
        timezone=timezone,
    )
