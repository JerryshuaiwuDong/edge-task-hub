import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.feishu.reminder_parser import parse_reminder_command


class ReminderParserTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 5, 29, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def test_parse_daily_reminder(self):
        spec = parse_reminder_command("remind me every day at 23:30 to sleep", now=self.now)

        self.assertEqual(spec.message, "sleep")
        self.assertEqual(spec.schedule_kind, "recurring")
        self.assertEqual(spec.cron_expr, "30 23 * * *")
        self.assertEqual(spec.schedule_simple_json, {"pattern": "daily", "time": "23:30"})

    def test_parse_tomorrow_one_time_reminder(self):
        spec = parse_reminder_command("remind me tomorrow at 23:30 to sleep", now=self.now)

        self.assertEqual(spec.message, "sleep")
        self.assertEqual(spec.schedule_kind, "one_time")
        self.assertEqual(spec.run_at, datetime(2026, 5, 30, 15, 30))

    def test_rejects_unclear_time(self):
        with self.assertRaises(ValueError):
            parse_reminder_command("remind me next week to eat", now=self.now)


if __name__ == "__main__":
    unittest.main()
