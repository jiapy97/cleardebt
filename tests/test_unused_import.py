import unittest

from cleardebt.unused_import import remove_unused_imports

ORDERS = """import { readFile } from "node:fs";

export function total(qty, unitPrice) {
  const unusedLocal = 1;
  let amount = qty * unitPrice;
  amount = qty * unitPrice;
  if (qty == qty) {
    return amount;
  }
  return amount;
}

export function sameBranch(flag) {
  if (flag) {
    return 1;
  } else {
    return 1;
  }
}

export function emptyHandler() {}

export function withTodo() {
  // TODO: tighten this later
  return 1;
}

export function useless() {
  1 + 2;
}

export function selfAssign(value) {
  value = value;
  return value;
}
"""


class RemoveUnusedImportTest(unittest.TestCase):
    def test_orders_fixture_drops_only_the_unused_import(self):
        updated = remove_unused_imports(ORDERS)
        self.assertFalse(updated.startswith("import"))
        self.assertIn("const unusedLocal = 1;", updated)
        self.assertIn("amount = qty * unitPrice;", updated)
        self.assertIn("// TODO: tighten this later", updated)
        self.assertNotIn("readFile", updated)
        self.assertTrue(updated.startswith("export function total"))

    def test_keeps_a_used_named_import(self):
        source = 'import { readFile, readFileSync } from "node:fs";\nreadFileSync("a");\n'
        self.assertEqual(
            remove_unused_imports(source),
            'import { readFileSync } from "node:fs";\nreadFileSync("a");\n',
        )

    def test_property_access_does_not_count_as_a_use(self):
        source = 'import { readFile } from "node:fs";\nobj.readFile();\n'
        self.assertEqual(remove_unused_imports(source), "obj.readFile();\n")

    def test_shorthand_property_counts_as_a_use(self):
        source = 'import { readFile } from "node:fs";\nconst file = { readFile };\n'
        self.assertEqual(remove_unused_imports(source), source)

    def test_alias_uses_the_local_name(self):
        source = 'import { readFile as rf } from "node:fs";\nrf("a");\n'
        self.assertEqual(remove_unused_imports(source), source)

    def test_keeps_side_effect_import(self):
        source = 'import "node:fs";\n'
        self.assertEqual(remove_unused_imports(source), source)

    def test_drops_unused_default_and_keeps_named(self):
        source = 'import fs, { readFile } from "node:fs";\nreadFile("a");\n'
        self.assertEqual(
            remove_unused_imports(source),
            'import { readFile } from "node:fs";\nreadFile("a");\n',
        )

    def test_refuses_a_parse_error(self):
        with self.assertRaises(ValueError):
            remove_unused_imports("import { ;\n")

    def test_drops_an_unused_typescript_import(self):
        source = (
            'import { readFileSync } from "node:fs";\n\n'
            "export function formatLabel(name: string): string {\n"
            "  return name;\n"
            "}\n"
        )
        updated = remove_unused_imports(source, "src/labels.ts")
        self.assertNotIn("readFileSync", updated)
        self.assertIn("formatLabel", updated)
        self.assertIn("name: string", updated)


if __name__ == "__main__":
    unittest.main()
