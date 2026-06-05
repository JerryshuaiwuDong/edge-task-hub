"""Startup seed data."""

import json
import logging

from app.database import SessionLocal
from app.models import Task
from app.scheduler import register_task

logger = logging.getLogger(__name__)


def seed_demo_task_if_empty():
    db = SessionLocal()
    try:
        existing_count = db.query(Task).filter(Task.name != "__anomaly_monitor__").count()
        _normalize_legacy_english_tasks(db)
        _ensure_standard_tasks(db)
        if existing_count == 0:
            task = Task(
                name="AI Morning Greeting (Demo)",
                description="Example AI-powered reminder using the local model",
                task_type="reminder",
                schedule_kind="recurring",
                schedule_mode="simple",
                cron_expr="0 8 * * *",
                schedule_simple_json=json.dumps({"pattern": "daily", "time": "08:00"}),
                timezone="Asia/Shanghai",
                payload_json=json.dumps({"message": "Good morning! (static fallback)"}),
                use_ai=True,
                ai_prompt_template=(
                    "Generate a warm and brief good morning message in English (max 50 words). "
                    "Today is {weekday} {date}. Mention something uplifting or motivational."
                ),
                enabled=False,
            )
            db.add(task)
            db.commit()
            logger.info("Seeded demo task: AI Morning Greeting (Demo)")
    finally:
        db.close()


def _ensure_standard_tasks(db) -> None:
    tasks = [
        Task(
            name="Daily Previous-Day News Summary",
            description="Analyze yesterday's global headlines from at least ten publishers and send the local summary to Feishu.",
            task_type="rss_digest",
            schedule_kind="recurring",
            schedule_mode="simple",
            cron_expr="0 10 * * *",
            schedule_simple_json=json.dumps({"pattern": "daily", "time": "10:00"}),
            timezone="Asia/Shanghai",
            payload_json=json.dumps(
                {
                    "feed_url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
                    "limit": 10,
                    "min_sources": 10,
                    "fetch_limit": 100,
                    "summary_mode": "ollama",
                    "model": "qwen3:1.7b",
                    "timeout": 300,
                    "date_window": "previous_day",
                    "notify": True,
                }
            ),
            use_ai=True,
            enabled=True,
        ),
        Task(
            name="Lunch Reminder",
            description="Daily Feishu lunch reminder.",
            task_type="reminder",
            schedule_kind="recurring",
            schedule_mode="simple",
            cron_expr="0 12 * * *",
            schedule_simple_json=json.dumps({"pattern": "daily", "time": "12:00"}),
            timezone="Asia/Shanghai",
            payload_json=json.dumps({"message": "It is 12:00. Time for lunch."}),
            use_ai=False,
            enabled=True,
        ),
        Task(
            name="Sleep Reminder",
            description="Daily Feishu sleep reminder.",
            task_type="reminder",
            schedule_kind="recurring",
            schedule_mode="simple",
            cron_expr="30 23 * * *",
            schedule_simple_json=json.dumps({"pattern": "daily", "time": "23:30"}),
            timezone="Asia/Shanghai",
            payload_json=json.dumps({"message": "It is 23:30. Time to sleep."}),
            use_ai=False,
            enabled=True,
        ),
    ]
    changed = False
    for task in tasks:
        exists = db.query(Task).filter(Task.name == task.name).first()
        if exists:
            continue
        db.add(task)
        db.flush()
        register_task(task)
        changed = True
    if changed:
        db.commit()
        logger.info("Seeded standard EdgeAI Feishu tasks")


def _normalize_legacy_english_tasks(db) -> None:
    legacy_name = "EdgeAI \u65b0\u95fb\u6458\u8981\u6f14\u793a"
    task = db.query(Task).filter(Task.name == legacy_name).first()
    if not task:
        return
    task.name = "EdgeAI News Summary Demo"
    task.description = task.description or "Legacy demo task normalized to English."
    try:
        payload = json.loads(task.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload["fallback_items"] = [
        {
            "title": "Raspberry Pi collects RSS headlines and summarizes them locally",
            "link": "local://edge-rss-summary",
            "source": "Local EdgeAI demo",
        },
        {
            "title": "qwen3:0.6b is the fastest reliable short-summary candidate",
            "link": "local://edge-llm-result",
            "source": "Local EdgeAI demo",
        },
        {
            "title": "The system records local model failures instead of hiding them",
            "link": "local://edge-fallback",
            "source": "Local EdgeAI demo",
        },
    ]
    task.payload_json = json.dumps(payload)
    db.commit()
    logger.info("Normalized legacy EdgeAI news demo task to English")
