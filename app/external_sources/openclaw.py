import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.external_sources.base import ExternalSource, ExternalTask, SourceWarning

logger = logging.getLogger(__name__)


class OpenClawSource(ExternalSource):
    source_id = "openclaw"
    source_label = "OpenClaw Cron"
    source_color = "violet"
    config_path = "/home/pi3/.openclaw/openclaw.json"

    def __init__(self):
        self._warning: SourceWarning | None = None

    def fetch_warnings(self) -> list[SourceWarning]:
        return [self._warning] if self._warning else []

    def fetch_tasks(self) -> list[ExternalTask]:
        self._warning = None
        cmd = None
        for candidate in (
            "openclaw",
            "/home/pi3/.npm-global/bin/openclaw",
            "/usr/local/bin/openclaw",
        ):
            if shutil.which(candidate) or candidate.startswith("/"):
                cmd = candidate
                break
        if not cmd:
            self._warning = SourceWarning(
                source=self.source_id,
                message="openclaw CLI not found on PATH.",
            )
            return []

        try:
            result = subprocess.run(
                self._cron_list_command(cmd),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            self._warning = SourceWarning(
                source=self.source_id,
                message="OpenClaw command timed out after 10 seconds.",
            )
            return []
        except FileNotFoundError:
            self._warning = SourceWarning(
                source=self.source_id,
                message=f"openclaw CLI not found: {cmd}",
            )
            return []

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()[:200]
            self._warning = SourceWarning(
                source=self.source_id,
                message=f"openclaw cron list failed: {err}",
            )
            return []

        text = (result.stdout or "").strip()
        if not text or "no cron jobs" in text.lower():
            return []

        return self._parse_output(text)

    def _cron_list_command(self, cmd: str) -> list[str]:
        args = [cmd, "cron", "list"]
        gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
        if gateway_url:
            args.extend(["--url", gateway_url])
        token = self._gateway_token()
        if token:
            args.extend(["--token", token])
        return args

    def _gateway_token(self) -> str:
        try:
            data = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        gateway = data.get("gateway") if isinstance(data, dict) else {}
        auth = gateway.get("auth") if isinstance(gateway, dict) else {}
        if not isinstance(auth, dict) or auth.get("mode") != "token":
            return ""
        return str(auth.get("token") or "").strip()

    def _parse_output(self, text: str) -> list[ExternalTask]:
        tasks: list[ExternalTask] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or "cron" in line.lower():
                continue
            if line.startswith("Agents:") or line.startswith("Routing"):
                break
            name = line[:80]
            cron_match = re.search(r"(\S+\s+\S+\s+\S+\s+\S+\s+\S+)", line)
            cron = cron_match.group(1) if cron_match else line
            tasks.append(
                ExternalTask(
                    source_id=self.source_id,
                    source_label=self.source_label,
                    source_color=self.source_color,
                    name=name,
                    task_type="unknown",
                    schedule_display=cron,
                    schedule_raw=cron,
                    timezone=None,
                    enabled=True,
                    config_path=self.config_path,
                    external_key=name,
                )
            )
        return tasks
