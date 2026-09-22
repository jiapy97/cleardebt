import unittest

from cleardebt.b_fix import ModelOutputError, apply_once, build_prompt, parse_replacement

EVIDENCE = {
    "expression": "qty == qty",
    "name": "qty",
    "type": "(parameter) qty: any",
    "occurrences": [{"line": 7, "text": "if (qty == qty) {"}],
    "function_source": "export function total(qty) {\n  if (qty == qty) {\n    return qty;\n  }\n}\n",
}


class ReplacementParseTest(unittest.TestCase):
    def test_accepts_only_the_two_snippet_fields(self):
        self.assertEqual(
            parse_replacement('{"old_string": "qty == qty", "new_string": "Number.isNaN(qty)"}'),
            ("qty == qty", "Number.isNaN(qty)"),
        )

    def test_ignores_the_json_format_marker(self):
        self.assertEqual(
            parse_replacement('{"type": "json_object", "old_string": "a", "new_string": "b"}'),
            ("a", "b"),
        )

    def test_rejects_a_claim_that_it_is_fixed(self):
        with self.assertRaises(ModelOutputError):
            parse_replacement('{"old_string": "a", "new_string": "b", "fixed": true}')

    def test_rejects_prose(self):
        with self.assertRaises(ModelOutputError):
            parse_replacement("修好了")

    def test_replaces_the_snippet_once(self):
        source = "if (qty == qty) {\n  return amount;\n}\n"
        self.assertEqual(
            apply_once(source, "qty == qty", "Number.isNaN(qty)"),
            "if (Number.isNaN(qty)) {\n  return amount;\n}\n",
        )

    def test_old_examples_enter_the_prompt_only_when_retrieval_is_on(self):
        example = {"old_string": "if (qty == qty) {", "new_string": "if (Number.isNaN(qty)) {"}
        with_examples = build_prompt(EVIDENCE, [example])
        without = build_prompt(EVIDENCE, [])
        self.assertIn("规则：", with_examples)
        self.assertIn("规则：", without)
        self.assertIn("以前同一条规则改过的片段", with_examples)
        self.assertIn("if (Number.isNaN(qty)) {", with_examples)
        self.assertNotIn("以前同一条规则改过的片段", without)
        self.assertNotIn("if (Number.isNaN(qty)) {", without)

    def test_refuses_an_ambiguous_snippet(self):
        with self.assertRaises(ModelOutputError):
            apply_once("qty == qty\nqty == qty\n", "qty == qty", "Number.isNaN(qty)")


if __name__ == "__main__":
    unittest.main()
