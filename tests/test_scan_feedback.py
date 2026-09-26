import unittest
from unittest.mock import patch

from cleardebt import scan_progress
from cleardebt.assign import refresh_backlog


class ScanFeedbackTest(unittest.TestCase):
    def tearDown(self):
        scan_progress.clear("scan-feedback-test")

    def test_success_exposes_result_and_issue_count(self):
        with patch("cleardebt.baseline_scan.scan_baseline", return_value={"analysis_date": "2026-09-26T10:19:28+0000"}), \
                patch("cleardebt.assign.list_backlog_issues", return_value=[{"rule": "a"}]), \
                patch("cleardebt.assign.record_first_seen"), \
                patch("cleardebt.assign.save_snapshot"):
            refresh_backlog("scan-feedback-test")
        result = scan_progress.read("scan-feedback-test")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["issue_count"], 1)
        self.assertIn("刚重扫过", result["note"])
        self.assertIn("北京时间 2026-09-26 18:19", result["note"])
        self.assertNotIn("+0000", result["note"])

    def test_failed_scan_exposes_error_even_when_old_issues_remain(self):
        with patch("cleardebt.baseline_scan.scan_baseline", side_effect=ValueError("scanner failed")), \
                patch("cleardebt.assign.list_backlog_issues", return_value=[{"rule": "a"}]), \
                patch("cleardebt.assign.record_first_seen"), \
                patch("cleardebt.assign.save_snapshot"):
            refresh_backlog("scan-feedback-test")
        result = scan_progress.read("scan-feedback-test")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["issue_count"], 1)
        self.assertIn("scanner failed", result["note"])

    def test_completed_progress_does_not_block_another_scan(self):
        from cleardebt.api import _scan_threads, api_list_issues

        _scan_threads.pop("scan-feedback-test", None)
        scan_progress.complete("scan-feedback-test", ok=True, note="old", issue_count=0)
        with patch("threading.Thread") as thread:
            result = api_list_issues({"repo": "scan-feedback-test"})
        self.assertFalse(result["already_running"])
        thread.return_value.start.assert_called_once()
        self.assertEqual(scan_progress.read("scan-feedback-test")["status"], "running")
        _scan_threads.pop("scan-feedback-test", None)


if __name__ == "__main__":
    unittest.main()
