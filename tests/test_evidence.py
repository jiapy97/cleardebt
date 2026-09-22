import unittest
from pathlib import Path
from unittest.mock import patch

from cleardebt.evidence import TYPESCRIPT, collect_s6679

ROOT = Path(__file__).resolve().parents[1]

SNIPPET = "export function total(qty, unitPrice) {\n  if (qty == qty) {\n    return qty;\n  }\n}\n"


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


if __name__ == "__main__":
    unittest.main()
