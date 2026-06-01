"""Apply startup SQLite schema migrations with additive ALTER TABLE changes."""

import logging

from sqlalchemy import inspect, text

from app.database import engine

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        if insp.has_table("tasks"):
            cols = {c["name"] for c in insp.get_columns("tasks")}
            if "schedule_kind" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE tasks ADD COLUMN schedule_kind VARCHAR(16) DEFAULT 'recurring'"
                    )
                )
                logger.info("Migration: schedule_kind")
            if "run_at" not in cols:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN run_at DATETIME"))
                logger.info("Migration: run_at")
            if "use_ai" not in cols:
                conn.execute(
                    text("ALTER TABLE tasks ADD COLUMN use_ai BOOLEAN DEFAULT 0")
                )
                logger.info("Migration: use_ai")
            if "ai_prompt_template" not in cols:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN ai_prompt_template TEXT"))
                logger.info("Migration: ai_prompt_template")
            conn.execute(
                text(
                    "UPDATE tasks SET schedule_kind = 'recurring' "
                    "WHERE schedule_kind IS NULL OR schedule_kind = ''"
                )
            )

        # system_metrics is created by create_all; skip it if the table exists.
