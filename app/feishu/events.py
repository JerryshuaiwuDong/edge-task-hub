from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class FeishuEventError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedFeishuEvent:
    kind: str
    challenge: str = ""
    event_id: str = ""
    message_id: str = ""
    open_id: str = ""
    chat_id: str = ""
    message_type: str = ""
    text: str = ""
    file_key: str = ""
    file_name: str = ""


def parse_feishu_event(
    body: dict[str, Any],
    *,
    verification_token: str = "",
) -> ParsedFeishuEvent:
    if body.get("type") == "url_verification":
        _verify_token(body.get("token", ""), verification_token)
        return ParsedFeishuEvent(kind="challenge", challenge=str(body.get("challenge", "")))

    header = body.get("header") or {}
    event = body.get("event") or {}
    _verify_token(header.get("token", body.get("token", "")), verification_token)

    event_type = header.get("event_type") or body.get("type")
    if event_type != "im.message.receive_v1":
        return ParsedFeishuEvent(kind="ignored", event_id=str(header.get("event_id", "")))

    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    content = _parse_content(message.get("content"))
    message_type = str(message.get("message_type", ""))

    text = ""
    file_key = ""
    file_name = ""
    if message_type == "text":
        text = str(content.get("text", "")).strip()
    elif message_type == "file":
        file_key = str(content.get("file_key", "") or content.get("key", "")).strip()
        file_name = str(content.get("file_name", "") or content.get("name", "")).strip()

    return ParsedFeishuEvent(
        kind="message",
        event_id=str(header.get("event_id", "")),
        message_id=str(message.get("message_id", "")),
        open_id=str(sender_id.get("open_id", "")),
        chat_id=str(message.get("chat_id", "")),
        message_type=message_type,
        text=text,
        file_key=file_key,
        file_name=file_name,
    )


def _verify_token(actual: str, expected: str) -> None:
    if expected and actual != expected:
        raise FeishuEventError("Feishu verification token mismatch.")


def _parse_content(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise FeishuEventError(f"Invalid Feishu message content JSON: {exc}") from exc
    return parsed if isinstance(parsed, dict) else {}
