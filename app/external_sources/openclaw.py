import logging
import re
import subprocess

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
            import shutil

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
                [cmd, "cron", "list"],
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
