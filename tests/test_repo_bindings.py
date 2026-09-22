import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.checkout import checkout_default
from cleardebt.controls import credentials_for, legacy_bindings, merge_bindings
from cleardebt.review import render_page
from run_batch import _open_one, run_controlled, run_whitelist
from run_issue import _prepare_work_dir


def _git_repo(path: Path, branch: str, filename: str, content: str) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", branch], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "cleardebt@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "ClearDebt"], cwd=path, check=True)
    target = path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


class BindingTest(unittest.TestCase):
    def test_one_saved_address_is_not_copied_onto_every_project(self):
        bindings = legacy_bindings(["alpha", "beta"], "https://gitlab.example/only/one", 9, [])
        self.assertIsNone(credentials_for(bindings, "token", "alpha"))
        self.assertIsNone(credentials_for(bindings, "token", "beta"))
        self.assertIsNone(credentials_for(bindings, "token", None))

    def test_the_old_single_project_still_binds_that_one_key(self):
        bindings = legacy_bindings(["toy-js"], "https://gitlab.example/g/test", 9, [])
        saved = credentials_for(bindings, "token", "toy-js")
        self.assertEqual(saved["project_id"], 9)
        self.assertEqual(saved["remote"], "https://gitlab.example/g/test.git")
        self.assertIsNone(credentials_for(bindings, "token", "other"))

    def test_each_stored_project_keeps_its_own_remote(self):
        stored = [
            {"sonar_key": "alpha", "gitlab_url": "https://git.example/g/alpha", "project_id": 11},
            {"sonar_key": "beta", "gitlab_url": "https://git.example/g/beta", "project_id": 22},
            {"sonar_key": "orphan", "gitlab_url": "", "project_id": None},
        ]
        self.assertEqual(credentials_for(stored, "t", "alpha")["project_id"], 11)
        self.assertEqual(credentials_for(stored, "t", "beta")["remote"], "https://git.example/g/beta.git")
        self.assertIsNone(credentials_for(stored, "t", "orphan"))
        self.assertIsNone(credentials_for(stored, "t", None))

    def test_lines_pair_a_key_with_its_own_address(self):
        paired = merge_bindings(
            ["alpha", "orphan"],
            "alpha https://git.example/g/alpha\nbeta=https://git.example/g/beta\n",
        )
        self.assertEqual(
            paired,
            [
                {"sonar_key": "alpha", "gitlab_url": "https://git.example/g/alpha"},
                {"sonar_key": "orphan", "gitlab_url": ""},
                {"sonar_key": "beta", "gitlab_url": "https://git.example/g/beta"},
            ],
        )

    def test_two_local_remotes_are_not_mixed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha = root / "alpha"
            beta = root / "beta"
            _git_repo(alpha, "alpha-branch", "src/a.js", "from-alpha\n")
            _git_repo(beta, "beta-branch", "src/b.js", "from-beta\n")
            saved = {
                "alpha": {"remote": str(alpha), "branch": "alpha-branch", "token": "local-token"},
                "beta": {"remote": str(beta), "branch": "beta-branch", "token": "local-token"},
            }
            with patch("cleardebt.checkout._default_branch", side_effect=lambda item: item["branch"]):
                branch_a = checkout_default(root / "work-a", saved["alpha"])
                branch_b = checkout_default(root / "work-b", saved["beta"])
            self.assertEqual(branch_a, "alpha-branch")
            self.assertEqual(branch_b, "beta-branch")
            self.assertEqual((root / "work-a" / "src" / "a.js").read_text(encoding="utf-8"), "from-alpha\n")
            self.assertFalse((root / "work-a" / "src" / "b.js").exists())
            self.assertEqual((root / "work-b" / "src" / "b.js").read_text(encoding="utf-8"), "from-beta\n")
            self.assertFalse((root / "work-b" / "src" / "a.js").exists())

    def test_unbound_project_does_not_clone_another_repo(self):
        with (
            patch("cleardebt.controls.gitlab_credentials", return_value=None),
            patch("cleardebt.checkout.checkout_default") as clone,
        ):
            with self.assertRaises(SystemExit) as caught:
                _prepare_work_dir(Path("/tmp/cleardebt-unbound"), {"project": "orphan", "path": "src/a.js"})
        self.assertIn("不去改别的仓库", str(caught.exception))
        clone.assert_not_called()

    def test_each_open_uses_that_repos_remote_and_project(self):
        projects = {
            "alpha": {
                "url": "https://git.alpha.example/g/alpha",
                "token": "t",
                "project_id": 11,
                "remote": "/repos/alpha",
            },
            "beta": {
                "url": "https://git.beta.example/g/beta",
                "token": "t",
                "project_id": 22,
                "remote": "/repos/beta",
            },
        }
        clones = []
        opened = []

        def creds(key=None):
            return projects.get(key)

        def checkout(dest: Path, saved: dict) -> str:
            clones.append((saved["remote"], saved["project_id"]))
            (dest / "src").mkdir(parents=True, exist_ok=True)
            return "develop" if saved["project_id"] == 11 else "trunk"

        def create(token: str, **kwargs):
            opened.append(kwargs)
            return {"iid": kwargs["project_id"], "web_url": kwargs["gitlab_url"] + "/mr"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            (work / "src").mkdir(parents=True)
            (work / "src" / "a.js").write_text("fixed\n", encoding="utf-8")
            issues = []
            for name in ("alpha", "beta"):
                issues.append(
                    {
                        "rule": "javascript:S1128",
                        "fingerprint": name + "fp0000",
                        "path": "src/a.js",
                        "work_dir": str(work),
                        "level": "L1",
                        "project": name,
                        "reason": "过了",
                    }
                )
            with (
                patch("run_batch.ROOT", root),
                patch("run_batch.gitlab_credentials", side_effect=creds),
                patch("run_batch.checkout_default", side_effect=checkout),
                patch("run_batch.git"),
                patch("run_batch.push"),
                patch("run_batch.create_merge_request", side_effect=create),
                patch("run_batch.save_merge_request"),
                patch("run_batch.find_merge_request", return_value=None),
            ):
                first = _open_one("t", issues[0], "alpha")
                second = _open_one("t", issues[1], "beta")
                with self.assertRaises(SystemExit) as caught:
                    _open_one("t", {**issues[0], "project": "orphan", "fingerprint": "orphanfp0000"}, "orphan")

        self.assertEqual(clones, [("/repos/alpha", 11), ("/repos/beta", 22)])
        self.assertEqual([item["project_id"] for item in opened], [11, 22])
        self.assertEqual(opened[0]["gitlab_url"], "https://git.alpha.example/g/alpha")
        self.assertEqual(opened[1]["gitlab_url"], "https://git.beta.example/g/beta")
        self.assertEqual(first["target_branch"], "develop")
        self.assertEqual(second["target_branch"], "trunk")
        self.assertIn("不去改别的仓库", str(caught.exception))
        self.assertEqual(len(clones), 2)

    def test_round_skips_an_unmatched_repo_and_still_runs_the_others(self):
        settings = {
            "configured": True,
            "enabled": True,
            "dry_run": True,
            "whitelist": ["alpha", "beta", "orphan"],
        }
        projects = {
            "alpha": {"url": "https://git.example/g/alpha", "token": "t", "project_id": 11, "remote": "/repos/alpha"},
            "beta": {"url": "https://git.example/g/beta", "token": "t", "project_id": 22, "remote": "/repos/beta"},
        }
        seen = []
        reports = []

        def creds(key=None):
            return projects.get(key)

        def execute(rule, project="toy-js"):
            seen.append(project)
            return {
                "rule": rule,
                "fingerprint": project + "fp",
                "path": "src/a.js",
                "level": "L2",
                "reason": "建议",
                "project": project,
                "work_dir": "/tmp/none",
            }

        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.gitlab_credentials", side_effect=creds),
            patch("run_batch._mr_count", return_value=0),
            patch("run_batch._opened_today", return_value=0),
            patch("run_batch.load_token", return_value="t"),
            patch("run_batch._issues", return_value=[{"rule": "javascript:S1128", "path": "src/a.js"}]),
            patch("run_batch.execute", side_effect=execute),
            patch("run_batch.find_merge_request", return_value=None),
            patch("run_batch.checkout_default") as clone,
            patch("run_batch.save_report", side_effect=lambda repo, dry_run, decisions: reports.append((repo, decisions))),
        ):
            result = run_whitelist()

        self.assertEqual(seen, ["alpha", "beta"])
        self.assertIn("不去改别的仓库", result["repos"][2]["reason"])
        clone.assert_not_called()
        combined = reports[-1]
        self.assertEqual(combined[0], "alpha、beta、orphan")
        reasons = " ".join(str(item.get("reason") or "") for item in combined[1])
        self.assertIn("不去改别的仓库", reasons)
        html = render_page(
            {"repo": combined[0], "dry_run": True, "created_at": "2026-09-22 20:00", "decisions": combined[1]}
        )
        self.assertIn("不去改别的仓库", html)
        self.assertIn("仓库：orphan", html)

    def test_controlled_skip_does_not_execute(self):
        settings = {"configured": True, "enabled": True, "dry_run": False, "whitelist": ["orphan"]}
        with (
            patch("run_batch.load_controls", return_value=settings),
            patch("run_batch.gitlab_credentials", return_value=None),
            patch("run_batch.execute") as execute,
            patch("run_batch.checkout_default") as clone,
            patch("run_batch.save_report") as save,
        ):
            outcome = run_controlled("orphan")
        self.assertFalse(outcome["started"])
        self.assertIn("不去改别的仓库", outcome["reason"])
        execute.assert_not_called()
        clone.assert_not_called()
        self.assertIn("不去改别的仓库", save.call_args.args[2][0]["reason"])


if __name__ == "__main__":
    unittest.main()
