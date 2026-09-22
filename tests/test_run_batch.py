import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_batch import _open_one, _settle


class RecordDefaultBranchTest(unittest.TestCase):
    def test_records_the_cloned_default_branch_and_skips_the_same_fingerprint(self):
        fingerprint = "abc12345deadbeef"
        store: dict[str, dict] = {}

        def save(record: dict) -> None:
            store[record["fingerprint"]] = dict(record)

        def find(fp: str) -> dict | None:
            return store.get(fp)

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
                patch("run_batch.gitlab_credentials", return_value={"token": "t", "project_id": 5}),
                patch("run_batch.checkout_default", return_value="develop") as clone,
                patch("run_batch.git"),
                patch("run_batch.push"),
                patch(
                    "run_batch.create_merge_request",
                    return_value={"iid": 9, "web_url": "https://example.test/9"},
                ) as create,
                patch("run_batch.save_merge_request", side_effect=save),
                patch("run_batch.find_merge_request", side_effect=find),
                patch("run_batch._opened_today", return_value=0),
                patch("run_batch._mr_count", return_value=1),
            ):
                first = _settle([issue], dry_run=False)
                second = _settle([issue], dry_run=False)
                again = _open_one("t", issue)

        batch_source = (ROOT / "scripts" / "run_batch.py").read_text(encoding="utf-8")
        opener_source = (ROOT / "scripts" / "open_merge_request.py").read_text(encoding="utf-8")
        self.assertNotIn("TARGET_BRANCH", batch_source)
        self.assertNotIn("TARGET_BRANCH", opener_source)
        self.assertEqual(store[fingerprint]["target_branch"], "develop")
        self.assertEqual(create.call_args.kwargs["target_branch"], "develop")
        self.assertEqual(create.call_count, 1)
        self.assertEqual(clone.call_count, 1)
        self.assertEqual(first["opened_now"][0]["target_branch"], "develop")
        self.assertEqual(second["decisions"][0]["action"], "already")
        self.assertEqual(second["opened_now"], [])
        self.assertEqual(again["web_url"], "https://example.test/9")
        self.assertEqual(again["target_branch"], "develop")


if __name__ == "__main__":
    unittest.main()
