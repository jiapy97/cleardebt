#!/usr/bin/env python3
"""Delete unused JS imports in one file and print the diff. Does not scan or open a merge request."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cleardebt.unused_import import remove_unused_imports


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} FILE")
    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    updated = remove_unused_imports(original)
    if updated == original:
        print(f"{path}: no unused imports")
        return 0
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    sys.stdout.writelines(diff)
    path.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
