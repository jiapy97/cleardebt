import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cleardebt.baseline_scan import _is_fresh, scan_baseline


class FreshSkipTest(unittest.TestCase):
    def test_recent_analysis_skips_scan(self):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S%z")
        with (
            patch("cleardebt.controls.gitlab_credentials", return_value={"remote": "x"}),
            patch("cleardebt.issue_graph.sonar_base_url", return_value="http://sonar"),
            patch("list_issues.load_token", return_value="token"),
            patch("cleardebt.baseline_scan._analysis_date", return_value=stamp),
            patch("cleardebt.checkout.checkout_default") as clone,
        ):
            out = scan_baseline("toy-js")
        self.assertTrue(out.get("skipped"))
        clone.assert_not_called()

    def test_stale_analysis_scans(self):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S%z")
        with (
            patch("cleardebt.controls.gitlab_credentials", return_value={"remote": "x"}),
            patch("cleardebt.issue_graph.sonar_base_url", return_value="http://sonar"),
            patch("list_issues.load_token", return_value="token"),
            patch("cleardebt.baseline_scan._analysis_date", side_effect=[stamp, stamp]),
            patch("cleardebt.checkout.checkout_default"),
            patch("cleardebt.languages.sonar_sources_value", return_value="src"),
            patch("cleardebt.baseline_scan._run_scanner") as run,
            patch("cleardebt.baseline_scan._wait_processed"),
        ):
            out = scan_baseline("toy-js")
        self.assertFalse(out.get("skipped"))
        run.assert_called_once()

    def test_is_fresh_edge_cases(self):
        self.assertFalse(_is_fresh("", 10))
        self.assertFalse(_is_fresh("not-a-date", 10))
        self.assertFalse(_is_fresh("2026-09-23T03:52:03+0000", 0))


if __name__ == "__main__":
    unittest.main()
