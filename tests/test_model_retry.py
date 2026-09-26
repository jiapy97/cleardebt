import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from cleardebt.b_fix import ModelOutputError, model_ladder
from cleardebt.issue_graph import build_graph


def _blank_state(**overrides) -> dict:
    state = {
        "fingerprint": "fp",
        "rule": "javascript:S1128",
        "path": "src/a.js",
        "message": "Remove this unused import of 'x'.",
        "start_line": 1,
        "end_line": 1,
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
        "fix_attempt": 0,
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


def _failing_rescan_once():
    calls = {"n": 0}

    def _node(state):
        calls["n"] += 1
        ok = calls["n"] > 1
        return {
            "rescan_ok": ok,
            "rescan_removed": (
                [{"fingerprint": state["fingerprint"], "rule": state["rule"]}] if ok else []
            ),
            "rescan_added": [],
            "history": ["rescan"],
        }

    _node.calls = calls
    return _node


def _passing_tests(_state):
    return {"tests_passed": True, "uncovered_lines": [], "history": ["test"]}


class ModelLadderTest(unittest.TestCase):
    def test_default_model_uses_current_deepseek_name(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(model_ladder(), ["deepseek-flash"])

    def test_models_env_builds_ladder(self):
        with patch.dict(
            os.environ,
            {"CLEARDEBT_LLM_MODELS": "cheap,pricey", "CLEARDEBT_LLM_MODEL": "ignored"},
            clear=False,
        ):
            self.assertEqual(model_ladder(), ["cheap", "pricey"])

    def test_upgrade_model_appends(self):
        with patch.dict(
            os.environ,
            {
                "CLEARDEBT_LLM_MODELS": "",
                "CLEARDEBT_LLM_MODEL": "base",
                "CLEARDEBT_LLM_UPGRADE_MODEL": "better",
            },
            clear=False,
        ):
            self.assertEqual(model_ladder(), ["base", "better"])


class ModelRetryGraphTest(unittest.TestCase):
    def test_rescan_failure_retries_with_next_model(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "src"
            source.mkdir()
            before = 'import x from "y";\nexport const a = 1;\n'
            (source / "a.js").write_text(before, encoding="utf-8")
            first = ('import x from "y";\n', "")
            second = ('import x from "y";\n', "")
            models = []

            def propose(**kwargs):
                models.append(kwargs.get("model"))
                if kwargs.get("model") == "cheap":
                    return first
                return second

            rescan = _failing_rescan_once()
            graph = build_graph(MemorySaver(), rescan_node=rescan, test_node=_passing_tests)
            with (
                patch.dict(
                    os.environ,
                    {
                        "CLEARDEBT_MECHANICAL_FIX": "0",
                        "CLEARDEBT_LLM_MODELS": "cheap,pricey",
                    },
                    clear=False,
                ),
                patch("cleardebt.issue_graph.propose_patch", side_effect=propose),
                patch("cleardebt.issue_graph.apply_mechanical", return_value=None),
                patch("cleardebt.issue_graph.collect", return_value={"nearby": "1|import"}),
                patch("cleardebt.controls.load_controls", return_value={"retrieve": False}),
                patch("cleardebt.triage.listed", return_value=True),
            ):
                result = graph.invoke(
                    _blank_state(work_dir=str(work), path="src/a.js"),
                    {"configurable": {"thread_id": "retry-rescan"}},
                )
        self.assertEqual(models, ["cheap", "pricey"])
        self.assertEqual(result["level"], "L1")
        self.assertIn("retry_fix", result["history"])
        self.assertEqual(rescan.calls["n"], 2)

    def test_parse_failure_retries_then_l3(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "src"
            source.mkdir()
            (source / "a.js").write_text('import x from "y";\n', encoding="utf-8")
            models = []

            def propose(**kwargs):
                models.append(kwargs.get("model"))
                raise ModelOutputError(f"bad from {kwargs.get('model')}")

            graph = build_graph(MemorySaver(), rescan_node=_passing_rescan, test_node=_passing_tests)
            with (
                patch.dict(
                    os.environ,
                    {
                        "CLEARDEBT_MECHANICAL_FIX": "0",
                        "CLEARDEBT_LLM_MODELS": "cheap,pricey",
                    },
                    clear=False,
                ),
                patch("cleardebt.issue_graph.propose_patch", side_effect=propose),
                patch("cleardebt.issue_graph.apply_mechanical", return_value=None),
                patch("cleardebt.issue_graph.collect", return_value={}),
                patch("cleardebt.controls.load_controls", return_value={"retrieve": False}),
                patch("cleardebt.triage.listed", return_value=True),
            ):
                result = graph.invoke(
                    _blank_state(work_dir=str(work), path="src/a.js"),
                    {"configurable": {"thread_id": "retry-parse"}},
                )
        self.assertEqual(models, ["cheap", "pricey"])
        self.assertEqual(result["level"], "L3")
        self.assertIn("retry_fix", result["history"])
        self.assertIn("bad from pricey", result["reason"])


if __name__ == "__main__":
    unittest.main()
