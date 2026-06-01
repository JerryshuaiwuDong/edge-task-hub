from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.ai.document_summary import summarize_document_file
from app.config import settings
from app.database import get_db
from app.feishu.client import FeishuClient, FeishuClientError
from app.feishu.events import FeishuEventError, ParsedFeishuEvent, parse_feishu_event
from app.feishu.reminder_parser import parse_reminder_command
from app.models import DocumentSummary, FeishuInboundEvent, Task
from app.schedule_utils import format_schedule_label
from app.scheduler import register_task

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


@router.post("/events")
async def receive_feishu_event(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        parsed = parse_feishu_event(
            body,
            verification_token=settings.feishu_verification_token,
        )
    except FeishuEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if parsed.kind == "challenge":
        return {"challenge": parsed.challenge}
    if parsed.kind == "ignored":
        return {"ok": True, "ignored": True}
    if not settings.feishu_inbound_enabled:
        raise HTTPException(status_code=403, detail="Feishu inbound is disabled.")
    _authorize(parsed)

    existing = (
        db.query(FeishuInboundEvent)
        .filter(FeishuInboundEvent.message_id == parsed.message_id)
        .first()
    )
    if existing:
        return {"ok": True, "duplicate": True, "status": existing.status}

    record = FeishuInboundEvent(
        event_id=parsed.event_id,
        message_id=parsed.message_id,
        open_id=parsed.open_id,
        chat_id=parsed.chat_id,
        message_type=parsed.message_type,
        status="received",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    client = FeishuClient()
    try:
        if parsed.message_type == "text":
            result = _handle_text_message(parsed, db)
        elif parsed.message_type == "file":
            result = _handle_file_message(parsed, db, client)
        else:
            result = "This message type is not supported yet. Send a text reminder command or a private document file."
            record.status = "ignored"
        record.output_text = result
        if record.status == "received":
            record.status = "success"
        db.commit()
        _reply_best_effort(client, parsed.message_id, result, record)
        db.commit()
        return {"ok": True, "status": record.status}
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error_text = str(exc)
        record.updated_at = datetime.utcnow()
        db.commit()
        _reply_best_effort(client, parsed.message_id, f"Request failed: {exc}", record)
        return {"ok": False, "status": record.status, "error": str(exc)}


def _handle_text_message(parsed: ParsedFeishuEvent, db: Session) -> str:
    try:
        spec = parse_reminder_command(parsed.text)
    except ValueError as exc:
        return f"{exc}"

    task = Task(
        name=f"Feishu Reminder: {spec.message[:80]}",
        description=f"Created from Feishu message {parsed.message_id}.",
        task_type="reminder",
        schedule_kind=spec.schedule_kind,
        schedule_mode="simple",
        cron_expr=spec.cron_expr,
        schedule_simple_json=json.dumps(spec.schedule_simple_json),
        run_at=spec.run_at,
        timezone=spec.timezone,
        payload_json=json.dumps(
            {
                "message": spec.message,
                "source": "feishu",
                "source_message_id": parsed.message_id,
            }
        ),
        use_ai=False,
        enabled=True,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    register_task(task)

    record = (
        db.query(FeishuInboundEvent)
        .filter(FeishuInboundEvent.message_id == parsed.message_id)
        .first()
    )
    if record:
        record.created_task_id = task.id
        record.status = "created_task"
        db.commit()
    return f'Reminder created: "{spec.message}" ({format_schedule_label(task)}).'


def _handle_file_message(parsed: ParsedFeishuEvent, db: Session, client: FeishuClient) -> str:
    if not parsed.file_key:
        raise ValueError("File key is missing from the Feishu event.")
    safe_name = _safe_file_name(parsed.file_name or parsed.file_key)
    with tempfile.TemporaryDirectory(prefix="edge-task-hub-feishu-") as tmpdir:
        path = Path(tmpdir) / safe_name
        client.download_message_file(parsed.message_id, parsed.file_key, path)
        result = summarize_document_file(path, file_name=safe_name)

    doc = DocumentSummary(
        message_id=parsed.message_id,
        file_name=safe_name,
        file_size=result.file_size,
        sha256=result.sha256,
        model=result.model,
        elapsed_seconds=result.elapsed_seconds,
        summary_text=result.text,
        error_text=result.error,
    )
    db.add(doc)
    db.commit()

    if not result.ok:
        raise ValueError(result.error)
    return f"Private document summary generated on this Raspberry Pi:\n\n{result.text}"


def _reply_best_effort(
    client: FeishuClient,
    message_id: str,
    text: str,
    record: FeishuInboundEvent,
) -> None:
    try:
        client.reply_text(message_id, text)
    except FeishuClientError as exc:
        record.error_text = f"Reply failed: {exc}"


def _authorize(parsed: ParsedFeishuEvent) -> None:
    allowed_open_ids = _csv(settings.feishu_allowed_open_ids)
    allowed_chat_ids = _csv(settings.feishu_allowed_chat_ids)
    if allowed_open_ids and parsed.open_id not in allowed_open_ids:
        raise HTTPException(status_code=403, detail="Sender is not allowed.")
    if allowed_chat_ids and parsed.chat_id not in allowed_chat_ids:
        raise HTTPException(status_code=403, detail="Chat is not allowed.")


def _csv(value: str) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def _safe_file_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:120] or "feishu-file"
