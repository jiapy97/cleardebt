"""Closed-loop verification: failed Sonar rescan never becomes an openable L1."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from cleardebt.batch import plan_merges
from cleardebt.gitlab_mr import NotEligible, ensure_eligible
from cleardebt.issue_graph import build_graph


def _blank(**overrides):
    state = {
        "fingerprint": "fp-closed",
        "rule": "javascript:S1128",
        "path": "src/a.js",
        "message": "",
        "tier": "",
        "level": "",
        "reason": "",
        "work_dir": "",
        "before": "",
        "after": "",
        "rejections": [],
        "rescan_removed": [],
        "rescan_added": [],
        "uncovered_lines": [],
        "history": [],
    }
    state.update(overrides)
    return state


class ClosedLoopVerificationTest(unittest.TestCase):
    def test_failed_rescan_is_l3_and_cannot_open_a_merge_request(self):
        def failing_rescan(state):
            return {
                "rescan_ok": False,
                "rescan_removed": [],
                "rescan_added": [{"fingerprint": "new", "rule": "javascript:S1854", "path": "src/a.js"}],
                "history": ["rescan"],
            }

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "src").mkdir()
            before = 'import { readFileSync } from "node:fs";\n\nexport function f() {\n  return 1;\n}\n'
            (work / "src" / "a.js").write_text(before, encoding="utf-8")
            graph = build_graph(MemorySaver(), rescan_node=failing_rescan, test_node=lambda s: {})
            with patch.dict("os.environ", {"CLEARDEBT_MECHANICAL_FIX": "1"}):
                result = graph.invoke(
                    _blank(work_dir=str(work), path="src/a.js"),
                    {"configurable": {"thread_id": "closed-loop-fail"}},
                )

        self.assertEqual(result["level"], "L3")
        self.assertIn("重扫没通过", result["reason"])
        with self.assertRaises(NotEligible):
            ensure_eligible(result["level"])
        decisions = plan_merges([result], {}, opened_today=0)
        self.assertEqual(decisions[0]["action"], "no_mr")

    def test_rescan_ok_still_requires_l1_before_opening(self):
        ensure_eligible("L1")
        for level in ("L2", "L3", "C", ""):
            with self.assertRaises(NotEligible):
                ensure_eligible(level)


if __name__ == "__main__":
    unittest.main()
