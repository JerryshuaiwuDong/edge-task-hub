import json
from typing import Callable

from app.models import Task, TaskType
from app.executors import reminder, rss_digest, system_status

EXECUTORS: dict[str, Callable] = {
    TaskType.REMINDER.value: reminder.run,
    TaskType.RSS_DIGEST.value: rss_digest.run,
    TaskType.SYSTEM_STATUS.value: system_status.run,
}


def run_task(task: Task) -> tuple[str, str, str]:
    """Return (status, output, error)."""
    fn = EXECUTORS.get(task.task_type)
    if not fn:
        return "failed", "", f"Unknown task type: {task.task_type}"
    try:
        payload = json.loads(task.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return fn(task, payload)
