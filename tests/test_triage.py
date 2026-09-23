import unittest

from cleardebt.triage import describe_message


class DescribeMessageTest(unittest.TestCase):
    def test_known_rules_in_chinese(self):
        self.assertEqual(
            describe_message("javascript:S1135", 'Complete the task associated to this "TODO" comment.'),
            "TODO 不自动完成",
        )
        self.assertEqual(
            describe_message("javascript:S1186", "Unexpected empty function 'emptyHandler'."),
            "空函数不自动填实现（emptyHandler）",
        )
        self.assertEqual(
            describe_message("javascript:S1862", "This condition is covered by the one on line 2"),
            "后面的条件永远到不了（第 2 行）",
        )

    def test_empty_message_falls_back_to_label(self):
        self.assertEqual(describe_message("javascript:S1128", ""), "未使用的 import")
        self.assertEqual(describe_message("weird:RULE", "Something odd happened"), "RULE")

    def test_sca_message_in_chinese(self):
        text = describe_message("sca:UPGRADE", "Upgrade lodash to version 4.17.21")
        self.assertIn("按建议升依赖版本", text)
        self.assertIn("lodash", text)


if __name__ == "__main__":
    unittest.main()
