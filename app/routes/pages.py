import json
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.database import get_db
from app.models import RunStatus, ScheduleKind, SystemMetric, Task, TaskRun
from app.schedule_form import build_schedule_from_form
from app.schedule_utils import format_schedule_label, get_dashboard_next_scheduled
from app.scheduler import register_task, remove_task, run_task_now
from app.external_sources.registry import (
    list_all_external_tasks,
    list_source_catalog,
    parse_pi_scheduler_recent_activity,
)
from app.task_form_helpers import task_form_schedule_defaults

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _parse_payload(
    task_type: str,
    message: str,
    feed_url: str,
    limit: int,
    summary_mode: str = "auto",
    notify: bool = True,
) -> dict:
    if task_type == "reminder":
        return {"message": message}
    if task_type == "rss_digest":
        return {
            "feed_url": feed_url,
            "limit": limit,
            "summary_mode": summary_mode or "auto",
            "notify": notify,
        }
    return {}


def _parse_summary_meta(output_text: str | None) -> dict[str, str]:
    if not output_text:
        return {}
    first_line = next((line.strip() for line in output_text.splitlines() if line.strip()), "")
    if not first_line.startswith("summary_mode="):
        return {}
    meta: dict[str, str] = {}
    for part in first_line.split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        meta[key.strip()] = value.strip()
    return meta


def _apply_schedule_to_task(task: Task, sched) -> None:
    task.schedule_kind = sched.schedule_kind
    task.schedule_mode = sched.schedule_mode
    task.cron_expr = sched.cron_expr
    task.schedule_simple_json = sched.schedule_simple_json
    task.run_at = sched.run_at


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    internal_active = db.query(Task).filter(Task.enabled.is_(True)).count()
    ext_tasks, _ = list_all_external_tasks()
    ext_active = sum(1 for t in ext_tasks if t.enabled)
    active_tasks = internal_active + ext_active
    runs_today = (
        db.query(TaskRun)
        .filter(TaskRun.started_at >= today_start)
        .filter(TaskRun.status != RunStatus.ANOMALY_ALERT.value)
        .count()
    )
    anomaly_runs_today = (
        db.query(TaskRun)
        .filter(TaskRun.started_at >= today_start)
        .filter(TaskRun.status == RunStatus.ANOMALY_ALERT.value)
        .count()
    )
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
        daily.append({"date": day.strftime("%a %m/%d"), "count": count})

    internal_count = db.query(Task).count()
    source_dist = [
        {"type": "Edge Task Hub", "count": internal_count, "color": "#4f46e5"},
        {"type": "pi-scheduler", "count": sum(1 for t in ext_tasks if t.source_id == "pi-scheduler"), "color": "#f59e0b"},
        {"type": "openclaw", "count": sum(1 for t in ext_tasks if t.source_id == "openclaw"), "color": "#8b5cf6"},
        {"type": "system-cron", "count": sum(1 for t in ext_tasks if t.source_id == "system-cron"), "color": "#64748b"},
    ]
    source_dist = [s for s in source_dist if s["count"] > 0] or source_dist

    recent_internal = [
        {
            "task_name": name,
            "source_id": "edge-task-hub",
            "source_label": "Edge Task Hub",
            "status": r.status,
            "started_at": r.started_at.isoformat() + "Z",
            "duration_ms": r.duration_ms,
        }
        for r, name in (
            db.query(TaskRun, Task.name)
            .join(Task, Task.id == TaskRun.task_id)
            .order_by(TaskRun.started_at.desc())
            .limit(15)
            .all()
        )
    ]
    recent_external = parse_pi_scheduler_recent_activity(15)
    merged_recent = sorted(
        recent_internal + recent_external,
        key=lambda x: x["started_at"],
        reverse=True,
    )[:10]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page_title": "Dashboard",
            "active_nav": "dashboard",
            "stats": {
                "active_tasks": active_tasks,
                "runs_today": runs_today,
                "anomaly_runs_today": anomaly_runs_today,
                "success_rate": success_rate,
                "next_scheduled": get_dashboard_next_scheduled(db, Task),
            },
            "daily_json": json.dumps(daily),
            "source_dist_json": json.dumps(source_dist),
            "recent_json": json.dumps(merged_recent),
        },
    )


