import unittest
from unittest.mock import MagicMock, patch

from cleardebt.baseline_scan import scan_baseline


class BaselineScanTest(unittest.TestCase):
    def test_needs_bound_repo(self):
        with patch("cleardebt.controls.gitlab_credentials", return_value=None):
            with self.assertRaises(ValueError):
                scan_baseline("toy-js")

    def test_scans_and_reports_analysis_date(self):
        with (
            patch("cleardebt.controls.gitlab_credentials", return_value={"remote": "x", "token": "t"}),
            patch("cleardebt.checkout.checkout_default", return_value="main") as checkout,
            patch("cleardebt.issue_graph.sonar_base_url", return_value="http://sonar"),
            patch("list_issues.load_token", return_value="token"),
            patch("cleardebt.languages.sonar_sources_value", return_value="src"),
            patch("cleardebt.baseline_scan._run_scanner") as run,
            patch("cleardebt.baseline_scan._wait_processed"),
            patch("cleardebt.baseline_scan._analysis_date", return_value="2026-09-23T00:00:00+0000"),
        ):
            out = scan_baseline("toy-js")
        self.assertEqual(out["analysis_date"], "2026-09-23T00:00:00+0000")
        checkout.assert_called_once()
        run.assert_called_once()

    def test_second_scan_while_running_is_refused(self):
        import cleardebt.baseline_scan as module

        lock = module._locks.setdefault("busy-js", MagicMock())
        lock.acquire = MagicMock(return_value=False)
        try:
            with self.assertRaises(ValueError):
                scan_baseline("busy-js")
        finally:
            del module._locks["busy-js"]


if __name__ == "__main__":
    unittest.main()
