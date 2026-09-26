import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from cleardebt.issue_graph import build_graph, decide
from cleardebt.sca import (
    SCA_RULE,
    apply_bump,
    bump_gradle,
    bump_maven,
    bump_npm,
    bump_pip,
    parse_risk,
    verify_bump,
)
from cleardebt.triage import llm_repairable, problem_surface, tier_for


class ScaBumpTest(unittest.TestCase):
    def test_parse_upgrade_message(self):
        risk = parse_risk("Upgrade lodash from 4.17.20 to 4.17.21", "package.json")
        self.assertEqual(risk["package"], "lodash")
        self.assertEqual(risk["from_version"], "4.17.20")
        self.assertEqual(risk["to_version"], "4.17.21")
        self.assertEqual(risk["ecosystem"], "npm")

    def test_bump_npm_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "package.json").write_text(
                json.dumps({"dependencies": {"lodash": "^4.17.20"}}, indent=2) + "\n",
                encoding="utf-8",
            )
            (work / "package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "node_modules/lodash": {"version": "4.17.20", "name": "lodash"},
                        },
                        "dependencies": {"lodash": {"version": "4.17.20"}},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            risk = parse_risk("Upgrade lodash to version 4.17.21", "package.json")
            bumped = apply_bump(work, risk)
            pkg = json.loads((work / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(pkg["dependencies"]["lodash"], "^4.17.21")
            checked = verify_bump(work, risk)
            self.assertTrue(checked["ok"])
            self.assertEqual(
                {item["path"] for item in bumped["changed_files"]},
                {"package.json", "package-lock.json"},
            )

    def test_bump_pip_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            req = Path(directory) / "requirements.txt"
            req.write_text("requests==2.28.0\nflask==2.0.0\n", encoding="utf-8")
            text = bump_pip(req, "requests", "2.31.0")
            self.assertIn("requests==2.31.0", text)
            self.assertIn("flask==2.0.0", text)

    def test_bump_maven_pom(self):
        with tempfile.TemporaryDirectory() as directory:
            pom = Path(directory) / "pom.xml"
            pom.write_text(
                """
<project>
  <dependencies>
    <dependency>
      <groupId>org.apache.commons</groupId>
      <artifactId>commons-text</artifactId>
      <version>1.9</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            text = bump_maven(pom, "org.apache.commons:commons-text", "1.10.0")
            self.assertIn("<version>1.10.0</version>", text)

    def test_bump_gradle(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / "build.gradle"
            build.write_text(
                "dependencies {\n  implementation 'com.google.guava:guava:31.0-jre'\n}\n",
                encoding="utf-8",
            )
            text = bump_gradle(build, "com.google.guava:guava", "32.0.0-jre")
            self.assertIn("com.google.guava:guava:32.0.0-jre", text)

    def test_triage_marks_sca_repairable(self):
        self.assertEqual(tier_for(SCA_RULE), "A")
        self.assertTrue(llm_repairable(SCA_RULE))
        self.assertEqual(problem_surface(SCA_RULE), "sca")

    def test_graph_sca_path_reaches_l1(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "package.json").write_text(
                json.dumps({"dependencies": {"lodash": "4.17.20"}}, indent=2) + "\n",
                encoding="utf-8",
            )
            state = {
                "fingerprint": "sca-fp",
                "rule": SCA_RULE,
                "path": "package.json",
                "message": "Upgrade lodash from 4.17.20 to 4.17.21",
                "work_dir": str(work),
                "project": "toy",
                "sca_package": "lodash",
                "sca_to_version": "4.17.21",
                "history": [],
            }
            graph = build_graph(MemorySaver())
            with patch("cleardebt.issue_graph.run_project_tests") as tests:
                result = graph.invoke(state, {"configurable": {"thread_id": "sca-1"}})
            tests.assert_not_called()
            self.assertEqual(result["level"], "L1")
            self.assertTrue(result.get("rescan_ok"))
            self.assertEqual(result.get("fix_method"), "sca")
            pkg = json.loads((work / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(pkg["dependencies"]["lodash"], "4.17.21")

    def test_decide_sca_message(self):
        outcome = decide(
            {
                "tier": "A",
                "rule": SCA_RULE,
                "rescan_ok": True,
                "tests_passed": True,
                "tests_skipped": True,
                "uncovered_lines": [],
            }
        )
        self.assertEqual(outcome["level"], "L1")
        self.assertIn("依赖已升", outcome["reason"])


if __name__ == "__main__":
    unittest.main()
