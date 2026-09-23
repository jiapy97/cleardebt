import unittest

from cleardebt.controls import automation_for


class AutomationForTest(unittest.TestCase):
    def test_binding_override_merges_onto_global(self):
        settings = {
            "backlog_automation": {
                "enabled": True,
                "frequency": "daily",
                "hour": 8,
                "minute": 0,
                "timezone": "Asia/Shanghai",
                "pause_when_open_mrs": 10,
            },
            "bindings": [
                {
                    "sonar_key": "alpha",
                    "automation": {"enabled": False, "pause_when_open_mrs": 2},
                }
            ],
        }
        auto = automation_for(settings, "alpha")
        self.assertFalse(auto["enabled"])
        self.assertEqual(auto["pause_when_open_mrs"], 2)
        self.assertEqual(auto["hour"], 8)
        self.assertEqual(automation_for(settings, "missing")["pause_when_open_mrs"], 10)


if __name__ == "__main__":
    unittest.main()
