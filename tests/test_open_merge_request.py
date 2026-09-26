import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.gitlab_mr import NotEligible
from open_merge_request import _apply_verified_files, create_merge_request, ensure_verified_base, project_access_level
import open_merge_request


class OpenMergeRequestProjectTest(unittest.TestCase):
    def test_changed_target_branch_rejects_old_verified_patch(self):
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "a.js").write_text("const a = 1;\n")
            subprocess.run(["git", "add", "a.js"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
            base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            ensure_verified_base(repo, {"base_commit": base})
            (repo / "a.js").write_text("const a = 2;\n")
            subprocess.run(["git", "commit", "-am", "new"], cwd=repo, check=True, capture_output=True)
            with self.assertRaisesRegex(NotEligible, "已变化"):
                ensure_verified_base(repo, {"base_commit": base})

    def test_applies_every_file_from_the_verified_patch_set(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            paths = _apply_verified_files(
                repo,
                [
                    {"path": "package.json", "after": "package\n"},
                    {"path": "package-lock.json", "after": "lock\n"},
                ],
            )
            self.assertEqual(paths, ["package.json", "package-lock.json"])
            self.assertEqual((repo / "package.json").read_text(), "package\n")
            self.assertEqual((repo / "package-lock.json").read_text(), "lock\n")

    def test_source_has_no_hardcoded_project(self):
        self.assertFalse(hasattr(open_merge_request, "PROJECT_ID"))
        self.assertFalse(hasattr(open_merge_request, "PROJECT_PATH"))
        self.assertFalse(hasattr(open_merge_request, "REMOTE"))

    def test_missing_project_does_not_call_gitlab(self):
        with patch("open_merge_request.urllib.request.urlopen") as urlopen:
            with self.assertRaises(NotEligible) as access:
                project_access_level("token")
            with self.assertRaises(NotEligible) as opened:
                create_merge_request(
                    "token",
                    source_branch="cleardebt/s1128",
                    target_branch="main",
                    title="去掉未使用的 import",
                    description="待审",
                )
        self.assertIn("碰不到任何仓库", str(access.exception))
        self.assertIn("碰不到任何仓库", str(opened.exception))
        urlopen.assert_not_called()

    def test_given_project_is_the_one_called(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"iid": 7, "web_url": "https://example.test/mr/7"}'

        with patch("open_merge_request.urllib.request.urlopen", return_value=Response()) as urlopen:
            opened = create_merge_request(
                "token",
                source_branch="cleardebt/s1128",
                target_branch="main",
                title="去掉未使用的 import",
                description="待审",
                project_id=4242,
            )
        request = urlopen.call_args.args[0]
        self.assertIn("/projects/4242/merge_requests", request.full_url)
        self.assertEqual(opened["iid"], 7)

    def test_merge_request_goes_to_the_given_gitlab_host(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"iid": 7, "web_url": "https://git.example/mr/7"}'

        with patch("open_merge_request.urllib.request.urlopen", return_value=Response()) as urlopen:
            create_merge_request(
                "token",
                source_branch="cleardebt/s1128",
                target_branch="main",
                title="去掉未使用的 import",
                description="待审",
                project_id=4242,
                gitlab_url="https://git.example/group/app",
            )
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith("https://git.example/api/v4/projects/4242/merge_requests"))

    def test_run_git_reports_stderr_and_hides_the_token(self):
        completed = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="fatal: auth secret-token failed\n",
        )
        with patch("open_merge_request.subprocess.run", return_value=completed) as run:
            with self.assertRaises(RuntimeError) as caught:
                open_merge_request.run_git(Path("."), ["push", "origin", "cleardebt/s3516"], "secret-token")
        text = str(caught.exception)
        self.assertIn("auth *** failed", text)
        self.assertNotIn("secret-token", text)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["git", "-c", "credential.helper="])
        self.assertIn("cleardebt/s3516", command)


if __name__ == "__main__":
    unittest.main()