def _build_unified_task_rows(db: Session) -> tuple[list[dict], list[dict]]:
    """Merge Edge Task Hub tasks and external scheduler tasks into table rows."""
    rows: list[dict] = []
    for t in (
        db.query(Task)
        .filter(Task.name != "__anomaly_monitor__")
        .order_by(Task.id.desc())
        .all()
    ):
        last = (
            db.query(TaskRun)
            .filter(TaskRun.task_id == t.id)
            .order_by(TaskRun.started_at.desc())
            .first()
        )
        last_at = last.started_at.strftime("%Y-%m-%d %H:%M") if last else None
        rows.append(
            {
                "source_id": "edge-task-hub",
                "source_label": "Edge Task Hub",
                "source_color": "indigo",
                "name": t.name,
                "task_type": t.task_type.replace("_", " "),
                "schedule_label": format_schedule_label(t),
                "enabled": t.enabled,
                "last_run_status": last.status if last else None,
                "last_run_at": last_at,
                "edit_url": f"/tasks/{t.id}/edit",
                "detail_url": f"/tasks/{t.id}",
                "run_url": f"/tasks/{t.id}/run",
                "use_ai": bool(t.use_ai),
                "task_id": t.id,
                "readonly": False,
                "modal": None,
            }
        )

    ext_tasks, warnings = list_all_external_tasks()
    for et in ext_tasks:
        last_at = et.last_run_at.strftime("%Y-%m-%d %H:%M") if et.last_run_at else None
        rows.append(
            {
                "source_id": et.source_id,
                "source_label": et.source_label,
                "source_color": et.source_color,
                "name": et.name,
                "task_type": et.task_type.replace("_", " "),
                "schedule_label": et.schedule_display,
                "enabled": et.enabled,
                "last_run_status": et.last_run_status,
                "last_run_at": last_at,
                "edit_url": None,
                "detail_url": None,
                "run_url": None,
                "readonly": True,
                "modal": {
                    "source_label": et.source_label,
                    "config_path": et.config_path,
                    "schedule_raw": et.schedule_raw,
                    "timezone": et.timezone,
                    "last_run_excerpt": et.last_run_excerpt,
                    "external_key": et.external_key,
                },
            }
        )
    warn_list = [{"source": w.source, "message": w.message} for w in warnings]
    return rows, warn_list


@router.get("/tasks", response_class=HTMLResponse)
def tasks_list(request: Request, db: Session = Depends(get_db)):
    unified_rows, warnings = _build_unified_task_rows(db)
    counts = {
        "all": len(unified_rows),
        "edge-task-hub": sum(1 for r in unified_rows if r["source_id"] == "edge-task-hub"),
        "pi-scheduler": sum(1 for r in unified_rows if r["source_id"] == "pi-scheduler"),
        "openclaw": sum(1 for r in unified_rows if r["source_id"] == "openclaw"),
        "system-cron": sum(1 for r in unified_rows if r["source_id"] == "system-cron"),
    }
    return templates.TemplateResponse(
        request,
        "tasks_list.html",
        {
            "page_title": "Tasks",
            "active_nav": "tasks",
            "unified_json": json.dumps(unified_rows),
            "warnings": warnings,
            "filter_counts": counts,
        },
    )


@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, db: Session = Depends(get_db)):
    ext_tasks, ext_warnings = list_all_external_tasks()
    internal_count = db.query(Task).count()
    internal_enabled = db.query(Task).filter(Task.enabled.is_(True)).count()
    catalog = list_source_catalog(ext_tasks, internal_count, internal_enabled)

    log_previews: dict[str, str] = {}
    pi_log = Path("/home/pi3/pi-automation-scheduler/logs/scheduler.log")
    if pi_log.is_file():
        try:
            log_previews["pi-scheduler"] = "\n".join(
                pi_log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            )
        except OSError:
            log_previews["pi-scheduler"] = "(unreadable)"

    ext_by_source: dict[str, list] = {}
    for t in ext_tasks:
        ext_by_source.setdefault(t.source_id, []).append(t)

    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "page_title": "Sources",
            "active_nav": "sources",
            "catalog": catalog,
            "warnings": ext_warnings,
            "log_previews": log_previews,
            "external_by_source": ext_by_source,
        },
    )


@router.get("/model-chat", response_class=HTMLResponse)
def model_chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "model_chat.html",
        {
            "page_title": "Model Chat",
            "active_nav": "model-chat",
        },
    )


@router.get("/model-router", response_class=HTMLResponse)
def model_router_page(request: Request):
    return templates.TemplateResponse(
        request,
        "model_router.html",
        {
            "page_title": "Model Router",
            "active_nav": "model-router",
        },
    )


