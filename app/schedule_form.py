"""Build schedule data from HTML form fields."""

import json
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException

from app.models import ScheduleKind
from app.schedule_utils import parse_run_at_local, pattern_to_cron, validate_cron


@dataclass
class ParsedSchedule:
    schedule_kind: str
    cron_expr: str | None
    schedule_simple_json: str
    run_at: datetime | None
    schedule_mode: str


def build_schedule_from_form(
    *,
    schedule_kind: str,
    timezone: str,
    run_date: str = "",
    run_time: str = "",
    pattern: str = "daily",
    daily_time: str = "08:00",
    weekly_time: str = "09:00",
    weekday: int = 1,
    every_hours: int = 1,
    every_minutes: int = 5,
    cron_expr: str = "",
) -> ParsedSchedule:
    if schedule_kind == ScheduleKind.ONE_TIME.value:
        try:
            run_at = parse_run_at_local(run_date, run_time, timezone)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ParsedSchedule(
            schedule_kind=ScheduleKind.ONE_TIME.value,
            cron_expr="",  # SQLite legacy schema: cron_expr NOT NULL
            schedule_simple_json=json.dumps(
                {"kind": "one_time", "run_date": run_date, "run_time": run_time}
            ),
            run_at=run_at,
            schedule_mode="simple",
        )

    fields: dict = {"pattern": pattern}
    if pattern == "daily":
        fields["time"] = daily_time
    elif pattern == "weekly":
        fields["time"] = weekly_time
        fields["weekday"] = weekday
    elif pattern == "hourly":
        fields["every_hours"] = every_hours
    elif pattern == "minutely":
        fields["every_minutes"] = every_minutes
    elif pattern == "cron":
        fields["cron_expr"] = cron_expr.strip()
        try:
            validate_cron(fields["cron_expr"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail=f"Unknown pattern: {pattern}")

    try:
        cron = pattern_to_cron(pattern, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mode = "advanced" if pattern == "cron" else "simple"
    return ParsedSchedule(
        schedule_kind=ScheduleKind.RECURRING.value,
        cron_expr=cron,
        schedule_simple_json=json.dumps(fields),
        run_at=None,
        schedule_mode=mode,
    )
