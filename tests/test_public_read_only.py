import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cleardebt.checkout import checkout_default
from cleardebt.controls import backlog_gate, connect_integration, credentials_for
from cleardebt.hosting import HostingError, resolve_repository
from cleardebt.request_fix import request_fix_gate


class PublicReadOnlyTest(unittest.TestCase):
    def test_public_repo_resolves_without_hosting_token(self):
        with patch("cleardebt.hosting._ls_remote_default", return_value="main") as probe:
            repo = resolve_repository("https://github.com/acme/app", "")
        self.assertEqual(repo["project_path"], "acme/app")
        self.assertIsNone(repo["project_id"])
        probe.assert_called_once_with("https://github.com/acme/app.git", anonymous=True)

    def test_private_or_non_https_repo_is_refused_without_token(self):
        with patch("cleardebt.hosting._ls_remote_default", return_value=""):
            with self.assertRaisesRegex(HostingError, "无法匿名读取"):
                resolve_repository("https://github.com/acme/private", "")
        with self.assertRaisesRegex(HostingError, "HTTPS"):
            resolve_repository("http://github.com/acme/app", "")

    def test_setup_stores_a_tokenless_binding_as_read_only(self):
        row = (
            True, False, ["app"], True, "http://sonar", "", "sonar-token", "", None,
            False, [], {}, True, "", "", "",
        )
        with (
            patch("cleardebt.controls._row", return_value=row),
            patch("cleardebt.controls._check_sonar"),
            patch("cleardebt.hosting._ls_remote_default", return_value="main"),
            patch("cleardebt.controls.save_integration", return_value={}) as save,
        ):
            connect_integration(
                sonar_url="http://sonar",
                sonar_token="sonar-token",
                gitlab_token="",
                whitelist=["app"],
                bindings=[{"sonar_key": "app", "gitlab_url": "https://github.com/acme/app"}],
            )
        binding = save.call_args.kwargs["bindings"][0]
        self.assertTrue(binding["read_only"])
        saved = credentials_for([binding], "", "app", tokens={"github": "", "gitlab": ""})
        self.assertEqual(saved["token"], "")
        self.assertTrue(saved["read_only"])

    def test_read_only_repo_cannot_enter_repair_paths(self):
        settings = {
            "configured": True,
            "enabled": True,
            "whitelist": ["app"],
            "bindings": [{"sonar_key": "app", "read_only": True}],
        }
        self.assertIn("只能扫描和查看问题", backlog_gate(settings, "app"))
        self.assertIn("只能扫描和查看问题", request_fix_gate(settings, "app"))

    def test_read_only_repo_can_run_baseline_scan(self):
        from cleardebt.baseline_scan import scan_baseline

        saved = {"provider": "github", "remote": "https://github.com/acme/app.git", "token": "", "read_only": True}
        with (
            patch("cleardebt.controls.gitlab_credentials", return_value=saved),
            patch("cleardebt.issue_graph.sonar_base_url", return_value="http://sonar"),
            patch("list_issues.load_token", return_value="sonar-token"),
            patch("cleardebt.baseline_scan.ensure_sonar"),
            patch("cleardebt.checkout.checkout_default", return_value="main") as checkout,
            patch("cleardebt.languages.sonar_sources_value", return_value="."),
            patch("cleardebt.baseline_scan._run_scanner") as scanner,
            patch("cleardebt.baseline_scan._wait_processed"),
            patch("cleardebt.baseline_scan._analysis_date", return_value="2026-09-25") as analyzed,
            patch("cleardebt.baseline_scan.report_progress"),
            patch("cleardebt.baseline_scan.clear_progress"),
        ):
            result = scan_baseline("app")
        self.assertEqual(result["analysis_date"], "2026-09-25")
        self.assertIs(checkout.call_args.args[1], saved)
        self.assertEqual(scanner.call_args.args[2], "sonar-token")
        analyzed.assert_called_once()

    def test_checkout_works_with_an_empty_hosting_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / "origin"
            origin.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=origin, check=True)
            (origin / "app.js").write_text("const answer = 42;\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.js"], cwd=origin, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=origin, check=True, capture_output=True)
            saved = {"remote": str(origin), "url": str(origin), "token": "", "provider": "github"}
            branch = checkout_default(root / "work", saved)
            self.assertEqual(branch, "main")
            self.assertEqual((root / "work" / "app.js").read_text(encoding="utf-8"), "const answer = 42;\n")


if __name__ == "__main__":
    unittest.main()
