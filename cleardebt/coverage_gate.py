"""Fail a change when a changed executable line was not run by Vitest."""

from __future__ import annotations

import difflib
from pathlib import Path


def changed_lines(before: str, after: str) -> set[int]:
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    lines: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert"}:
            lines.update(range(j1 + 1, j2 + 1))
    return lines


def uncovered_changed_lines(
    coverage: dict,
    file_path: Path,
    changed: set[int],
    source: str,
) -> list[int]:
    file_coverage = _file_coverage(coverage, file_path)
    statements = _statements(file_coverage)
    source_lines = source.splitlines()
    missed = []
    for line in sorted(changed):
        if line < 1 or line > len(source_lines):
            missed.append(line)
            continue
        if _ignorable(source_lines[line - 1]):
            continue
        hits = [hit for start, end, hit in statements if start <= line <= end]
        if not hits or not any(hit > 0 for hit in hits):
            missed.append(line)
    return missed


def _file_coverage(coverage: dict, file_path: Path) -> dict | None:
    resolved = str(file_path.resolve())
    for key, value in coverage.items():
        if not isinstance(value, dict):
            continue
        candidate = str(value.get("path") or key)
        if str(Path(candidate).resolve()) == resolved:
            return value
    return None


def _statements(file_coverage: dict | None) -> list[tuple[int, int, int]]:
    if not file_coverage:
        return []
    locations = file_coverage.get("statementMap") or {}
    hits = file_coverage.get("s") or {}
    found = []
    for statement_id, location in locations.items():
        found.append(
            (
                int(location["start"]["line"]),
                int(location["end"]["line"]),
                int(hits.get(statement_id, 0)),
            )
        )
    return found


def _ignorable(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("//")
