import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cleardebt.ai_codefix_rules import listed, rule_keys
from cleardebt.triage import issue_repairable, tier_for_issue


class AiCodefixRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "rules.txt"
        self.path.write_text("# authorized Sonar export\njavascript:S6582\ncsharpsquid:S1128\n", encoding="utf-8")
        self._env = patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": str(self.path)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmpdir.cleanup()

    def test_exact_full_key_and_live_reload(self):
        self.assertTrue(listed("javascript:S6582"))
        self.assertFalse(listed("typescript:S6582"))
        self.assertFalse(listed("javascript:S1186"))
        self.path.write_text("javascript:S1186\n", encoding="utf-8")
        self.assertFalse(listed("javascript:S6582"))
        self.assertTrue(listed("javascript:S1186"))

    def test_membership_alone_decides_eligibility_even_with_stale_tier(self):
        security = {"rule": "javascript:S6582", "sonar_type": "VULNERABILITY",
                    "sonar_impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}]}
        unlisted = {"rule": "javascript:S1186", "tier": "A", "sonar_type": "CODE_SMELL",
                    "sonar_impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "LOW"}]}
        self.assertEqual(tier_for_issue(security), "B")
        self.assertTrue(issue_repairable(security))
        self.assertEqual(tier_for_issue(unlisted), "C")
        self.assertFalse(issue_repairable(unlisted))
        with patch("cleardebt.triage.lookup", return_value=None):
            self.assertTrue(issue_repairable({"rule": "csharpsquid:S1128"}))

    def test_missing_list_fails_closed_even_with_stale_tier(self):
        with patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": ""}):
            self.assertIsNone(rule_keys())
            self.assertEqual(tier_for_issue({"rule": "javascript:S1128", "sonar_type": "CODE_SMELL"}), "C")
            self.assertFalse(issue_repairable({"rule": "javascript:S1128", "tier": "A"}))

    def test_bad_configured_list_fails_closed(self):
        self.path.write_text("javascript:S6582\ntypescript:S6582 extra\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            rule_keys()
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "无法读取"):
            rule_keys()

    def test_backlog_uses_the_same_list_as_execution(self):
        from cleardebt.assign import _enrich

        rows = [
            {"rule": "javascript:S6582", "path": "src/a.js", "sonar_type": "VULNERABILITY"},
            {"rule": "javascript:S1186", "path": "src/b.js", "sonar_type": "CODE_SMELL",
             "sonar_impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "LOW"}]},
        ]
        with (
            patch("cleardebt.assign.describe_message", return_value="告警"),
            patch("cleardebt.assign.suppressed_map", return_value={}),
            patch("cleardebt.assign.first_seen_map", return_value={}),
            patch("cleardebt.assign.issue_status_map", return_value={}),
        ):
            enriched = _enrich("test", rows)
        by_rule = {row["rule"]: row for row in enriched}
        self.assertTrue(by_rule["javascript:S6582"]["eligible"])
        self.assertFalse(by_rule["javascript:S1186"]["eligible"])
        self.assertEqual(by_rule["javascript:S1186"]["tier_source"], "sonar_ai_codefix_list")


if __name__ == "__main__":
    unittest.main()
