import asyncio
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.batch_worker import run_one
from cleardebt.gitlab_mr import NotEligible
from open_merge_request import execute as open_merge_request
from run_issue import _checkpoint_for_issue, _find_issue, _initial_state, execute, execution_fingerprint, main


class RunOneProjectTest(unittest.TestCase):
    def test_find_issue_uses_sonar_key_when_rule_and_file_repeat(self):
        issues = [
            {"rule": "javascript:S1128", "component": "toy-js:src/a.js", "key": "first",
             "textRange": {"startLine": 2, "endLine": 2}},
            {"rule": "javascript:S1128", "component": "toy-js:src/a.js", "key": "second",
             "textRange": {"startLine": 8, "endLine": 8}},
        ]
        with (
            patch("run_issue.fetch_issues", return_value=issues),
            patch("run_issue.rescan_check.api_text", return_value="\n".join(str(i) for i in range(1, 11))),
        ):
            found = _find_issue("token", "javascript:S1128", "toy-js", path="src/a.js", issue_key="second")
        self.assertEqual(found["start_line"], 8)

    def test_run_issue_passes_fresh_sonar_signals_to_graph(self):
        row = {"rule": "javascript:S1128", "component": "toy-js:src/a.js", "key": "one",
               "type": "CODE_SMELL", "severity": "MAJOR", "effort": "5min",
               "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "HIGH"}],
               "quickFixAvailable": True}
        with (
            patch("run_issue.fetch_issues", return_value=[row]),
            patch("run_issue.rescan_check.api_text", return_value="const a = 1;\n"),
        ):
            issue = _find_issue("token", "javascript:S1128", "toy-js", path="src/a.js", issue_key="one")
        state = _initial_state(issue, Path("/tmp/work"))
        self.assertEqual(state["sonar_type"], "CODE_SMELL")
        self.assertEqual(state["sonar_impacts"][0]["severity"], "HIGH")
        self.assertEqual(state["sonar_effort"], "5min")
        self.assertTrue(state["quick_fix"])

    def test_changed_issue_tier_does_not_reuse_old_completed_checkpoint(self):
        finished = type("Snapshot", (), {"values": {"tier": "C", "level": "C"}, "next": ()})()
        empty = type("Snapshot", (), {"values": {}, "next": ()})()
        graph = type("Graph", (), {"get_state": lambda self, config: finished if config["configurable"]["thread_id"] == "old" else empty})()
        issue = {"fingerprint": "old", "rule": "javascript:S1186", "sonar_type": "CODE_SMELL",
                 "sonar_impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "LOW"}]}
        with patch("cleardebt.triage.listed", return_value=True):
            config, snapshot, action = _checkpoint_for_issue(graph, issue)
        self.assertEqual(action, "start")
        self.assertIs(snapshot, empty)
        self.assertNotEqual(issue["fingerprint"], "old")
        self.assertEqual(config["configurable"]["thread_id"], issue["fingerprint"])

    def test_execution_identity_is_scoped_to_project_and_ref(self):
        base = execution_fingerprint("same-sonar-fp", "alpha")
        self.assertNotEqual(base, execution_fingerprint("same-sonar-fp", "beta"))
        self.assertNotEqual(base, execution_fingerprint("same-sonar-fp", "alpha", git_branch="feature/x"))
        self.assertNotEqual(
            execution_fingerprint("same-sonar-fp", "alpha", git_branch="feature/x"),
            execution_fingerprint(
                "same-sonar-fp",
                "alpha",
                git_branch="feature/x",
                pull_request="42",
            ),
        )
        self.assertNotEqual(base, execution_fingerprint("same-sonar-fp", "alpha", agent_mode=True, base_commit="one"))
        self.assertNotEqual(
            execution_fingerprint("same-sonar-fp", "alpha", agent_mode=True, base_commit="one"),
            execution_fingerprint("same-sonar-fp", "alpha", agent_mode=True, base_commit="two"),
        )
        old_protocol = hashlib.sha256(b"alpha\ndefault\nsame-sonar-fp\nagent:v1\none").hexdigest()
        self.assertNotEqual(old_protocol, execution_fingerprint(
            "same-sonar-fp", "alpha", agent_mode=True, base_commit="one",
        ))
        self.assertNotEqual(base, execution_fingerprint(
            "same-sonar-fp", "alpha", benchmark_run_id="fresh-run",
        ))
        self.assertNotEqual(
            execution_fingerprint("same-sonar-fp", "alpha", benchmark_run_id="run-a"),
            execution_fingerprint("same-sonar-fp", "alpha", benchmark_run_id="run-b"),
        )

    def test_read_only_benchmark_rejects_any_other_binding(self):
        settings = {"configured": True, "enabled": True, "whitelist": ["bench-dayjs"]}
        with (
            patch.dict("os.environ", {"CLEARDEBT_BENCH_RUN_ID": "test-run"}),
            patch("run_issue._find_issue") as find,
            patch("cleardebt.controls.load_controls", return_value=settings),
            patch("cleardebt.controls.gitlab_credentials", return_value={
                "url": "https://github.com/another/repo", "read_only": True,
            }),
        ):
            with self.assertRaises(SystemExit) as refused:
                execute("javascript:S1940", "bench-dayjs", benchmark_read_only=True,
                        benchmark_sha="436bde0bcded312781cbe45dc2b0ef079a36d8e3")
        self.assertIn("只读评测", str(refused.exception))
        find.assert_not_called()

    def test_missing_or_unlisted_project_does_not_run(self):
        settings = {"configured": True, "enabled": True, "whitelist": ["alpha"]}
        with (
            patch("run_issue._find_issue") as find,
            patch("cleardebt.controls.load_controls", return_value=settings),
        ):
            with self.assertRaises(SystemExit) as missing:
                execute("javascript:S1128")
            with self.assertRaises(SystemExit) as unlisted:
                execute("javascript:S1128", "beta")
        self.assertIn("不会跑", str(missing.exception))
        self.assertIn("不在白名单", str(unlisted.exception))
        find.assert_not_called()

    def test_command_without_a_project_does_not_run(self):
        with patch("sys.argv", ["run_issue.py", "javascript:S1128"]), patch("run_issue.execute") as run:
            self.assertEqual(main(), 1)
        run.assert_not_called()

    def test_merge_request_without_a_project_does_not_look_up_an_issue(self):
        with patch("open_merge_request._find_issue") as find:
            with self.assertRaises(NotEligible) as caught:
                open_merge_request()
        self.assertIn("不会跑", str(caught.exception))
        find.assert_not_called()

    def test_worker_without_a_project_does_not_run(self):
        with patch("cleardebt.batch_worker.execute") as run:
            missing = asyncio.run(run_one({}, "javascript:S1128"))
            asyncio.run(run_one({}, "javascript:S1128", "alpha"))
        self.assertFalse(missing["started"])
        self.assertIn("不会跑", missing["reason"])
        run.assert_called_once_with("javascript:S1128", "alpha")


if __name__ == "__main__":
    unittest.main()
