import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.batch_worker import WorkerSettings
from cleardebt.controls import gate
from run_batch import run_whitelist


class ControlGateTest(unittest.TestCase):
    def test_unconfigured_service_touches_nothing(self):
        reason = gate({"configured": False, "enabled": True, "whitelist": ["toy-js"]}, "toy-js")
        self.assertIn("碰不到任何仓库", reason)

    def test_kill_switch_stops_the_round(self):
        self.assertEqual(
            gate({"configured": True, "enabled": False, "whitelist": ["toy-js"]}, "toy-js"),
            "总开关关掉了，这一轮不开始。",
        )

    def test_unknown_repo_is_untouchable(self):
        reason = gate({"configured": True, "enabled": True, "whitelist": ["toy-js"]}, "other")
        self.assertIn("不在白名单里", reason)

    def test_whitelisted_repo_can_start(self):
        self.assertIsNone(gate({"configured": True, "enabled": True, "whitelist": ["toy-js"]}, "toy-js"))

    def test_whitelist_round_runs_each_repo_and_skips_the_rest(self):
        settings = {"configured": True, "enabled": True, "whitelist": ["toy-js", "toy-ts"]}
        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.run_controlled", return_value={"started": True, "opened_now": []}) as run,
        ):
            result = run_whitelist()
        self.assertTrue(result["started"])
        self.assertEqual([item["repo"] for item in result["repos"]], ["toy-js", "toy-ts"])
        self.assertEqual([call.args[0] for call in run.call_args_list], ["toy-js", "toy-ts"])

    def test_removed_repo_is_not_in_the_next_round(self):
        settings = {"configured": True, "enabled": True, "whitelist": ["toy-js"]}
        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.run_controlled", return_value={"started": True, "opened_now": []}) as run,
        ):
            result = run_whitelist()
        self.assertEqual([item["repo"] for item in result["repos"]], ["toy-js"])
        run.assert_called_once_with("toy-js")

    def test_kill_switch_does_not_touch_the_whitelist(self):
        settings = {"configured": True, "enabled": False, "whitelist": ["toy-js", "toy-ts"]}
        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.run_controlled") as run,
        ):
            result = run_whitelist()
        self.assertFalse(result["started"])
        self.assertIn("总开关", result["reason"])
        self.assertEqual(result["repos"], [])
        run.assert_not_called()

    def test_nightly_job_ticks_hourly(self):
        job = WorkerSettings.cron_jobs[0]
        self.assertEqual(job.coroutine.__name__, "nightly")
        self.assertEqual(job.minute, {0})


if __name__ == "__main__":
    unittest.main()
