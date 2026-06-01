"""Convert cron expressions into readable English labels."""


def cron_to_display(cron: str) -> str:
    parts = (cron or "").strip().split()
    if len(parts) != 5:
        return cron or "—"

    minute, hour, dom, month, dow = parts

    if minute.startswith("*/"):
        n = minute[2:]
        return f"Every {n} minutes"
    if hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
        n = hour[2:]
        return f"Every {n} hours"
    if dom == "*" and month == "*" and dow == "*" and minute.isdigit():
        if "-" in hour and not hour.startswith("*/"):
            return f"Hourly during {hour} (at :{minute.zfill(2)})"
        if hour.isdigit():
            return f"Daily at {int(hour):02d}:{int(minute):02d}"
    if dom == "*" and month == "*" and dow in ("1-5", "MON-FRI"):
        if minute.isdigit() and hour.isdigit():
            return f"Weekdays at {int(hour):02d}:{int(minute):02d}"
    if dom == "*" and month == "*" and dow.isdigit() and minute.isdigit() and hour.isdigit():
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        d = days[int(dow) % 7]
        return f"Every {d} at {int(hour):02d}:{int(minute):02d}"
    if "," in hour and dom == "*" and month == "*":
        return f"Twice daily ({hour} UTC, min {minute})"
    if "-" in hour and dom == "*" and month == "*" and dow == "*":
        return f"Hours {hour} (at :{minute.zfill(2)})"

    return cron
