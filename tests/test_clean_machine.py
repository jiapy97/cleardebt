"""Step 28: a clean machine runs someone else's repos, not the toy ones."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.review import render_page
from run_batch import _settle, run_whitelist


THIS_MACHINE_PROJECT = 999001
FOREIGN = {
    "alpha": {
        "url": "https://git.example/acme/alpha",
        "token": "their-gitlab-token",
        "project_id": 101,
        "remote": "/repos/alpha",
    },
    "beta": {
        "url": "https://git.example/acme/beta",
        "token": "their-gitlab-token",
        "project_id": 202,
        "remote": "/repos/beta",
    },
}


class CleanMachineTest(unittest.TestCase):
    def test_tracked_tree_has_no_tokens_or_personal_gitlab(self):
        opener = (ROOT / "scripts" / "open_merge_request.py").read_text(encoding="utf-8")
        batch = (ROOT / "scripts" / "run_batch.py").read_text(encoding="utf-8")
        listed_src = (ROOT / "scripts" / "list_issues.py").read_text(encoding="utf-8")
        rescan = (ROOT / "scripts" / "rescan_check.py").read_text(encoding="utf-8")
        self.assertNotIn("gitlab-toy", opener)
        self.assertNotIn("PROJECT_ID", opener)
        self.assertNotIn('default="toy-js"', listed_src)
        self.assertNotIn("toy-js-rescan-", rescan)
        self.assertNotIn("TARGET_BRANCH", batch)
        self.assertNotIn("999001", opener + batch)
        if not (ROOT / ".git").exists():
            return
        listed = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
        paths = listed.splitlines()
        self.assertTrue(paths)
        for path in paths:
            self.assertFalse(path.endswith(".token"), path)
            self.assertNotIn("var/", path)

    def test_dry_run_lists_their_alerts_and_opens_zero_merge_requests(self):
        settings = {
            "configured": True,
            "enabled": True,
            "dry_run": True,
            "whitelist": ["alpha", "beta"],
        }
        opened = []
        reports = []

        def creds(key=None):
            return FOREIGN.get(key)

        def execute(rule, project=""):
            return {
                "rule": rule,
                "fingerprint": f"{project}-fp-{rule}",
                "path": "src/a.js" if project == "alpha" else "src/b.js",
                "level": "L1",
                "reason": "重扫和测试都过了。",
                "project": project,
                "work_dir": "/tmp/none",
            }

        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.gitlab_credentials", side_effect=creds),
            patch("run_batch._mr_count", return_value=0),
            patch("run_batch._opened_today", return_value=0),
            patch("run_batch.load_token", return_value="their-sonar-token"),
            patch(
                "run_batch._issues",
                side_effect=lambda token, project: [{"rule": "javascript:S1128", "path": "src/x.js"}],
            ),
            patch("run_batch.execute", side_effect=execute),
            patch("run_batch.find_merge_request", return_value=None),
            patch("run_batch.create_merge_request", side_effect=lambda *a, **k: opened.append(k) or {"iid": 1, "web_url": "x"}),
            patch("run_batch.checkout_default") as clone,
            patch("run_batch.save_report", side_effect=lambda repo, dry_run, decisions: reports.append((repo, dry_run, decisions))),
        ):
            result = run_whitelist()

        self.assertTrue(result["started"])
        self.assertEqual([item["repo"] for item in result["repos"]], ["alpha", "beta"])
        self.assertEqual(result["repos"][0]["opened_now"], [])
        self.assertEqual(result["repos"][1]["opened_now"], [])
        self.assertEqual(opened, [])
        clone.assert_not_called()
        combined = reports[-1]
        self.assertTrue(combined[1])
        reasons = " ".join(str(item.get("reason") or "") for item in combined[2])
        self.assertIn("空跑，不开合并请求", reasons)
        repos = {item.get("repo") for item in combined[2]}
        self.assertEqual(repos, {"alpha", "beta"})
        html = render_page(
            {"repo": combined[0], "dry_run": True, "created_at": "2026-09-22 22:00", "decisions": combined[2]}
        )
        self.assertIn("这一轮是空跑", html)
        self.assertIn("仓库：alpha", html)
        self.assertIn("仓库：beta", html)

    def test_live_run_opens_on_their_repos_not_this_machines_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            (work / "src").mkdir(parents=True)
            (work / "src" / "a.js").write_text("fixed-a\n", encoding="utf-8")
            (work / "src" / "b.js").write_text("fixed-b\n", encoding="utf-8")
            opened = []
            clones = []

            def creds(key=None):
                return FOREIGN.get(key)

            def checkout(dest: Path, saved: dict) -> str:
                clones.append(saved["project_id"])
                (dest / "src").mkdir(parents=True, exist_ok=True)
                return "main"

            def create(token: str, **kwargs):
                opened.append(kwargs)
                self.assertNotEqual(kwargs["project_id"], THIS_MACHINE_PROJECT)
                return {"iid": kwargs["project_id"], "web_url": kwargs["gitlab_url"] + "/-/merge_requests/1"}

            alpha = {
                "rule": "javascript:S1128",
                "fingerprint": "alpha-fp-0001",
                "path": "src/a.js",
                "work_dir": str(work),
                "level": "L1",
                "project": "alpha",
                "reason": "过了",
            }
            beta = {
                "rule": "javascript:S1481",
                "fingerprint": "beta-fp-0002",
                "path": "src/b.js",
                "work_dir": str(work),
                "level": "L1",
                "project": "beta",
                "reason": "过了",
            }
            with (
                patch("run_batch.ROOT", root),
                patch("run_batch.gitlab_credentials", side_effect=creds),
                patch("run_batch.checkout_default", side_effect=checkout),
                patch("run_batch.git"),
                patch("run_batch.push"),
                patch("run_batch.create_merge_request", side_effect=create),
                patch("run_batch.save_merge_request"),
                patch("run_batch.find_merge_request", return_value=None),
                patch("run_batch._opened_today", return_value=0),
                patch("run_batch._mr_count", return_value=0),
            ):
                first = _settle([alpha], dry_run=False, repo="alpha")
                second = _settle([beta], dry_run=False, repo="beta")

        self.assertEqual(clones, [101, 202])
        self.assertEqual([item["project_id"] for item in opened], [101, 202])
        self.assertEqual(opened[0]["gitlab_url"], "https://git.example/acme/alpha")
        self.assertEqual(opened[1]["gitlab_url"], "https://git.example/acme/beta")
        self.assertEqual(first["opened_now"][0]["target_branch"], "main")
        self.assertEqual(second["opened_now"][0]["target_branch"], "main")
        self.assertNotIn(THIS_MACHINE_PROJECT, clones)
        self.assertNotIn(THIS_MACHINE_PROJECT, [item["project_id"] for item in opened])

    def test_token_loader_prefers_page_credentials_over_missing_files(self):
        import os

        from list_issues import load_token

        missing = ROOT / "deploy" / "sonarqube" / ".token.missing-for-test"
        env = {key: value for key, value in os.environ.items() if key != "SONAR_TOKEN"}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("list_issues.DEFAULT_TOKEN_FILE", missing),
            patch(
                "cleardebt.controls.sonar_credentials",
                return_value={"url": "http://sonar.example", "token": "page-token"},
            ),
        ):
            self.assertEqual(load_token(None), "page-token")


if __name__ == "__main__":
    unittest.main()
