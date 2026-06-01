from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from app.config import settings


FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuClientError(RuntimeError):
    pass


class FeishuClient:
    def __init__(self, *, app_id: str | None = None, app_secret: str | None = None):
        self.app_id = app_id if app_id is not None else settings.feishu_app_id
        self.app_secret = app_secret if app_secret is not None else settings.feishu_app_secret
        self._tenant_access_token: str | None = None

    def tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        if not self.app_id or not self.app_secret:
            raise FeishuClientError("FEISHU_APP_ID and FEISHU_APP_SECRET are required.")
        response = requests.post(
            f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15,
        )
        data = _json_response(response)
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuClientError(f"Feishu tenant token missing: {data}")
        self._tenant_access_token = str(token)
        return self._tenant_access_token

    def reply_text(self, message_id: str, text: str) -> None:
        response = requests.post(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply",
            headers=self._headers(),
            json={"msg_type": "text", "content": json.dumps({"text": text[:4000]})},
            timeout=15,
        )
        _json_response(response)

    def download_message_file(self, message_id: str, file_key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
            headers=self._headers(),
            params={"type": "file"},
            timeout=60,
        )
        if response.status_code != 200:
            raise FeishuClientError(f"Feishu file download failed: HTTP {response.status_code} {response.text[:300]}")
        destination.write_bytes(response.content)
        return destination

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_access_token()}"}


def _json_response(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise FeishuClientError(f"Feishu returned non-JSON response: HTTP {response.status_code}") from exc
    if response.status_code != 200 or data.get("code", 0) != 0:
        raise FeishuClientError(f"Feishu API error: HTTP {response.status_code} {data}")
    return data
