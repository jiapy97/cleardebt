import unittest
from unittest.mock import patch

from cleardebt.rules import lookup, pins, policy_tier, refresh
from cleardebt.triage import describe, llm_repairable, tier_for

FAKE = {
    "javascript:S107": {"key": "javascript:S107", "type": "CODE_SMELL", "severity": "MAJOR", "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "MEDIUM"}], "name": "Functions should not have too many parameters"},
    "javascript:S3649": {"key": "javascript:S3649", "type": "VULNERABILITY", "severity": "BLOCKER", "impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}], "name": "SQL injection"},
    "javascript:S9999": {"key": "javascript:S9999", "type": "BUG", "severity": "MINOR", "impacts": [{"softwareQuality": "RELIABILITY", "severity": "LOW"}], "name": "Some minor bug"},
}


class LiveRulesTest(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from cleardebt import rules as _rules

        self._saved_rules = dict(_rules._rules)
        self._saved_at = _rules._fetched_at
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved_env = os.environ.get("CLEARDEBT_RULES_CACHE")
        os.environ["CLEARDEBT_RULES_CACHE"] = str(
            __import__("pathlib").Path(self._tmpdir.name) / "rules_cache.json"
        )
        _rules.CACHE_PATH = __import__("pathlib").Path(os.environ["CLEARDEBT_RULES_CACHE"])

    def tearDown(self):
        import os

        from cleardebt import rules as _rules

        _rules._rules = self._saved_rules
        _rules._fetched_at = self._saved_at
        if self._saved_env is None:
            os.environ.pop("CLEARDEBT_RULES_CACHE", None)
        else:
            os.environ["CLEARDEBT_RULES_CACHE"] = self._saved_env
        _rules.CACHE_PATH = __import__("pathlib").Path(
            os.environ.get("CLEARDEBT_RULES_CACHE", "").strip()
            or (_rules.ROOT / "var" / "rules_cache.json")
        )
        self._tmpdir.cleanup()

    def test_manual_pin_beats_policy(self):
        from cleardebt.rules import save_pin

        save_pin("S107", tier="C", zh="参数太多，要人拆")
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
            self.assertIn(tier_for("javascript:S1128"), {"A", "B", "unknown"})
            self.assertEqual(llm_repairable("javascript:S1128"), tier_for("javascript:S1128") in {"A", "B"})


if __name__ == "__main__":
    unittest.main()
