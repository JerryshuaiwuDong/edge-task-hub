import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RunStatus, Task, TaskRun
from app.schedule_utils import format_schedule_label, get_dashboard_next_scheduled
from app.scheduler import register_task, remove_task, run_task_now
from app.schemas import TaskCreate, TaskOut, TaskRunOut, TaskUpdate, ToggleRequest

router = APIRouter(prefix="/api", tags=["tasks"])


def _task_to_out(task: Task, db: Session) -> TaskOut:
    last = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc())
        .first()
    )
    simple = {}
    try:
        simple = json.loads(task.schedule_simple_json or "{}")
    except json.JSONDecodeError:
        pass
    payload = {}
    try:
        payload = json.loads(task.payload_json or "{}")
    except json.JSONDecodeError:
        pass
    return TaskOut(
        id=task.id,
        name=task.name,
        description=task.description,
        task_type=task.task_type,
        schedule_kind=task.schedule_kind or "recurring",
        schedule_mode=task.schedule_mode,
        cron_expr=task.cron_expr,
        schedule_simple_json=simple,
        run_at=task.run_at,
        timezone=task.timezone,
        payload_json=payload,
        use_ai=task.use_ai,
        ai_prompt_template=task.ai_prompt_template,
        enabled=task.enabled,
        created_at=task.created_at,
        updated_at=task.updated_at,
        schedule_label=format_schedule_label(task),
        last_run_at=last.started_at if last else None,
        last_run_status=last.status if last else None,
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    tasks = (
        db.query(Task)
        .filter(Task.name != "__anomaly_monitor__")
        .order_by(Task.id.desc())
        .all()
    )
    return [_task_to_out(t, db) for t in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    try:
        validated = TaskCreate.model_validate(body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()[0]["msg"]) from exc

    payload = validated.payload_json if isinstance(validated.payload_json, dict) else {}
    simple = validated.schedule_simple_json if isinstance(validated.schedule_simple_json, dict) else {}

    task = Task(
        name=validated.name,
        description=validated.description,
        task_type=validated.task_type,
        schedule_kind=validated.schedule_kind,
        schedule_mode=validated.schedule_mode,
        cron_expr=validated.cron_expr or "",
        schedule_simple_json=json.dumps(simple),
        run_at=validated.run_at,
        timezone=validated.timezone,
        payload_json=json.dumps(payload),
        use_ai=validated.use_ai,
        ai_prompt_template=validated.ai_prompt_template,
        enabled=validated.enabled,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if task.enabled:
        register_task(task)
    return _task_to_out(task, db)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _task_to_out(task, db)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    data = body.model_dump(exclude_unset=True)
    merged = {
        "name": data.get("name", task.name),
        "description": data.get("description", task.description),
        "task_type": data.get("task_type", task.task_type),
        "schedule_kind": data.get("schedule_kind", task.schedule_kind or "recurring"),
        "schedule_mode": data.get("schedule_mode", task.schedule_mode),
        "cron_expr": data.get("cron_expr", task.cron_expr),
        "schedule_simple_json": data.get(
            "schedule_simple_json", json.loads(task.schedule_simple_json or "{}")
        ),
        "run_at": data.get("run_at", task.run_at),
        "timezone": data.get("timezone", task.timezone),
        "payload_json": data.get("payload_json", json.loads(task.payload_json or "{}")),
        "use_ai": data.get("use_ai", task.use_ai),
        "ai_prompt_template": data.get("ai_prompt_template", task.ai_prompt_template),
        "enabled": data.get("enabled", task.enabled),
    }
    try:
        validated = TaskCreate.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()[0]["msg"]) from exc

    task.name = validated.name
    task.description = validated.description
    task.task_type = validated.task_type
    task.schedule_kind = validated.schedule_kind
    task.schedule_mode = validated.schedule_mode
    task.cron_expr = validated.cron_expr
    task.schedule_simple_json = json.dumps(
        validated.schedule_simple_json if isinstance(validated.schedule_simple_json, dict) else {}
    )
    task.run_at = validated.run_at
    task.timezone = validated.timezone
    if "payload_json" in data:
        task.payload_json = json.dumps(
            validated.payload_json if isinstance(validated.payload_json, dict) else {}
        )
    if "enabled" in data:
        task.enabled = validated.enabled
    if "use_ai" in data:
        task.use_ai = validated.use_ai
    if "ai_prompt_template" in data:
        task.ai_prompt_template = validated.ai_prompt_template
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    remove_task(task.id)
    if task.enabled:
        register_task(task)
    return _task_to_out(task, db)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    remove_task(task_id)
    db.delete(task)
    db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/toggle", response_model=TaskOut)
def toggle_task(
    task_id: int,
    body: ToggleRequest | None = None,
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    body = body or ToggleRequest()
    task.enabled = body.enabled if body.enabled is not None else not task.enabled
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    remove_task(task.id)
    if task.enabled:
        register_task(task)
    return _task_to_out(task, db)


@router.post("/tasks/{task_id}/run")
def run_now(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    run_task_now(task_id)
    return {"ok": True, "message": "Task execution started."}


@router.get("/tasks/{task_id}/runs", response_model=list[TaskRunOut])
def list_runs(task_id: int, limit: int = 50, db: Session = Depends(get_db)):
    if not db.get(Task, task_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    runs = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task_id)
        .order_by(TaskRun.started_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return runs


@router.get("/stats/dashboard")
def dashboard_stats(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    from app.external_sources.registry import list_all_external_tasks

    internal_active = db.query(Task).filter(Task.enabled.is_(True)).count()
    ext_tasks, _ = list_all_external_tasks()
    ext_active = sum(1 for t in ext_tasks if t.enabled)
    active_tasks = internal_active + ext_active
    runs_today = db.query(TaskRun).filter(TaskRun.started_at >= today_start).count()
    week_runs = db.query(TaskRun).filter(TaskRun.started_at >= week_start).all()
    success_week = sum(1 for r in week_runs if r.status == RunStatus.SUCCESS.value)
    success_rate = round((success_week / len(week_runs)) * 100, 1) if week_runs else 100.0

    daily = []
    for i in range(6, -1, -1):
        day = (today_start - timedelta(days=i)).date()
        day_end = day + timedelta(days=1)
        count = (
            db.query(TaskRun)
            .filter(TaskRun.started_at >= datetime.combine(day, datetime.min.time()))
            .filter(TaskRun.started_at < datetime.combine(day_end, datetime.min.time()))
            .count()
        )
        daily.append({"date": day.isoformat(), "count": count})

    type_rows = db.query(Task.task_type, func.count(Task.id)).group_by(Task.task_type).all()
    type_dist = [{"type": t, "count": c} for t, c in type_rows]

    recent = (
        db.query(TaskRun, Task.name)
        .join(Task, Task.id == TaskRun.task_id)
        .order_by(TaskRun.started_at.desc())
        .limit(10)
        .all()
    )
    recent_activity = [
        {
            "task_id": r.task_id,
            "task_name": name,
            "status": r.status,
            "started_at": r.started_at.isoformat() + "Z",
            "duration_ms": r.duration_ms,
        }
        for r, name in recent
    ]

    return {
        "active_tasks": active_tasks,
        "runs_today": runs_today,
        "success_rate": success_rate,
        "next_scheduled": get_dashboard_next_scheduled(db, Task),
        "daily_executions": daily,
        "type_distribution": type_dist,
        "recent_activity": recent_activity,
    }
