import subprocess
import tempfile
import unittest
from pathlib import Path

from cleardebt import issue_graph
from cleardebt.sandbox import docker_command, image_name


class SandboxCommandTest(unittest.TestCase):
    def test_tests_run_offline_in_that_repos_image(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            lockfile = work / "package-lock.json"
            lockfile.write_text('{"name":"other-js"}\n', encoding="utf-8")
            command = docker_command(work)
            tag = image_name(lockfile)
        self.assertEqual(command[command.index("--network") + 1], "cleardebt-sandbox")
        self.assertNotIn("npm", command)
        self.assertNotIn("ci", command)
        self.assertEqual(command[-1], tag)
        self.assertTrue(command[-1].startswith("cleardebt-sandbox:"))
        self.assertNotEqual(command[-1], "cleardebt-sandbox")
        self.assertTrue(any(part.endswith(":/work") for part in command))

    def test_the_graph_asks_the_sandbox_not_the_host(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
            (work / "package-lock.json").write_text("{}\n", encoding="utf-8")
            seen = []

            def fake(path):
                seen.append(path)
                coverage = work / "coverage"
                coverage.mkdir()
                (coverage / "coverage-final.json").write_text("{}", encoding="utf-8")
                return subprocess.CompletedProcess(["docker"], 0, "", "")

            original = issue_graph.run_project_tests
            issue_graph.run_project_tests = fake
            try:
                result = issue_graph.run_tests(
                    {"work_dir": str(work), "path": "src/a.js", "before": "a\n", "after": "a\n"}
                )
            finally:
                issue_graph.run_project_tests = original
        self.assertEqual(result["tests_passed"], True)
        self.assertFalse(result.get("tests_skipped"))
        self.assertEqual(result["uncovered_lines"], [])
        self.assertEqual(seen, [work])


if __name__ == "__main__":
    unittest.main()
