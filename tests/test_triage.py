import unittest
from unittest.mock import patch

from cleardebt.triage import describe_message, tier_for_issue


class DescribeMessageTest(unittest.TestCase):
    def test_message_details_attach_to_the_rule_name(self):
        from cleardebt.rules import save_pin

        save_pin("S1186", zh="空函数")
        self.assertEqual(
            describe_message("javascript:S1186", "Unexpected empty function 'emptyHandler'."),
            "空函数（emptyHandler）",
        )
        self.assertIn("第 2 行", describe_message("javascript:S1862", "This condition is covered by the one on line 2"))

    def test_untranslated_rule_falls_back_to_sonars_own_name(self):
        self.assertNotEqual(describe_message("javascript:S1128", ""), "")
        self.assertNotIn("未使用的 import", describe_message("javascript:S1128", ""))
        self.assertEqual(describe_message("weird:RULE", "Something odd happened"), "RULE")

    def test_sca_message_in_chinese(self):
        text = describe_message("sca:UPGRADE", "Upgrade lodash to version 4.17.21")
        self.assertIn("按建议升依赖版本", text)
        self.assertIn("lodash", text)

    def test_secret_setting_cannot_override_list_membership(self):
        signals = {
            "sonar_type": "VULNERABILITY",
            "sonar_impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}],
        }
        with patch.dict("os.environ", {"CLEARDEBT_FIX_SECRETS": "1"}), patch("cleardebt.triage.listed", return_value=False):
            self.assertEqual(tier_for_issue({"rule": "javascript:S2077", **signals}), "skip")
            self.assertEqual(tier_for_issue({"rule": "javascript:S2068", **signals}), "skip")
        with patch("cleardebt.triage.listed", return_value=True):
            self.assertEqual(tier_for_issue({"rule": "javascript:S2068", **signals}), "llm")



class TriageTierTest(unittest.TestCase):
    def test_rewrite_tier_is_only_for_js_ts_files(self):
        from cleardebt.a_fix import apply_mechanical

        with patch("cleardebt.triage.listed", return_value=True):
            self.assertEqual(tier_for_issue({"rule": "javascript:S1128", "path": "src/a.js"}), "rewrite")
            self.assertEqual(tier_for_issue({"rule": "java:S1128", "path": "src/A.java"}), "llm")
            self.assertEqual(tier_for_issue({"rule": "python:S1481", "path": "app.py"}), "llm")
            self.assertEqual(tier_for_issue({"rule": "javascript:S1186", "path": "src/a.js"}), "llm")
        # Non-JS sources used to reach the JS parser and raise inside the fix node.
        self.assertIsNone(apply_mechanical("python:S1128", "import os\nimport sys\nprint(sys.argv)\n", "a.py"))
        self.assertIsNone(apply_mechanical("java:S1128", "import java.util.List;\nclass A {}\n", "A.java"))

    def test_legacy_letter_tiers_keep_their_route(self):
        from cleardebt.triage import normalize_tier, same_route

        self.assertEqual([normalize_tier(t) for t in ("A", "B", "C", "unknown")], ["dependency", "llm", "skip", "unsupported"])
        self.assertTrue(same_route("B", "rewrite"))
        self.assertTrue(same_route("A", "dependency"))
        self.assertFalse(same_route("C", "llm"))

    def test_skipped_tiers_decide_skip_not_l3(self):
        from cleardebt.issue_graph import decide

        for tier in ("C", "skip", "unsupported"):
            with self.subTest(tier=tier):
                self.assertEqual(decide({"tier": tier, "rule": "kotlin:S1"})["level"], "skip")

    def test_merge_plan_reports_fix_method(self):
        from cleardebt.batch import plan_merges

        rows = [{"rule": "javascript:S1128", "path": "a.js", "level": "L3", "reason": "x", "fingerprint": "f", "fix_method": "mechanical"}]
        self.assertEqual(plan_merges(rows, {}, 0)[0]["fix_method"], "mechanical")


if __name__ == "__main__":
    unittest.main()
