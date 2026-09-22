import unittest

from cleardebt.rescan import verdict


def row(fingerprint: str, rule: str, path: str = "src/orders.js", line: int = 1) -> dict:
    return {"fingerprint": fingerprint, "rule": rule, "path": path, "line": line}


class RescanVerdictTest(unittest.TestCase):
    def test_passes_when_only_the_fixed_rule_disappears(self):
        before = [row("fixed", "javascript:S1128"), row("kept", "javascript:S1481", line=4)]
        after = [row("kept", "javascript:S1481", line=2)]
        result = verdict(before, after, "javascript:S1128")
        self.assertTrue(result["ok"])
        self.assertEqual([item["rule"] for item in result["removed"]], ["javascript:S1128"])
        self.assertEqual(result["added"], [])

    def test_fails_when_a_new_issue_appears(self):
        before = [row("fixed", "javascript:S1128")]
        after = [row("new", "javascript:S1854")]
        result = verdict(before, after, "javascript:S1128")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["added"]), 1)

    def test_passes_when_a_second_old_issue_also_disappears(self):
        before = [row("fixed", "javascript:S1128"), row("kept", "javascript:S1481")]
        after = []
        self.assertTrue(verdict(before, after, "javascript:S1128")["ok"])

    def test_fails_when_the_fixed_issue_is_still_there(self):
        before = [row("fixed", "javascript:S1128")]
        after = [row("fixed", "javascript:S1128")]
        self.assertFalse(verdict(before, after, "javascript:S1128")["ok"])


if __name__ == "__main__":
    unittest.main()
