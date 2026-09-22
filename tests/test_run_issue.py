import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.batch_worker import run_one
from cleardebt.gitlab_mr import NotEligible
from open_merge_request import execute as open_merge_request
from run_issue import execute, main


class RunOneProjectTest(unittest.TestCase):
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
