import unittest
from pathlib import Path

from cleardebt.fake_fix import review_patch

PRICING = (Path(__file__).resolve().parents[1] / "fixtures" / "toy-js" / "src" / "pricing.js").read_text(
    encoding="utf-8"
)
PRICING_TEST = (
    Path(__file__).resolve().parents[1] / "fixtures" / "toy-js" / "src" / "pricing.test.js"
).read_text(encoding="utf-8")


class FakeFixTest(unittest.TestCase):
    def test_nosonar_is_rejected(self):
        after = PRICING.replace("return qty * unit;", "return qty * unit; // NOSONAR", 1)
        rejections = review_patch([("src/pricing.js", PRICING, after)])
        self.assertEqual([item["kind"] for item in rejections], ["suppression"])
        self.assertIn("抑制注释", rejections[0]["reason"])

    def test_eslint_disable_is_rejected(self):
        after = "/* eslint-disable */\n" + PRICING
        rejections = review_patch([("src/pricing.js", PRICING, after)])
        self.assertEqual(rejections[0]["kind"], "suppression")

    def test_editing_a_test_file_is_rejected(self):
        after = PRICING_TEST.replace("toBe(10)", "toBe(11)", 1)
        rejections = review_patch([("src/pricing.test.js", PRICING_TEST, after)])
        self.assertEqual([item["kind"] for item in rejections], ["test_file"])
        self.assertIn("测试文件", rejections[0]["reason"])

    def test_emptying_a_function_is_rejected(self):
        after = PRICING.replace("  return qty * unit;\n", "", 1)
        rejections = review_patch([("src/pricing.js", PRICING, after)])
        self.assertEqual([item["kind"] for item in rejections], ["emptied_function"])
        self.assertEqual(rejections[0]["function"], "coveredPrice")
        self.assertIn("掏空", rejections[0]["reason"])

    def test_a_normal_edit_is_not_a_fake_fix(self):
        after = PRICING.replace("0.1", "0.2", 1)
        self.assertEqual(review_patch([("src/pricing.js", PRICING, after)]), [])

    def test_emptying_a_typescript_function_is_rejected(self):
        before = "export function formatLabel(name: string): string {\n  return name;\n}\n"
        after = "export function formatLabel(name: string): string {\n}\n"
        rejections = review_patch([("src/labels.ts", before, after)])
        self.assertEqual(rejections[0]["kind"], "emptied_function")
        self.assertEqual(rejections[0]["function"], "formatLabel")

    def test_deleting_a_javascript_function_is_rejected(self):
        before = "export function live() {\n  return 1;\n}\n"
        rejections = review_patch([("src/live.js", before, "")])
        self.assertIn("erased_file", [item["kind"] for item in rejections])
        self.assertIn("emptied_function", [item["kind"] for item in rejections])

    def test_emptying_a_python_function_is_rejected(self):
        before = "def live():\n    return 1\n"
        after = "def live():\n    pass\n"
        rejections = review_patch([("src/live.py", before, after)])
        self.assertEqual([item["kind"] for item in rejections], ["emptied_function"])

    def test_emptying_a_java_method_is_rejected(self):
        before = "public class Live {\n  public int value() { return 1; }\n}\n"
        after = "public class Live {\n  public int value() { }\n}\n"
        rejections = review_patch([("src/Live.java", before, after)])
        self.assertEqual([item["kind"] for item in rejections], ["emptied_function"])

    def test_deleting_a_csharp_method_is_rejected(self):
        before = "public class Live {\n  public int Value() { return 1; }\n}\n"
        after = "public class Live {\n}\n"
        rejections = review_patch([("src/Live.cs", before, after)])
        self.assertEqual([item["kind"] for item in rejections], ["emptied_function"])


if __name__ == "__main__":
    unittest.main()
