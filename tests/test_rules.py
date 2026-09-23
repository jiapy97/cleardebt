import unittest
from unittest.mock import patch

from cleardebt.rules import lookup, pins, policy_tier, refresh
from cleardebt.triage import describe, llm_repairable, tier_for

FAKE = {
    "javascript:S107": {"key": "javascript:S107", "type": "CODE_SMELL", "severity": "MAJOR", "name": "Functions should not have too many parameters"},
    "javascript:S3649": {"key": "javascript:S3649", "type": "VULNERABILITY", "severity": "BLOCKER", "name": "SQL injection"},
    "javascript:S9999": {"key": "javascript:S9999", "type": "BUG", "severity": "MINOR", "name": "Some minor bug"},
}


class LiveRulesTest(unittest.TestCase):
    def test_pins_beat_policy(self):
        with patch("cleardebt.rules.fetch_all", return_value=dict(FAKE)):
            refresh()
            self.assertEqual(tier_for("javascript:S107"), "C")
            self.assertEqual(describe("javascript:S107"), "参数太多，要人拆")
            self.assertFalse(llm_repairable("javascript:S107"))

    def test_policy_grades_unknown_rules(self):
        with patch("cleardebt.rules.fetch_all", return_value=dict(FAKE)):
            refresh()
            self.assertEqual(tier_for("javascript:S3649"), "C")
            self.assertEqual(tier_for("javascript:S9999"), "B")
            self.assertTrue(llm_repairable("javascript:S9999"))

    def test_lookup_miss_is_unknown(self):
        with patch("cleardebt.rules.fetch_all", return_value={}):
            refresh()
            self.assertIsNone(lookup("javascript:S0000"))
            self.assertEqual(policy_tier(None), "unknown")

    def test_sonar_unreachable_keeps_pins_working(self):
        with patch("cleardebt.rules.fetch_all", side_effect=ConnectionError("down")):
            try:
                refresh()
            except ConnectionError:
                pass
            self.assertEqual(tier_for("javascript:S1128"), "A")
            self.assertTrue(llm_repairable("javascript:S1128"))


if __name__ == "__main__":
    unittest.main()
