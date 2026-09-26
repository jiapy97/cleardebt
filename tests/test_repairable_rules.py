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
    def test_quick_fix_mode_counts_only_marked_supported_issues(self):
        result = summarize(ISSUES, None, {"javascript:S6582": {"name": "Prefer optional chaining"}})
        self.assertEqual((result["rule_count"], result["eligible_issue_count"], result["open_issue_count"]), (1, 1, 4))
        self.assertEqual(result["rules"][0]["key"], "javascript:S6582")
        self.assertEqual(result["rules"][0]["projects"], ["alpha"])
        self.assertEqual(result["rules"][0]["name"], "Prefer optional chaining")

    def test_ai_codefix_list_is_exact_and_includes_rules_without_open_issues(self):
        keys = frozenset({"javascript:S1128", "typescript:S6582", "kotlin:S1128"})
        result = summarize(ISSUES, keys, {})
        self.assertEqual(result["mode"], "ai_codefix_list")
        self.assertEqual(result["eligible_issue_count"], 1)
        self.assertEqual([row["key"] for row in result["rules"]], ["javascript:S1128", "typescript:S6582"])
        self.assertEqual(result["rules"][1]["issue_count"], 0)

    def test_api_returns_the_current_sonar_aggregation(self):
        with (
            patch("cleardebt.controls.sonar_credentials", return_value={"url": "http://sonar", "token": "secret"}),
            patch("cleardebt.ai_codefix_rules.rule_keys", return_value=None),
            patch("cleardebt.repairable_rules.fetch_open_issues", return_value=ISSUES) as fetch,
            patch("cleardebt.rules.catalog", return_value={}),
        ):
            response = TestClient(app).get("/api/repairable-rules")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rule_count"], 1)
        fetch.assert_called_once_with("http://sonar", "secret")


if __name__ == "__main__":
    unittest.main()
