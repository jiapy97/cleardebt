import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleardebt.checkout import _refuse_fixtures
from run_issue import _prepare_work_dir


class CheckoutGuardTest(unittest.TestCase):
    def test_refuses_to_write_inside_the_fixtures(self):
        with self.assertRaises(SystemExit) as caught:
            _refuse_fixtures(Path(__file__).resolve().parents[1] / "fixtures" / "toy-js" / "src" / "new.js")
        self.assertIn("玩具文件", str(caught.exception))

    def test_work_dir_keeps_the_cloned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"

            def fake_clone(dest: Path, saved=None) -> str:
                (dest / "src").mkdir(parents=True)
                (dest / "src" / "orders.js").write_text("from-default-branch\n", encoding="utf-8")
                return "main"

            with (
                patch(
                    "cleardebt.controls.gitlab_credentials",
                    return_value={"remote": "https://gitlab.example/g/one.git", "project_id": 1, "token": "t", "url": "https://gitlab.example/g/one"},
                ),
                patch("cleardebt.checkout.checkout_default", side_effect=fake_clone),
            ):
                _prepare_work_dir(
                    work,
                    {"project": "toy-js", "path": "src/orders.js", "source": "from-sonar-raw\n"},
                )
            self.assertEqual((work / "src" / "orders.js").read_text(encoding="utf-8"), "from-default-branch\n")


if __name__ == "__main__":
    unittest.main()
