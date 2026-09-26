import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data" / "public_fix_lists"


def catalog(name: str) -> dict:
    return json.loads((ROOT / f"{name}-2026-09-26.json").read_text(encoding="utf-8"))


class PublicFixListsTest(unittest.TestCase):
    def test_public_snapshots_preserve_native_namespaces(self):
        expected = {
            "github_copilot_autofix": (461, "codeql_query_help_slug"),
            "gitlab_duo_vulnerability_resolution": (45, "cwe"),
            "ruff": (479, "ruff_rule_code"),
            "biome": (202, "biome_language_rule"),
            "eslint_core": (38, "eslint_rule_name"),
        }
        for source, (count, kind) in expected.items():
            with self.subTest(source=source):
                data = catalog(source)
                keys = [row["key"] for row in data["rules"]]
                self.assertEqual(data["source"], source)
                self.assertEqual(data["key_kind"], kind)
                self.assertEqual(len(keys), count)
                self.assertEqual(len(keys), len(set(keys)))

    def test_only_actual_autofix_marks_are_included(self):
        github = {row["key"] for row in catalog("github_copilot_autofix")["rules"]}
        gitlab = {row["key"] for row in catalog("gitlab_duo_vulnerability_resolution")["rules"]}
        eslint = {row["key"] for row in catalog("eslint_core")["rules"]}
        biome = {row["key"]: row for row in catalog("biome")["rules"]}
        self.assertIn("javascript/js-zipslip", github)
        self.assertIn("CWE-89", gitlab)
        self.assertIn("curly", eslint)
        self.assertNotIn("no-unused-vars", eslint)  # suggestions alone are not autofix
        self.assertEqual(biome["js/noUnusedVariables"]["fix_safety"], "unsafe")


if __name__ == "__main__":
    unittest.main()
