import unittest

from cleardebt.batch import plan_merges


def row(rule: str, level: str, fingerprint: str) -> dict:
    return {"rule": rule, "level": level, "fingerprint": fingerprint, "reason": level, "path": "src/orders.js"}


class PlanMergesTest(unittest.TestCase):
    def test_different_rules_are_separate_and_the_cap_holds_the_rest(self):
        rows = [
            row("javascript:S1128", "L1", "a"),
            row("javascript:S1481", "L1", "b"),
            row("javascript:S1656", "L1", "c"),
            row("javascript:S6679", "L2", "d"),
        ]
        existing = {"a": {"web_url": "https://gitlab.example/1"}}
        decisions = {item["rule"]: item for item in plan_merges(rows, existing, opened_today=1, cap=2)}
        self.assertEqual(decisions["javascript:S1128"]["action"], "already")
        self.assertEqual(decisions["javascript:S1481"]["action"], "open")
        self.assertEqual(decisions["javascript:S1656"]["action"], "held")
        self.assertEqual(decisions["javascript:S6679"]["action"], "no_mr")


if __name__ == "__main__":
    unittest.main()
