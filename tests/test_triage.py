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

    def test_secret_override_does_not_allow_other_security_issues(self):
        signals = {
            "sonar_type": "VULNERABILITY",
            "sonar_impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}],
        }
        with patch.dict("os.environ", {"CLEARDEBT_FIX_SECRETS": "1"}):
            self.assertEqual(tier_for_issue({"rule": "javascript:S2077", **signals}), "C")
            self.assertEqual(tier_for_issue({"rule": "javascript:S2068", **signals}), "A")


if __name__ == "__main__":
    unittest.main()
