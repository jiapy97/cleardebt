import unittest
from pathlib import Path
from unittest.mock import patch

from cleardebt.evidence import TYPESCRIPT, collect, collect_s6679

ROOT = Path(__file__).resolve().parents[1]

SNIPPET = "export function total(qty, unitPrice) {\n  if (qty == qty) {\n    return qty;\n  }\n}\n"

UNUSED = (
    'import { readFileSync } from "node:fs";\n'
    "\n"
    "export function formatLabel(name) {\n"
    "  return name;\n"
    "}\n"
)


class EvidenceTypeTest(unittest.TestCase):
    def test_type_comes_from_the_service_install(self):
        self.assertNotIn("fixtures", TYPESCRIPT.parts)
        self.assertTrue((TYPESCRIPT / "package.json").is_file())
        self.assertNotIn("fixtures", (ROOT / "cleardebt" / "evidence.py").read_text(encoding="utf-8"))
        found = collect_s6679(SNIPPET, "src/orders.js")
        self.assertEqual(found["expression"], "qty == qty")
        self.assertEqual(found["type"], "(parameter) qty: any")

    def test_missing_service_typescript_is_reported(self):
        with patch("cleardebt.evidence.TYPESCRIPT", Path("/tmp/cleardebt-no-typescript")):
            with self.assertRaises(RuntimeError) as caught:
                collect_s6679(SNIPPET, "src/orders.js")
        self.assertIn("还没装", str(caught.exception))


class DefaultEvidenceTest(unittest.TestCase):
    def test_collect_includes_nearby_window_and_symbol(self):
        found = collect(
            "javascript:S1128",
            UNUSED,
            "src/labels.js",
            message="Remove this unused import of 'readFileSync'.",
            start_line=1,
            end_line=1,
        )
        self.assertIn("1|import { readFileSync }", found["nearby"])
        self.assertEqual(found["name"], "readFileSync")
        self.assertTrue(any(item["line"] == 1 for item in found["occurrences"]))

    def test_collect_is_default_for_non_s6679(self):
        found = collect("python:S1128", "import os\n\nx = 1\n", "a.py", message="unused", start_line=1)
        self.assertIn("nearby", found)
        self.assertNotIn("type", found)


if __name__ == "__main__":
    unittest.main()
