import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import ScheduleKind
from app.schedule_utils import parse_run_at_local, pattern_to_cron, simple_to_cron, validate_cron


class TaskBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    task_type: str
    schedule_kind: Literal["one_time", "recurring"] = "recurring"
    schedule_mode: str = "simple"
    cron_expr: str | None = None
    schedule_simple_json: dict[str, Any] | str = Field(default_factory=dict)
    run_at: datetime | str | None = None
    timezone: str = "Asia/Shanghai"
    payload_json: dict[str, Any] | str = Field(default_factory=dict)
    use_ai: bool = False
    ai_prompt_template: str | None = None
    enabled: bool = True

    @field_validator("schedule_simple_json", "payload_json", mode="before")
    @classmethod
    def parse_json_fields(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return {}
            return json.loads(v)
        return v or {}

    @field_validator("run_at", mode="before")
    @classmethod
    def parse_run_at(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo:
                return dt.astimezone(__import__("pytz").UTC).replace(tzinfo=None)
            return dt
        return v

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.schedule_kind == ScheduleKind.ONE_TIME.value:
            if self.run_at is None:
                raise ValueError("run_at is required for one-time tasks.")
            if self.run_at <= datetime.utcnow():
                raise ValueError("One-time run_at must be in the future.")
            self.cron_expr = ""
        else:
            simple = (
                self.schedule_simple_json
                if isinstance(self.schedule_simple_json, dict)
                else {}
            )
            if self.cron_expr:
                validate_cron(self.cron_expr)
            elif simple:
                self.cron_expr = simple_to_cron(simple)
                validate_cron(self.cron_expr)
            elif simple.get("pattern"):
                self.cron_expr = pattern_to_cron(simple["pattern"], simple)
            else:
                raise ValueError("cron_expr or schedule_simple_json is required for recurring tasks.")
            self.run_at = None
        return self


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    task_type: str | None = None
    schedule_kind: Literal["one_time", "recurring"] | None = None
    schedule_mode: str | None = None
    cron_expr: str | None = None
    schedule_simple_json: dict[str, Any] | str | None = None
    run_at: datetime | str | None = None
    timezone: str | None = None
    payload_json: dict[str, Any] | str | None = None
    use_ai: bool | None = None
    ai_prompt_template: str | None = None
    enabled: bool | None = None


class TaskOut(BaseModel):
    id: int
    name: str
    description: str
    task_type: str
    schedule_kind: str
    schedule_mode: str
    cron_expr: str | None
    schedule_simple_json: dict[str, Any]
    run_at: datetime | None
    timezone: str
    payload_json: dict[str, Any]
    use_ai: bool = False
    ai_prompt_template: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    schedule_label: str | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None

    model_config = {"from_attributes": True}


class TaskRunOut(BaseModel):
    id: int
    task_id: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: str
    output_text: str
    error_text: str

    model_config = {"from_attributes": True}


class ToggleRequest(BaseModel):
    enabled: bool | None = None
