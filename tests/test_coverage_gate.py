import unittest
from pathlib import Path

from cleardebt.coverage_gate import changed_lines, uncovered_changed_lines


def coverage_for(path: Path, hits_by_line: dict[int, int]) -> dict:
    statement_map = {}
    hits = {}
    for index, (line, count) in enumerate(hits_by_line.items()):
        statement_map[str(index)] = {
            "start": {"line": line, "column": 0},
            "end": {"line": line, "column": 1},
        }
        hits[str(index)] = count
    return {str(path): {"path": str(path), "statementMap": statement_map, "s": hits}}


class CoverageGateTest(unittest.TestCase):
    def test_changed_line_numbers_follow_the_new_file(self):
        self.assertEqual(changed_lines("return 1;\n", "return 2;\n"), {1})

    def test_uncovered_executable_line_fails(self):
        path = Path("/tmp/pricing.js")
        source = "export function uncoveredTax(amount) {\n  return amount;\n}\n"
        coverage = coverage_for(path, {1: 1, 2: 0})
        self.assertEqual(uncovered_changed_lines(coverage, path, {2}, source), [2])

    def test_covered_line_passes(self):
        path = Path("/tmp/pricing.js")
        source = "export function coveredPrice(qty, unit) {\n  return qty * unit;\n}\n"
        coverage = coverage_for(path, {1: 1, 2: 1})
        self.assertEqual(uncovered_changed_lines(coverage, path, {2}, source), [])

    def test_blank_line_is_ignored(self):
        path = Path("/tmp/pricing.js")
        source = "\n"
        coverage = coverage_for(path, {})
        self.assertEqual(uncovered_changed_lines(coverage, path, {1}, source), [])


if __name__ == "__main__":
    unittest.main()
