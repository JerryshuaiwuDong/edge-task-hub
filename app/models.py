import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskType(str, enum.Enum):
    REMINDER = "reminder"
    RSS_DIGEST = "rss_digest"
    SYSTEM_STATUS = "system_status"


class ScheduleKind(str, enum.Enum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class ScheduleMode(str, enum.Enum):
    SIMPLE = "simple"
    ADVANCED = "advanced"


class RunStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"
    ANOMALY_ALERT = "anomaly_alert"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schedule_kind: Mapped[str] = mapped_column(
        String(16), default=ScheduleKind.RECURRING.value, nullable=False
    )
    schedule_mode: Mapped[str] = mapped_column(String(16), default=ScheduleMode.SIMPLE.value)
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_simple_json: Mapped[str] = mapped_column(Text, default="")
    run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    runs: Mapped[list["TaskRun"]] = relationship(
        "TaskRun", back_populates="task", cascade="all, delete-orphan"
    )


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING.value)
    output_text: Mapped[str] = mapped_column(Text, default="")
    error_text: Mapped[str] = mapped_column(Text, default="")

    task: Mapped["Task"] = relationship("Task", back_populates="runs")


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    cpu: Mapped[float] = mapped_column(Float, default=0.0)
    mem: Mapped[float] = mapped_column(Float, default=0.0)
    disk: Mapped[float] = mapped_column(Float, default=0.0)
    temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    network: Mapped[float] = mapped_column(Float, default=0.0)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)


class FeishuInboundEvent(Base):
    __tablename__ = "feishu_inbound_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    open_id: Mapped[str] = mapped_column(String(128), default="")
    chat_id: Mapped[str] = mapped_column(String(128), default="")
    message_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="received")
    output_text: Mapped[str] = mapped_column(Text, default="")
    error_text: Mapped[str] = mapped_column(Text, default="")
    created_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DocumentSummary(Base):
    __tablename__ = "document_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    error_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
