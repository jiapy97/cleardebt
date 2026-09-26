import unittest

from cleardebt.suggestion import build

ROW = {
    "fingerprint": "fp",
    "rule": "javascript:S1854",
    "path": "src/status.js",
    "level": "L3",
    "reason": "old run",
    "old_string": "  let status = 1;\n  status = 2;\n",
    "new_string": "  let status = 2;\n",
}


class SuggestionTest(unittest.TestCase):
    def test_finished_checkpoint_wins_over_saved_snippet(self):
        state = {
            "level": "L1",
            "reason": "重扫过了。",
            "path": "src/status.js",
            "message": "Remove this useless assignment to variable \"status\".",
            "before": "a\nb\n",
            "after": "a\nc\n",
            "fix_method": "mechanical",
            "history": ["triage", "fix", "anti_cheat", "rescan", "test", "decide"],
            "rescan_ok": True,
            "tests_skipped": True,
        }
        result = build(ROW, state, "https://mr")
        self.assertEqual((result["level"], result["fix_method"], result["diff_scope"]), ("L1", "规则改写", "file"))
        self.assertIn("-b\n+c\n", result["diffs"][0]["diff"])
        self.assertEqual([check["ok"] for check in result["checks"]], [True, True, None])
        self.assertEqual(result["mr_url"], "https://mr")

    def test_missing_or_unfinished_checkpoint_falls_back_to_snippet(self):
        for state in ({}, {"before": "x\n", "after": "y\n", "rescan_ok": False}):
            with self.subTest(state=state):
                result = build(ROW, state)
                self.assertEqual((result["level"], result["reason"], result["diff_scope"]), ("L3", "old run", "snippet"))
                self.assertIn("-  status = 2;\n", result["diffs"][0]["diff"])
                self.assertEqual(result["checks"], [])

    def test_failed_gates_explain_why(self):
        state = {
            "level": "L3",
            "rejections": [{"reason": "改了测试文件。"}],
            "tests_passed": True,
            "uncovered_lines": [7],
        }
        checks = build(ROW, state)["checks"]
        self.assertEqual([(c["name"], c["ok"]) for c in checks], [("防作弊检查", False), ("测试", False)])
        self.assertIn("第 7 行", checks[1]["detail"])


if __name__ == "__main__":
    unittest.main()