@router.get("/tasks/new", response_class=HTMLResponse)
def task_new(
    request: Request,
    clone_from: int | None = Query(None),
    db: Session = Depends(get_db),
):
    clone_task = db.get(Task, clone_from) if clone_from else None
    sched = task_form_schedule_defaults(clone_task, clone=bool(clone_from))
    payload = {}
    name = ""
    task_type = "reminder"
    description = ""
    enabled = True
    if clone_task:
        payload = json.loads(clone_task.payload_json or "{}")
        name = f"{clone_task.name} (copy)"
        task_type = clone_task.task_type
        description = clone_task.description or ""
        enabled = True

    return templates.TemplateResponse(
        request,
        "task_form.html",
        {
            "page_title": "New Task",
            "active_nav": "tasks",
            "task": None,
            "payload": payload,
            "name": name,
            "task_type": task_type,
            "description": description,
            "enabled": enabled,
            "sched": sched,
            "use_ai": False,
            "form_action": "/tasks",
            "is_edit": False,
        },
    )


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit(request: Request, task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        return RedirectResponse("/tasks", status_code=302)
    sched = task_form_schedule_defaults(task)
    return templates.TemplateResponse(
        request,
        "task_form.html",
        {
            "page_title": "Edit Task",
            "active_nav": "tasks",
            "task": task,
            "payload": json.loads(task.payload_json or "{}"),
            "name": task.name,
            "task_type": task.task_type,
            "description": task.description or "",
            "enabled": task.enabled,
            "sched": sched,
            "use_ai": task.use_ai,
            "form_action": f"/tasks/{task_id}",
            "is_edit": True,
        },
    )


@router.post("/tasks")
def task_create(
    name: str = Form(...),
    description: str = Form(""),
    task_type: str = Form(...),
    schedule_kind: str = Form("recurring"),
    run_date: str = Form(""),
    run_time: str = Form(""),
    pattern: str = Form("daily"),
    daily_time: str = Form("08:00"),
    weekly_time: str = Form("09:00"),
    weekday: int = Form(1),
    every_hours: int = Form(1),
    every_minutes: int = Form(5),
    cron_expr: str = Form(""),
    timezone: str = Form("Asia/Shanghai"),
    message: str = Form(""),
    feed_url: str = Form("https://www.raspberrypi.com/news/feed/"),
    limit: int = Form(5),
    summary_mode: str = Form("auto"),
    notify: str = Form("on"),
    enabled: str = Form("on"),
    use_ai: str = Form(""),
    ai_prompt_template: str = Form(""),
    db: Session = Depends(get_db),
):
    sched = build_schedule_from_form(
        schedule_kind=schedule_kind,
        timezone=timezone,
        run_date=run_date,
        run_time=run_time,
        pattern=pattern,
        daily_time=daily_time,
        weekly_time=weekly_time,
        weekday=weekday,
        every_hours=every_hours,
        every_minutes=every_minutes,
        cron_expr=cron_expr,
    )
    task = Task(
        name=name,
        description=description,
        task_type=task_type,
        timezone=timezone,
        payload_json=json.dumps(
            _parse_payload(task_type, message, feed_url, limit, summary_mode, notify == "on")
        ),
        use_ai=use_ai == "on",
        ai_prompt_template=ai_prompt_template.strip() or None,
        enabled=enabled == "on",
    )
    _apply_schedule_to_task(task, sched)
    db.add(task)
    db.commit()
    db.refresh(task)
    if task.enabled:
        register_task(task)
    return RedirectResponse("/tasks", status_code=303)


@router.post("/tasks/{task_id}")
def task_update(
    task_id: int,
    name: str = Form(...),
    description: str = Form(""),
    task_type: str = Form(...),
    schedule_kind: str = Form("recurring"),
    run_date: str = Form(""),
    run_time: str = Form(""),
    pattern: str = Form("daily"),
    daily_time: str = Form("08:00"),
    weekly_time: str = Form("09:00"),
    weekday: int = Form(1),
    every_hours: int = Form(1),
    every_minutes: int = Form(5),
    cron_expr: str = Form(""),
    timezone: str = Form("Asia/Shanghai"),
    message: str = Form(""),
    feed_url: str = Form(""),
    limit: int = Form(5),
    summary_mode: str = Form("auto"),
    notify: str = Form("on"),
    enabled: str = Form("on"),
    use_ai: str = Form(""),
    ai_prompt_template: str = Form(""),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if not task:
        return RedirectResponse("/tasks", status_code=302)

    sched = build_schedule_from_form(
        schedule_kind=schedule_kind,
        timezone=timezone,
        run_date=run_date,
        run_time=run_time,
        pattern=pattern,
        daily_time=daily_time,
        weekly_time=weekly_time,
        weekday=weekday,
        every_hours=every_hours,
        every_minutes=every_minutes,
        cron_expr=cron_expr,
    )

    task.name = name
    task.description = description
    task.task_type = task_type
    task.timezone = timezone
    task.payload_json = json.dumps(
        _parse_payload(task_type, message, feed_url, limit, summary_mode, notify == "on")
    )
    task.use_ai = use_ai == "on"
    task.ai_prompt_template = ai_prompt_template.strip() or None
    task.enabled = enabled == "on"
    _apply_schedule_to_task(task, sched)
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    remove_task(task.id)
    if task.enabled:
        register_task(task)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/delete")
def task_delete(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task:
        remove_task(task_id)
        db.delete(task)
        db.commit()
    return RedirectResponse("/tasks", status_code=303)


@router.post("/tasks/{task_id}/run")
def task_run_page(task_id: int):
    run_task_now(task_id)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        return RedirectResponse("/tasks", status_code=302)
    runs = (
        db.query(TaskRun)
        .filter(TaskRun.task_id == task_id)
        .order_by(TaskRun.started_at.desc())
        .limit(50)
        .all()
    )
    week_start = datetime.utcnow() - timedelta(days=7)
    week_runs = [r for r in runs if r.started_at >= week_start]
    success = sum(1 for r in week_runs if r.status == RunStatus.SUCCESS.value)
    rate = round((success / len(week_runs)) * 100, 1) if week_runs else 100.0

    chart_days = []
    for i in range(6, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        chart_days.append(
            {
                "date": day.strftime("%a"),
                "success": sum(
                    1
                    for r in week_runs
                    if r.started_at.date() == day and r.status == RunStatus.SUCCESS.value
                ),
                "failed": sum(
                    1
                    for r in week_runs
                    if r.started_at.date() == day and r.status == RunStatus.FAILED.value
                ),
            }
        )

    show_one_time_banner = (
        task.schedule_kind == ScheduleKind.ONE_TIME.value
        and not task.enabled
        and len(runs) > 0
    )

    return templates.TemplateResponse(
        request,
        "task_detail.html",
        {
            "page_title": task.name,
            "active_nav": "tasks",
            "task": task,
            "payload": json.loads(task.payload_json or "{}"),
            "schedule_label": format_schedule_label(task),
            "runs": runs,
            "latest_run": runs[0] if runs else None,
            "latest_summary_meta": _parse_summary_meta(runs[0].output_text if runs else None),
            "success_rate": rate,
            "chart_json": json.dumps(chart_days),
            "show_one_time_banner": show_one_time_banner,
        },
    )


@router.get("/anomaly", response_class=HTMLResponse)
def anomaly_page(request: Request, db: Session = Depends(get_db)):
    from app.ai.anomaly_detector import IsolationForestDetector, sklearn_available
    from datetime import timedelta

    detector = IsolationForestDetector()
    total = db.query(SystemMetric).count()
    since = datetime.utcnow() - timedelta(hours=24)
    anomalies_24h = (
        db.query(SystemMetric)
        .filter(SystemMetric.timestamp >= since)
        .filter(SystemMetric.is_anomaly.is_(True))
        .count()
    )
    return templates.TemplateResponse(
        request,
        "anomaly.html",
        {
            "page_title": "Anomaly Detection",
            "active_nav": "anomaly",
            "sklearn_available": sklearn_available(),
            "model_trained": detector.model is not None,
            "samples_collected": total,
            "anomalies_24h": anomalies_24h,
        },
    )


@router.get("/system", response_class=HTMLResponse)
def system_page(request: Request):
    return templates.TemplateResponse(
        request,
        "system.html",
        {"page_title": "System Monitor", "active_nav": "system"},
    )


@router.get("/maintenance", response_class=HTMLResponse)
def maintenance_page(request: Request):
    return templates.TemplateResponse(
        request,
        "maintenance.html",
        {"page_title": "Maintenance Center", "active_nav": "maintenance"},
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    webhook_ok = settings.feishu_webhook_url not in ("", "REPLACE_ME")
    masked = "Configured" if webhook_ok else "Not configured"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "page_title": "Settings",
            "active_nav": "settings",
            "webhook_status": masked,
            "timezone": settings.default_timezone,
        },
    )
