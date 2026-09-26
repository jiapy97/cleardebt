import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_batch import _issues, _open_group, _open_one, _settle


class RecordDefaultBranchTest(unittest.TestCase):
    def test_issue_collection_keeps_each_file_for_the_same_rule(self):
        rows = [
            {"rule": "javascript:S1128", "component": "toy:src/a.js"},
            {"rule": "javascript:S1128", "component": "toy:src/b.js"},
            {"rule": "javascript:S1128", "component": "toy:src/a.js"},
        ]
        with (
            patch("run_batch.sonar_base_url", return_value="http://sonar"),
            patch("run_batch.fetch_issues", return_value=rows),
        ):
            self.assertEqual(
                _issues("token", "toy"),
                [
                    {"rule": "javascript:S1128", "path": "src/a.js"},
                    {"rule": "javascript:S1128", "path": "src/b.js"},
                ],
            )

    def test_group_request_commits_and_records_every_verified_file(self):
        saved = {
            "token": "t",
            "project_id": 5,
            "url": "https://example.test/g/one",
            "provider": "gitlab",
            "remote": "https://example.test/g/one.git",
        }
        issues = [
            {
                "rule": "javascript:S1128",
                "fingerprint": "aaa11111deadbeef",
                "path": "src/a.js",
                "level": "L1",
                "reason": "过了",
                "project": "toy-js",
                "changed_files": [{"path": "src/a.js", "after": "a fixed\n"}],
            },
            {
                "rule": "javascript:S1128",
                "fingerprint": "bbb22222deadbeef",
                "path": "src/b.js",
                "level": "L1",
                "reason": "过了",
                "project": "toy-js",
                "changed_files": [{"path": "src/b.js", "after": "b fixed\n"}],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = []
            with (
                patch("run_batch.ROOT", root),
                patch("run_batch.gitlab_credentials", return_value=saved),
                patch("run_batch.checkout_default", return_value="main"),
                patch("run_batch.find_merge_request", return_value=None),
                patch("run_batch.git") as git,
                patch("run_batch.push"),
                patch(
                    "cleardebt.hosting.create_request",
                    return_value={"iid": 9, "web_url": "https://example.test/9", "provider": "gitlab"},
                ),
                patch("run_batch.save_merge_request", side_effect=lambda row: records.append(dict(row))),
            ):
                opened = _open_group("t", issues, "toy-js")
            work = root / "var" / "merge" / "aaa11111dead"
            self.assertEqual((work / "src/a.js").read_text(), "a fixed\n")
            self.assertEqual((work / "src/b.js").read_text(), "b fixed\n")
            self.assertIn(
                call(work, ["add", "--", "src/a.js", "src/b.js"]),
                git.call_args_list,
            )
        self.assertEqual({row["fingerprint"] for row in records}, {"aaa11111deadbeef", "bbb22222deadbeef"})
        self.assertEqual(opened["fingerprints"], ["aaa11111deadbeef", "bbb22222deadbeef"])

    def test_records_the_cloned_default_branch_and_skips_the_same_fingerprint(self):
        fingerprint = "abc12345deadbeef"
        store: dict[str, dict] = {}

        def save(record: dict) -> None:
            store[record["fingerprint"]] = dict(record)

        def find(fp: str) -> dict | None:
            return store.get(fp)

        saved = {
            "token": "t",
            "project_id": 5,
            "url": "https://example.test/g/one",
            "provider": "gitlab",
            "remote": "https://example.test/g/one.git",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            (work / "src").mkdir(parents=True)
            (work / "src" / "orders.js").write_text("fixed\n", encoding="utf-8")
            issue = {
                "rule": "javascript:S1128",
                "fingerprint": fingerprint,
                "path": "src/orders.js",
                "work_dir": str(work),
                "level": "L1",
                "reason": "过了",
            }
            with (
                patch("run_batch.ROOT", root),
                patch("run_batch.gitlab_credentials", return_value=saved),
                patch("run_batch.checkout_default", return_value="develop") as clone,
                patch("run_batch.git"),
                patch("run_batch.push"),
                patch(
                    "cleardebt.hosting.create_request",
                    return_value={"iid": 9, "web_url": "https://example.test/9", "provider": "gitlab"},
                ) as create,
                patch("run_batch.save_merge_request", side_effect=save),
                patch("run_batch.find_merge_request", side_effect=find),
                patch("run_batch._opened_today", return_value=0),
                patch("run_batch._mr_count", return_value=1),
                patch("run_batch.load_controls", return_value={"backlog_automation": {}, "bindings": []}),
            ):
                first = _settle([issue], dry_run=False, repo="toy-js")
                second = _settle([issue], dry_run=False, repo="toy-js")
                again = _open_one("t", issue)

        batch_source = (ROOT / "scripts" / "run_batch.py").read_text(encoding="utf-8")
        opener_source = (ROOT / "scripts" / "open_merge_request.py").read_text(encoding="utf-8")
        self.assertNotIn("TARGET_BRANCH", batch_source)
        self.assertNotIn("TARGET_BRANCH", opener_source)
        self.assertEqual(store[fingerprint]["target_branch"], "develop")
        self.assertEqual(create.call_args.kwargs["target_branch"], "develop")
        self.assertEqual(create.call_args.args[0]["project_id"], 5)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(clone.call_count, 1)
        self.assertEqual(first["opened_now"][0]["target_branch"], "develop")
        self.assertEqual(second["decisions"][0]["action"], "already")
        self.assertEqual(second["opened_now"], [])
        self.assertEqual(again["web_url"], "https://example.test/9")
        self.assertEqual(again["target_branch"], "develop")


if __name__ == "__main__":
    unittest.main()
