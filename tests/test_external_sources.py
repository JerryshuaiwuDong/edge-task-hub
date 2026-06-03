import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.external_sources.openclaw import OpenClawSource


class OpenClawSourceTest(unittest.TestCase):
    @mock.patch("app.external_sources.openclaw.subprocess.run")
    @mock.patch("app.external_sources.openclaw.shutil.which", return_value="/home/pi3/.npm-global/bin/openclaw")
    def test_passes_gateway_token_when_gateway_url_is_overridden(self, _which_mock, run_mock):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write('{"gateway":{"auth":{"mode":"token","token":"test-token"}}}')
            config_path = Path(handle.name)

        run_mock.return_value = subprocess.CompletedProcess(
            ["/home/pi3/.npm-global/bin/openclaw", "cron", "list"],
            0,
            stdout="no cron jobs",
            stderr="",
        )
        source = OpenClawSource()
        source.config_path = str(config_path)
        old_url = os.environ.get("OPENCLAW_GATEWAY_URL")
        os.environ["OPENCLAW_GATEWAY_URL"] = "ws://127.0.0.1:18789"
        try:
            tasks = source.fetch_tasks()
        finally:
            config_path.unlink(missing_ok=True)
            if old_url is None:
                os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            else:
                os.environ["OPENCLAW_GATEWAY_URL"] = old_url

        self.assertEqual(tasks, [])
        cmd = run_mock.call_args.args[0]
        self.assertIn("--url", cmd)
        self.assertIn("ws://127.0.0.1:18789", cmd)
        self.assertIn("--token", cmd)
        self.assertIn("test-token", cmd)


if __name__ == "__main__":
    unittest.main()
