import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cleardebt.fake_fix import review_patch
from cleardebt.issue_graph import decide, run_tests
from cleardebt.languages import (
    has_node_test_stack,
    is_test_path,
    language_supported,
    sonar_sources_value,
)
from cleardebt.triage import llm_repairable, tier_for


class LanguagesTest(unittest.TestCase):
    def test_four_languages_share_rule_numbers(self):
        for prefix in ("javascript", "typescript", "python", "java"):
            self.assertEqual(tier_for(f"{prefix}:S1128"), "A")
            self.assertTrue(llm_repairable(f"{prefix}:S1128"))
        self.assertFalse(language_supported("kotlin:S1128"))
        self.assertFalse(llm_repairable("kotlin:S1128"))
        self.assertEqual(tier_for("kotlin:S1128"), "unknown")

    def test_problem_surfaces_include_secrets_and_security(self):
        from cleardebt.triage import is_secret_rule, problem_surface

        self.assertEqual(problem_surface("javascript:S1128"), "maintainability")
        self.assertEqual(problem_surface("javascript:S6679"), "reliability")
        self.assertEqual(problem_surface("javascript:S1313"), "security")
        self.assertEqual(problem_surface("javascript:S2068"), "secrets")
        self.assertTrue(is_secret_rule("secrets:S6290"))
        self.assertFalse(llm_repairable("javascript:S2068"))
        self.assertFalse(llm_repairable("secrets:S6290"))
        self.assertFalse(llm_repairable("javascript:S2077"))
        self.assertEqual(tier_for("javascript:S2077"), "C")

    def test_test_paths_cover_four_languages(self):
        self.assertTrue(is_test_path("src/pricing.test.js"))
        self.assertTrue(is_test_path("tests/test_orders.py"))
        self.assertTrue(is_test_path("pkg/orders_test.py"))
        self.assertTrue(is_test_path("src/test/java/AppTest.java"))
        self.assertTrue(is_test_path("Services/UserTests.cs"))
        self.assertFalse(is_test_path("src/orders.py"))
        self.assertFalse(is_test_path("src/main/java/App.java"))

    def test_editing_python_test_is_rejected(self):
        before = "def test_ok():\n    assert True\n"
        after = "def test_ok():\n    assert False\n"
        rejections = review_patch([("tests/test_ok.py", before, after)])
        self.assertEqual(rejections[0]["kind"], "test_file")

    def test_node_stack_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(has_node_test_stack(root))
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            self.assertTrue(has_node_test_stack(root))

    def test_sonar_sources_prefers_src_then_dot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(sonar_sources_value(root), ".")
            (root / "src").mkdir()
            self.assertEqual(sonar_sources_value(root), "src")
            (root / "sonar-project.properties").write_text("sonar.sources=app\n", encoding="utf-8")
            self.assertEqual(sonar_sources_value(root), "app")

    def test_run_tests_skips_without_node_stack(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_tests({"work_dir": directory, "path": "src/a.py", "before": "", "after": ""})
        self.assertTrue(result["tests_passed"])
        self.assertTrue(result["tests_skipped"])
        self.assertEqual(result["uncovered_lines"], [])

    def test_decide_l1_when_rescan_ok_and_tests_skipped(self):
        outcome = decide(
            {
                "tier": "A",
                "rule": "python:S1128",
                "rescan_ok": True,
                "tests_passed": True,
                "tests_skipped": True,
                "uncovered_lines": [],
            }
        )
        self.assertEqual(outcome["level"], "L1")
        self.assertIn("测试闸已跳过", outcome["reason"])

    def test_run_tests_still_calls_sandbox_for_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            with patch(
                "cleardebt.issue_graph.run_project_tests",
                return_value=type("R", (), {"returncode": 1})(),
            ) as run:
                result = run_tests({"work_dir": directory, "path": "src/a.js", "before": "", "after": ""})
        run.assert_called_once()
        self.assertFalse(result["tests_passed"])
        self.assertFalse(result["tests_skipped"])


if __name__ == "__main__":
    unittest.main()
