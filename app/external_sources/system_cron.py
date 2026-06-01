import logging
import subprocess

from app.external_sources.base import ExternalSource, ExternalTask
from app.external_sources.cron_display import cron_to_display

logger = logging.getLogger(__name__)


class SystemCronSource(ExternalSource):
    source_id = "system-cron"
    source_label = "System Cron"
    source_color = "slate"
    config_path = "crontab -l (user pi3)"

    def fetch_tasks(self) -> list[ExternalTask]:
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            logger.warning("crontab -l timed out")
            return []
        except FileNotFoundError:
            return []

        stderr = (result.stderr or "").lower()
        if "no crontab" in stderr or result.returncode != 0 and not result.stdout:
            return []

        tasks: list[ExternalTask] = []
        for i, line in enumerate((result.stdout or "").splitlines()):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            cron_expr = " ".join(parts[:5])
            command = parts[5]
            name = command if len(command) <= 40 else command[:37] + "..."
            tasks.append(
                ExternalTask(
                    source_id=self.source_id,
                    source_label=self.source_label,
                    source_color=self.source_color,
                    name=name,
                    task_type="shell",
                    schedule_display=cron_to_display(cron_expr),
                    schedule_raw=cron_expr,
                    timezone=None,
                    enabled=True,
                    config_path=self.config_path,
                    external_key=f"line-{i}",
                    last_run_status="unknown",
                )
            )
        return tasks
