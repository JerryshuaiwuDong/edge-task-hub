import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from pytz import timezone as pytz_timezone

from app.config import settings
from app.database import SessionLocal
from app.executors import run_task
from app.models import RunStatus, ScheduleKind, Task, TaskRun

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_job_ids: dict[int, str] = {}

AUTO_DISABLE_MSG = "Auto-disabled after one-time execution"


def _execute_task(task_id: int):
    db = SessionLocal()
    run = TaskRun(task_id=task_id, status=RunStatus.RUNNING.value, started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    task = db.get(Task, task_id)
    if not task or not task.enabled:
        run.status = RunStatus.FAILED.value
        run.error_text = "Task not found or disabled."
        run.finished_at = datetime.utcnow()
        db.commit()
        db.close()
        return

    is_one_time = task.schedule_kind == ScheduleKind.ONE_TIME.value

    try:
        status, output, error = run_task(task)
        run.status = status
        run.output_text = output or ""
        run.error_text = error or ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("Task %s execution failed", task_id)
        run.status = RunStatus.FAILED.value
        run.error_text = str(exc)
    finally:
        run.finished_at = datetime.utcnow()
        run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

        if is_one_time:
            task.enabled = False
            task.updated_at = datetime.utcnow()
            if run.output_text:
                run.output_text = f"{run.output_text}\n{AUTO_DISABLE_MSG}"
            else:
                run.output_text = AUTO_DISABLE_MSG
            remove_task(task.id)
            logger.info("One-time task %s auto-disabled after run", task_id)

        db.commit()
        db.close()


def run_task_now(task_id: int):
    _execute_task(task_id)


def _job_id(task_id: int) -> str:
    return f"task_{task_id}"


def register_task(task: Task):
    remove_task(task.id)
    if not task.enabled:
        return

    tz = pytz_timezone(task.timezone or "Asia/Shanghai")

    try:
        if task.schedule_kind == ScheduleKind.ONE_TIME.value:
            if not task.run_at:
                logger.warning("One-time task %s has no run_at", task.id)
                return
            if task.run_at <= datetime.utcnow():
                logger.info("One-time task %s run_at is in the past, not scheduling", task.id)
                return
            trigger = DateTrigger(run_date=task.run_at, timezone=pytz_timezone("UTC"))
            scheduler.add_job(
                _execute_task,
                trigger=trigger,
                id=_job_id(task.id),
                args=[task.id],
                replace_existing=True,
            )
            _job_ids[task.id] = _job_id(task.id)
            logger.info("Registered one-time task %s at %s UTC", task.id, task.run_at)
            return

        cron = (task.cron_expr or "").strip()
        parts = cron.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron: {cron}")
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone=tz,
        )
        scheduler.add_job(
            _execute_task,
            trigger=trigger,
            id=_job_id(task.id),
            args=[task.id],
            replace_existing=True,
        )
        _job_ids[task.id] = _job_id(task.id)
        logger.info("Registered recurring task %s cron=%s", task.id, cron)
    except Exception as exc:
        logger.error("Failed to register task %s: %s", task.id, exc)


def remove_task(task_id: int):
    jid = _job_id(task_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
    _job_ids.pop(task_id, None)


def reload_all_tasks():
    for tid in list(_job_ids.keys()):
        remove_task(tid)
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(Task.enabled.is_(True)).all()
        for task in tasks:
            register_task(task)
    finally:
        db.close()


def _register_anomaly_jobs():
    if not settings.enable_anomaly_model:
        logger.info("Anomaly jobs not registered: ENABLE_ANOMALY_MODEL=false")
        return

    from app.anomaly_jobs import anomaly_enabled, collect_and_score_metric, daily_retrain

    if not anomaly_enabled():
        logger.warning("Anomaly jobs not registered: scikit-learn unavailable")
        return
    interval = max(30, int(settings.anomaly_sample_interval_seconds))
    scheduler.add_job(
        collect_and_score_metric,
        trigger="interval",
        seconds=interval,
        id="anomaly_collect",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_retrain,
        trigger=CronTrigger(hour=3, minute=0),
        id="anomaly_retrain",
        replace_existing=True,
    )
    logger.info("Anomaly detection jobs registered (sample interval: %ss)", interval)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
    reload_all_tasks()
    _register_anomaly_jobs()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
