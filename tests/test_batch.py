import unittest

from cleardebt.batch import file_kind, plan_merges


def row(rule: str, level: str, fingerprint: str, path: str = "src/orders.js") -> dict:
    return {
        "rule": rule,
        "level": level,
        "fingerprint": fingerprint,
        "reason": level,
        "path": path,
    }


class PlanMergesTest(unittest.TestCase):
    def test_different_rules_are_separate_and_the_cap_holds_the_rest(self):
        rows = [
            row("javascript:S1128", "L1", "a"),
            row("javascript:S1481", "L1", "b"),
            row("javascript:S1656", "L1", "c"),
            row("javascript:S6679", "L2", "d"),
        ]
        existing = {"a": {"web_url": "https://gitlab.example/1"}}
        decisions = {(item["rule"], item["file_kind"]): item for item in plan_merges(rows, existing, opened_today=1, cap=2)}
        self.assertEqual(decisions[("javascript:S1128", "js")]["action"], "already")
        self.assertEqual(decisions[("javascript:S1481", "js")]["action"], "open")
        self.assertEqual(decisions[("javascript:S1656", "js")]["action"], "held")
        self.assertEqual(decisions[("javascript:S6679", "js")]["action"], "no_mr")

    def test_same_rule_splits_by_file_kind(self):
        rows = [
            row("javascript:S1128", "L1", "a", "src/a.js"),
            row("typescript:S1128", "L1", "b", "src/b.ts"),
        ]
        # Same Sonar rule number but different file kinds should not share one MR group key via path kind.
        # Rules strings differ (javascript vs typescript) — also test same rule string different extensions:
        rows = [
            row("javascript:S1128", "L1", "a", "src/a.js"),
            row("javascript:S1128", "L1", "b", "src/b.ts"),
        ]
        decisions = plan_merges(rows, {}, opened_today=0, cap=5)
        self.assertEqual(len(decisions), 2)
        kinds = sorted(item["file_kind"] for item in decisions)
        self.assertEqual(kinds, ["js", "ts"])
        self.assertTrue(all(item["action"] == "open" for item in decisions))

    def test_pauses_when_open_agent_mrs_hit_the_limit(self):
        rows = [row("javascript:S1128", "L1", "a")]
        decisions = plan_merges(
            rows,
            {},
            opened_today=0,
            open_agent_mrs=3,
            pause_when_open_mrs=3,
        )
        self.assertEqual(decisions[0]["action"], "held")
        self.assertIn("暂停", decisions[0]["reason"])

    def test_file_kind_from_path(self):
        self.assertEqual(file_kind("src/a.ts"), "ts")
        self.assertEqual(file_kind("Makefile"), "unknown")


if __name__ == "__main__":
    unittest.main()
