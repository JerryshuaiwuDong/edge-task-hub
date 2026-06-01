from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field


class ExternalTask(BaseModel):
    source_id: str
    source_label: str
    source_color: str
    name: str
    task_type: str
    schedule_display: str
    schedule_raw: str
    timezone: str | None = None
    enabled: bool = True
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    last_run_excerpt: str | None = None
    config_path: str
    readonly: bool = True
    external_key: str = ""


class SourceWarning(BaseModel):
    source: str
    message: str


class SourceInfo(BaseModel):
    source_id: str
    source_label: str
    source_color: str
    status: str
    status_detail: str
    task_count: int
    enabled_count: int
    config_path: str
    log_path: str | None = None
    service_unit: str | None = None
    readonly: bool = True


class ExternalSource(ABC):
    source_id: str
    source_label: str
    source_color: str
    config_path: str

    @abstractmethod
    def fetch_tasks(self) -> list[ExternalTask]:
        pass

    def fetch_warnings(self) -> list[SourceWarning]:
        return []
