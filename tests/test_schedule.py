import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from cleardebt.schedule import normalize_automation, schedule_due, schedule_skip_reason


class ScheduleTest(unittest.TestCase):
    def test_daily_due_at_configured_local_time(self):
        auto = normalize_automation(
            {"enabled": True, "frequency": "daily", "hour": 8, "minute": 0, "timezone": "Asia/Shanghai"}
        )
        now = datetime(2026, 9, 23, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertTrue(schedule_due(auto, now))
        self.assertIsNone(schedule_skip_reason(auto, now))
        later = datetime(2026, 9, 23, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertFalse(schedule_due(auto, later))
        self.assertIn("未到设定时间", schedule_skip_reason(auto, later))

    def test_weekly_requires_weekday(self):
        auto = normalize_automation(
            {
                "enabled": True,
                "frequency": "weekly",
                "weekday": 1,
                "hour": 8,
                "minute": 0,
                "timezone": "UTC",
            }
        )
        tuesday = datetime(2026, 9, 22, 8, 0, tzinfo=ZoneInfo("UTC"))  # Tuesday=1
        monday = datetime(2026, 9, 21, 8, 0, tzinfo=ZoneInfo("UTC"))
        self.assertTrue(schedule_due(auto, tuesday))
        self.assertFalse(schedule_due(auto, monday))

    def test_disabled_schedule_skips(self):
        auto = normalize_automation({"enabled": False, "hour": 8, "minute": 0})
        now = datetime(2026, 9, 23, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertFalse(schedule_due(auto, now))
        self.assertIn("关掉", schedule_skip_reason(auto, now))


if __name__ == "__main__":
    unittest.main()
