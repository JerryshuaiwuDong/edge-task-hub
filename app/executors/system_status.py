from app.models import Task
from app.notifier import send_markdown
from app.system_monitor import get_snapshot


def run(task: Task, payload: dict) -> tuple[str, str, str]:
    snap = get_snapshot()
    temp = snap.get("cpu_temp_c")
    temp_line = f"**Temperature:** {temp}°C\n" if temp is not None else ""
    content = (
        f"**CPU:** {snap['cpu_percent']}%\n"
        f"**Memory:** {snap['memory_percent']}% "
        f"({snap['memory_used_gb']}/{snap['memory_total_gb']} GB)\n"
        f"**Disk:** {snap['disk_percent']}% "
        f"({snap['disk_used_gb']}/{snap['disk_total_gb']} GB)\n"
        f"{temp_line}"
        f"**Reported at:** {snap['timestamp']}"
    )
    ok, detail = send_markdown(task.name or "System Status", content)
    if ok:
        return "success", content + f"\n\n{detail}", ""
    return "failed", "", detail
