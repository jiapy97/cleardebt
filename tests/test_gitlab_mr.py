import unittest

from cleardebt.gitlab_mr import NotEligible, ensure_access, ensure_eligible, render_description


class GitlabMergeRequestTest(unittest.TestCase):
    def test_only_l1_can_open(self):
        ensure_eligible("L1")
        with self.assertRaises(NotEligible):
            ensure_eligible("L2")
        with self.assertRaises(NotEligible):
            ensure_eligible("C")

    def test_guest_token_cannot_push(self):
        with self.assertRaises(NotEligible) as caught:
            ensure_access(10)
        self.assertIn("Guest", str(caught.exception))

    def test_description_includes_the_gate_results(self):
        text = render_description(
            {
                "rule": "javascript:S1128",
                "path": "src/orders.js",
                "fingerprint": "abc",
                "rescan_removed": [{"rule": "javascript:S1128", "path": "src/orders.js"}],
                "rescan_added": [],
                "tests_passed": True,
                "uncovered_lines": [],
            }
        )
        self.assertIn("javascript:S1128", text)
        self.assertIn("abc", text)
        self.assertIn("没有新告警", text)
        self.assertIn("通过", text)
        self.assertIn("没有新增需要覆盖的代码行", text)


if __name__ == "__main__":
    unittest.main()
