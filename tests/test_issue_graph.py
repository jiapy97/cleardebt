import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from cleardebt.issue_graph import build_graph, next_action, rescan, triage

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)


def _blank_state(**overrides) -> dict:
    state = {
        "fingerprint": "fp",
        "rule": "javascript:S2077",
        "path": "src/query.js",
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


def _passing_rescan(state):
    return {
        "rescan_ok": True,
        "rescan_removed": [{"fingerprint": state["fingerprint"], "rule": state["rule"]}],
        "rescan_added": [],
        "history": ["rescan"],
    }


def _passing_tests(_state):
    return {"tests_passed": True, "uncovered_lines": [], "history": ["test"]}


class NextActionTest(unittest.TestCase):
    def test_finished_level_is_skipped(self):
        snapshot = type("Snap", (), {"values": {"level": "L1"}, "next": ()})()
        self.assertEqual(next_action(snapshot), "skip")

    def test_pending_node_resumes(self):
        snapshot = type("Snap", (), {"values": {"tier": "A"}, "next": ("rescan",)})()
        self.assertEqual(next_action(snapshot), "resume")

    def test_empty_snapshot_starts(self):
        snapshot = type("Snap", (), {"values": {}, "next": ()})()
        self.assertEqual(next_action(snapshot), "start")

    def test_rescan_without_a_project_does_not_touch_sonar(self):
        with (
            patch("cleardebt.issue_graph.rescan_check.scan_temp_project") as scan,
            patch("cleardebt.issue_graph.rescan_check.issue_rows") as rows,
            patch("cleardebt.issue_graph.rescan_check.load_token") as token,
        ):
            with self.assertRaises(RuntimeError) as caught:
                rescan({"project": "", "work_dir": "/tmp", "rule": "javascript:S1128", "fingerprint": "fp"})
        self.assertIn("不会重扫", str(caught.exception))
        scan.assert_not_called()
        rows.assert_not_called()
        token.assert_not_called()


class IssueGraphTest(unittest.TestCase):
    def test_c_tier_stops_at_triage(self):
        graph = build_graph(MemorySaver())
        result = graph.invoke(_blank_state(), {"configurable": {"thread_id": "c-tier"}})
        self.assertEqual(result["level"], "C")
        self.assertIn("C 档不修", result["reason"])
        self.assertNotIn("不是已接入的规则", result["reason"])
        self.assertEqual(result["history"], ["triage", "decide"])
        self.assertNotIn("fix", result["history"])

    def test_secret_rule_reports_secrets_surface(self):
        from cleardebt.triage import llm_repairable, problem_surface, tier_for

        self.assertEqual(problem_surface("javascript:S2068"), "secrets")

    def test_unknown_rule_is_l3_without_a_fix(self):
        graph = build_graph(MemorySaver())
        result = graph.invoke(
            _blank_state(rule="javascript:S9999"),
            {"configurable": {"thread_id": "unknown"}},
        )
        self.assertEqual(result["level"], "L3")
        self.assertIn("不是已接入的规则", result["reason"])
        self.assertEqual(result["history"], ["triage", "decide"])

    def test_b_tier_smell_reaches_fix_preparation(self):
        from cleardebt.triage import tier_for

        self.assertEqual(tier_for("typescript:S2301"), "B")
        state = _blank_state(rule="typescript:S2301", path="src/labels.ts")
        self.assertEqual({"tier": "B", "history": ["triage"]}, triage(state))

    def test_typescript_empty_function_is_the_same_c_tier(self):
        graph = build_graph(MemorySaver())
        result = graph.invoke(
            _blank_state(rule="typescript:S1186", path="src/labels.ts"),
            {"configurable": {"thread_id": "ts-c"}},
        )
        self.assertEqual(result["tier"], "C")
        self.assertEqual(result["level"], "C")
        self.assertNotIn("不是已接入的规则", result["reason"])

    def test_typescript_unused_import_uses_the_same_fix_path(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "src"
            source.mkdir()
            (source / "labels.ts").write_text(
                'import { readFileSync } from "node:fs";\n\n'
                "export function formatLabel(name: string): string {\n"
                "  return name;\n"
                "}\n",
                encoding="utf-8",
            )
            graph = build_graph(MemorySaver(), rescan_node=_passing_rescan, test_node=_passing_tests)
            with patch.dict(os.environ, {"CLEARDEBT_MECHANICAL_FIX": "1"}):
                result = graph.invoke(
                    _blank_state(
                        fingerprint="fp-ts",
                        rule="typescript:S1128",
                        path="src/labels.ts",
                        work_dir=str(work),
                    ),
                    {"configurable": {"thread_id": "ts-import"}},
                )
            updated = (source / "labels.ts").read_text(encoding="utf-8")
        self.assertEqual(result["tier"], "A")
        self.assertEqual(result["fix_method"], "mechanical")
        self.assertEqual(result["level"], "L1")
        self.assertEqual(result["history"], ["triage", "fix", "anti_cheat", "rescan", "test", "decide"])
        self.assertNotIn("readFileSync", updated)
        self.assertIn("formatLabel", updated)

    def test_default_path_asks_the_model_for_an_a_rule_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "src"
            source.mkdir()
            before = 'import { readFileSync } from "node:fs";\n\nexport function formatLabel(name) {\n  return name;\n}\n'
            (source / "labels.js").write_text(before, encoding="utf-8")
            old = 'import { readFileSync } from "node:fs";\n\n'
            new = ""
            graph = build_graph(MemorySaver(), rescan_node=_passing_rescan, test_node=_passing_tests)
            with (
                patch.dict(os.environ, {"CLEARDEBT_MECHANICAL_FIX": "0"}, clear=False),
                patch("cleardebt.issue_graph.propose_patch", return_value=(old, new)) as propose,
                patch("cleardebt.issue_graph.apply_mechanical", return_value=None) as mechanical,
                patch("cleardebt.controls.load_controls", return_value={"retrieve": False}),
            ):
                result = graph.invoke(
                    _blank_state(
                        fingerprint="fp-llm",
                        rule="javascript:S1128",
                        path="src/labels.js",
                        work_dir=str(work),
                        message="Remove this unused import",
                    ),
                    {"configurable": {"thread_id": "llm-import"}},
                )
            updated = (source / "labels.js").read_text(encoding="utf-8")
        propose.assert_called_once()
        mechanical.assert_called_once()
        self.assertEqual(result["fix_method"], "llm")
        self.assertEqual(result["proposed_old"], old)
        self.assertEqual(result["proposed_new"], new)
        self.assertEqual(result["level"], "L1")
        self.assertNotIn("readFileSync", updated)

    def test_resume_continues_from_postgres_without_repeating_the_fix(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "src"
            source.mkdir()
            (source / "orders.js").write_text(
                'import { readFile } from "node:fs";\n\nexport function total() {\n  return 1;\n}\n',
                encoding="utf-8",
            )
            thread_id = "resume-" + uuid.uuid4().hex
            config = {"configurable": {"thread_id": thread_id}}
            initial = _blank_state(
                fingerprint="fp-resume",
                rule="javascript:S1128",
                path="src/orders.js",
                work_dir=str(work),
            )
            with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
                checkpointer.setup()
                paused = build_graph(
                    checkpointer,
                    rescan_node=_passing_rescan,
                    test_node=_passing_tests,
                    interrupt_before=["rescan"],
                )
                with patch.dict(os.environ, {"CLEARDEBT_MECHANICAL_FIX": "1"}):
                    paused.invoke(initial, config)
                midpoint = paused.get_state(config)
                self.assertEqual(midpoint.next, ("rescan",))
                self.assertEqual(midpoint.values["history"], ["triage", "fix", "anti_cheat"])
                self.assertNotIn("import ", (source / "orders.js").read_text(encoding="utf-8"))

                continued = build_graph(
                    checkpointer,
                    rescan_node=_passing_rescan,
                    test_node=_passing_tests,
                )
                result = continued.invoke(None, config)
            self.assertEqual(result["history"], ["triage", "fix", "anti_cheat", "rescan", "test", "decide"])
            self.assertEqual(result["history"].count("fix"), 1)
            self.assertEqual(result["level"], "L1")


if __name__ == "__main__":
    unittest.main()
