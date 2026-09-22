import unittest
from pathlib import Path

from cleardebt.a_fix import (
    apply_mechanical,
    collapse_identical_branches,
    collapse_overwritten_declarations,
    remove_duplicate_conditions,
    remove_self_assignments,
    remove_unused_locals,
    remove_useless_expressions,
)
from cleardebt.coverage_gate import changed_lines

ROOT = Path(__file__).resolve().parents[1]
ORDERS = (ROOT / "fixtures" / "toy-js" / "src" / "orders.js").read_text(encoding="utf-8")
STATUS = (ROOT / "fixtures" / "toy-js" / "src" / "status.js").read_text(encoding="utf-8")


class MechanicalFixTest(unittest.TestCase):
    def test_removes_the_unused_local(self):
        updated = remove_unused_locals(ORDERS)
        self.assertNotIn("unusedLocal", updated)
        self.assertIn("let amount = qty * unitPrice;", updated)
        self.assertEqual(changed_lines(ORDERS, updated), set())

    def test_collapses_the_useless_assignment(self):
        updated = collapse_overwritten_declarations(ORDERS)
        self.assertEqual(updated.count("amount = qty * unitPrice"), 1)
        self.assertIn("let amount = qty * unitPrice;", updated)
        self.assertNotIn("\n  amount = qty * unitPrice;", updated)
        self.assertEqual(changed_lines(ORDERS, updated), set())

    def test_removes_self_assignment(self):
        updated = remove_self_assignments(ORDERS)
        self.assertNotIn("value = value", updated)
        self.assertIn("return value;", updated)
        self.assertEqual(changed_lines(ORDERS, updated), set())

    def test_removes_a_useless_expression_and_keeps_calls(self):
        updated = remove_useless_expressions(ORDERS)
        self.assertNotIn("1 + 2", updated)
        self.assertIn("export function useless() {\n}", updated)
        self.assertIn("value = value", updated)
        self.assertIn("qty == qty", updated)
        self.assertEqual(changed_lines(ORDERS, updated), set())

    def test_keeps_a_directive_and_a_call(self):
        source = '"use strict";\nexport function f() {\n  foo();\n  1 + 2;\n}\n'
        updated = remove_useless_expressions(source)
        self.assertIn('"use strict";', updated)
        self.assertIn("foo();", updated)
        self.assertNotIn("1 + 2", updated)

    def test_collapses_identical_if_else(self):
        updated = collapse_identical_branches(ORDERS)
        self.assertIn("export function sameBranch(flag) {\n  return 1;\n}", updated)
        self.assertNotIn("if (flag)", updated)
        self.assertIn("const unusedLocal = 1;", updated)
        self.assertIn("emptyHandler", updated)

    def test_collapses_several_statements_at_the_same_indent(self):
        source = (
            "export function f(flag) {\n"
            "  if (flag) {\n"
            "    const value = 1;\n"
            "    return value;\n"
            "  } else {\n"
            "    const value = 1;\n"
            "    return value;\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(
            collapse_identical_branches(source),
            "export function f(flag) {\n  const value = 1;\n  return value;\n}\n",
        )

    def test_leaves_a_condition_that_calls_something(self):
        source = "export function f(flag) {\n  if (flag()) {\n    return 1;\n  } else {\n    return 1;\n  }\n}\n"
        self.assertEqual(collapse_identical_branches(source), source)

    def test_removes_only_an_unreachable_else_if(self):
        updated = remove_duplicate_conditions(STATUS)
        self.assertEqual(
            updated,
            "export function label(status) {\n"
            '  if (status === "closed") {\n'
            '    return "closed";\n'
            "  }\n"
            '  return "open";\n'
            "}\n",
        )
        self.assertEqual(changed_lines(STATUS, updated), set())

    def test_keeps_a_live_else_if_and_a_following_else(self):
        live = (
            "export function label(status) {\n"
            '  if (status === "closed") {\n'
            '    return "closed";\n'
            '  } else if (status === "open") {\n'
            '    return "open";\n'
            "  }\n"
            '  return "other";\n'
            "}\n"
        )
        chained = (
            "export function label(status) {\n"
            '  if (status === "closed") {\n'
            '    return "closed";\n'
            '  } else if (status === "closed") {\n'
            '    return "closed";\n'
            "  } else {\n"
            '    return "open";\n'
            "  }\n"
            "}\n"
        )
        self.assertEqual(remove_duplicate_conditions(live), live)
        self.assertEqual(remove_duplicate_conditions(chained), chained)

    def test_same_rule_number_edits_typescript(self):
        source = (
            "export function withNoise(name: string): string {\n"
            "  1 + 2;\n"
            "  if (name) {\n"
            "    return name;\n"
            "  } else {\n"
            "    return name;\n"
            "  }\n"
            "}\n"
        )
        noisy = (
            "export function deadStatus(status: string): string {\n"
            '  if (status === "closed") {\n'
            '    return "closed";\n'
            '  } else if (status === "closed") {\n'
            '    return "closed";\n'
            "  }\n"
            '  return "open";\n'
            "}\n"
        )
        unused = "export function formatLabel(name: string): string {\n  const unusedLocal: number = 1;\n  return name;\n}\n"
        self_assign = "export function selfAssign(value: number): number {\n  value = value;\n  return value;\n}\n"
        self.assertNotIn("unusedLocal", remove_unused_locals(unused, "src/labels.ts"))
        self.assertNotIn("value = value", remove_self_assignments(self_assign, "src/labels.ts"))
        self.assertNotIn("1 + 2", remove_useless_expressions(source, "src/labels.ts"))
        self.assertIn("return name;", remove_useless_expressions(source, "src/labels.ts"))
        collapsed = collapse_identical_branches(source, "src/labels.ts")
        self.assertNotIn("else", collapsed)
        self.assertIn("return name;", collapsed)
        self.assertNotIn("else if", remove_duplicate_conditions(noisy, "src/labels.ts"))
        js = apply_mechanical("javascript:S905", "export function f() {\n  1 + 2;\n  return 1;\n}\n", "src/a.js")
        ts = apply_mechanical("typescript:S905", "export function f() {\n  1 + 2;\n  return 1;\n}\n", "src/a.ts")
        self.assertEqual(js, ts)
        self.assertNotIn("1 + 2", ts)
        self.assertIsNone(apply_mechanical("javascript:S9999", ORDERS))


if __name__ == "__main__":
    unittest.main()
