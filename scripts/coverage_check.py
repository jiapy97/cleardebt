#!/usr/bin/env python3
"""Change one untested line, run Vitest, and show the coverage gate failing.

The toy file in the repository is not modified. The edit is applied to a copy.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cleardebt.coverage_gate import changed_lines, uncovered_changed_lines

PROJECT = ROOT / "fixtures" / "toy-js"
TARGET = PROJECT / "src" / "pricing.js"


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    updated = original.replace("amount * 0.1", "amount * 0.2", 1)
    if updated == original:
        raise SystemExit("pricing.js no longer contains the uncovered tax line")

    with tempfile.TemporaryDirectory(prefix="cleardebt-coverage-") as directory:
        copy = Path(directory) / "toy-js"
        shutil.copytree(
            PROJECT,
            copy,
            ignore=shutil.ignore_patterns("node_modules", "coverage"),
        )
        os.symlink(PROJECT / "node_modules", copy / "node_modules", target_is_directory=True)
        changed_file = copy / "src" / "pricing.js"
        changed_file.write_text(updated, encoding="utf-8")
        completed = subprocess.run(
            ["npm", "test"],
            cwd=copy,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            raise SystemExit("Vitest failed, so this run does not show the coverage gate")
        coverage = json.loads((copy / "coverage" / "coverage-final.json").read_text(encoding="utf-8"))
        missed = uncovered_changed_lines(
            coverage,
            changed_file,
            changed_lines(original, updated),
            updated,
        )

    sys.stdout.writelines(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/fixtures/toy-js/src/pricing.js",
            tofile="b/fixtures/toy-js/src/pricing.js",
        )
    )
    if missed != [6]:
        print(json.dumps({"ok": False, "missed": missed}, ensure_ascii=False))
        return 1
    print("测试通过。改动的是 src/pricing.js 第 6 行，这行没有任何测试跑到。")
    print("结果：不过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
