import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cleardebt.api import app
from cleardebt.repairable_rules import summarize


ISSUES = [
    {"rule": "javascript:S6582", "project": "alpha", "quickFixAvailable": True},
    {"rule": "javascript:S6582", "project": "beta", "quickFixAvailable": False},
    {"rule": "javascript:S1128", "project": "alpha", "quickFixAvailable": False},
    {"rule": "kotlin:S1128", "project": "alpha", "quickFixAvailable": True},
]


class RepairableRulesTest(unittest.TestCase):
    def test_quick_fix_mode_lists_only_marked_supported_rules(self):
        result = summarize(ISSUES, None, {"javascript:S6582": {"name": "Prefer optional chaining"}})
        self.assertEqual(result["mode"], "sonar_quick_fix")
        self.assertEqual(result["rules"], [{"key": "javascript:S6582", "language": "javascript", "name": "Prefer optional chaining"}])

    def test_ai_codefix_list_is_exact_and_needs_no_issues(self):
        keys = frozenset({"javascript:S1128", "typescript:S6582", "kotlin:S1128"})
        result = summarize(None, keys, {})
        self.assertEqual(result["mode"], "ai_codefix_list")
        self.assertEqual([row["key"] for row in result["rules"]], ["javascript:S1128", "typescript:S6582"])
        self.assertNotIn("issue_count", result["rules"][0])

    def test_secrets_catalog_rules_are_always_listed(self):
        metadata = {"secrets:S6290": {"name": "AWS credentials"}, "kotlin:S1": {}}
        for keys in (frozenset({"javascript:S1128"}), None):
            with self.subTest(list_mode=keys is not None):
                result = summarize([], keys, metadata)
                self.assertIn({"key": "secrets:S6290", "language": "secrets", "name": "AWS credentials"}, result["rules"])
                self.assertNotIn("kotlin:S1", [row["key"] for row in result["rules"]])

    def test_api_lists_rules_without_reading_issues(self):
        with (
            patch("cleardebt.controls.sonar_credentials", return_value={"url": "http://sonar", "token": "secret"}),
            patch("cleardebt.ai_codefix_rules.rule_keys", return_value=frozenset({"javascript:S1128"})),
            patch("cleardebt.repairable_rules.fetch_open_issues") as fetch,
            patch("cleardebt.rules.catalog", return_value={}),
        ):
            response = TestClient(app).get("/api/repairable-rules")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rule_count"], 1)
        fetch.assert_not_called()

    def test_api_reads_issues_only_for_quick_fix_mode(self):
        with (
            patch("cleardebt.controls.sonar_credentials", return_value={"url": "http://sonar", "token": "secret"}),
            patch("cleardebt.ai_codefix_rules.rule_keys", return_value=None),
            patch("cleardebt.repairable_rules.fetch_open_issues", return_value=ISSUES) as fetch,
            patch("cleardebt.rules.catalog", return_value={}),
        ):
            response = TestClient(app).get("/api/repairable-rules")
        self.assertEqual(response.json()["rule_count"], 1)
        fetch.assert_called_once_with("http://sonar", "secret")


if __name__ == "__main__":
    unittest.main()
