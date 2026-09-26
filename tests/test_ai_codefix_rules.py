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
        self.assertEqual(tier_for_issue(security), "llm")
        self.assertTrue(issue_repairable(security))
        self.assertEqual(tier_for_issue(unlisted), "skip")
        self.assertFalse(issue_repairable(unlisted))
        with patch("cleardebt.triage.lookup", return_value=None):
            self.assertTrue(issue_repairable({"rule": "csharpsquid:S1128"}))

    def test_missing_list_uses_only_sonar_issue_quick_fix(self):
        with patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": ""}):
            self.assertIsNone(rule_keys())
            self.assertEqual(tier_for_issue({"rule": "javascript:S1128", "sonar_type": "CODE_SMELL"}), "skip")
            self.assertFalse(issue_repairable({"rule": "javascript:S1128", "tier": "A"}))
            self.assertEqual(tier_for_issue({"rule": "javascript:S1128", "quick_fix": True}), "rewrite")
            self.assertTrue(issue_repairable({"rule": "javascript:S1128", "quick_fix": True}))
            self.assertFalse(issue_repairable({"rule": "javascript:S1128", "quick_fix": "true"}))

    def test_bundled_snapshot_is_the_default_list(self):
        with patch.dict("os.environ", {}, clear=True):
            keys = rule_keys()
        self.assertEqual(len(keys), 2635)
        self.assertIn("javascript:S1186", keys)
        self.assertNotIn("kotlin:S1186", keys)

    def test_json_snapshot_is_validated(self):
        path = Path(self._tmpdir.name) / "rules.json"
        path.write_text('{"rules": [{"key": "java:S100"}, {"key": "bad"}]}', encoding="utf-8")
        with patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": str(path)}):
            with self.assertRaisesRegex(ValueError, "第 2 条"):
                rule_keys()

    def test_configured_list_overrides_sonar_quick_fix(self):
        self.assertFalse(issue_repairable({"rule": "javascript:S1186", "quick_fix": True}))
        self.assertTrue(issue_repairable({"rule": "javascript:S6582", "quick_fix": False}))

    def test_secrets_repo_is_repairable_outside_the_list(self):
        self.assertFalse(listed("secrets:S6290"))
        self.assertTrue(issue_repairable({"rule": "secrets:S6290"}))
        with patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": ""}):
            self.assertTrue(issue_repairable({"rule": "secrets:S6290", "quick_fix": False}))

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

    def test_backlog_uses_sonar_quick_fix_without_a_list(self):
        from cleardebt.assign import _enrich, _sonar_row

        rows = [
            _sonar_row("test", {
                "rule": "javascript:S1128", "component": "test:src/a.js",
                "quickFixAvailable": True,
            }),
            {"rule": "javascript:S1186", "path": "src/b.js", "quick_fix": False, "tier": "A"},
        ]
        with (
            patch.dict("os.environ", {"CLEARDEBT_AI_CODEFIX_RULES_FILE": ""}),
            patch("cleardebt.assign.describe_message", return_value="告警"),
            patch("cleardebt.assign.suppressed_map", return_value={}),
            patch("cleardebt.assign.first_seen_map", return_value={}),
            patch("cleardebt.assign.issue_status_map", return_value={}),
        ):
            enriched = _enrich("test", rows)
        by_rule = {row["rule"]: row for row in enriched}
        self.assertTrue(by_rule["javascript:S1128"]["eligible"])
        self.assertFalse(by_rule["javascript:S1186"]["eligible"])
        self.assertEqual(by_rule["javascript:S1128"]["tier_source"], "sonar_quick_fix")


if __name__ == "__main__":
    unittest.main()
