#!/usr/bin/env python3
"""Build the test image and run the toy suites with the network off."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cleardebt.issue_graph import run_tests
from cleardebt.sandbox import build_image, docker_command, run_project_tests

CHECK = ROOT / "var" / "sandbox-check"


def main() -> int:
    build_image(ROOT / "fixtures" / "toy-js")
    js = _copy_fixture(ROOT / "fixtures" / "toy-js", CHECK / "toy-js")
    ts = _copy_fixture(ROOT / "fixtures" / "toy-ts", CHECK / "toy-ts")
    online = _run_online(js)
    offline_js = run_project_tests(js)
    offline_ts = run_project_tests(ts)
    covered = _covered_edit(js)
    uncovered = _uncovered_edit(js)
    print(
        json.dumps(
            {
                "image": docker_command(js)[-1],
                "network": "none",
                "online_refused": online.returncode != 0 and "还能上网" in (online.stderr or ""),
                "online_tail": "\n".join((online.stderr or online.stdout or "").splitlines()[-6:]),
                "javascript": _summary(js, offline_js),
                "typescript": _summary(ts, offline_ts),
                "covered_change_passed": covered["tests_passed"] is True and covered["uncovered_lines"] == [],
                "uncovered_change_lines": uncovered["uncovered_lines"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    ok = (
        online.returncode != 0
        and "还能上网" in (online.stderr or "")
        and offline_js.returncode == 0
        and offline_ts.returncode == 0
        and covered["tests_passed"] is True
        and covered["uncovered_lines"] == []
        and uncovered["tests_passed"] is True
        and uncovered["uncovered_lines"]
    )
    return 0 if ok else 1


def _copy_fixture(source: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("node_modules", "coverage", ".scannerwork"))
    return dest


def _run_online(work: Path) -> subprocess.CompletedProcess[str]:
    command = docker_command(work)
    command[command.index("none")] = "bridge"
    return subprocess.run(command, check=False, text=True, capture_output=True)


def _summary(work: Path, completed: subprocess.CompletedProcess[str]) -> dict:
    coverage = work / "coverage" / "coverage-final.json"
    paths = []
    if coverage.exists():
        payload = json.loads(coverage.read_text(encoding="utf-8"))
        paths = sorted(payload)[:3]
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    tail = "\n".join(text.splitlines()[-12:])
    return {
        "passed": completed.returncode == 0,
        "coverage": coverage.exists(),
        "paths_inside_workdir": all(str(item).startswith(str(work.resolve())) for item in paths),
        "tail": tail,
    }


def _covered_edit(work: Path) -> dict:
    path = work / "src" / "pricing.js"
    before = path.read_text(encoding="utf-8")
    after = before.replace("return qty * unit;", "return qty * unit + 0;", 1)
    path.write_text(after, encoding="utf-8")
    try:
        return run_tests({"work_dir": str(work), "path": "src/pricing.js", "before": before, "after": after})
    finally:
        path.write_text(before, encoding="utf-8")


def _uncovered_edit(work: Path) -> dict:
    path = work / "src" / "pricing.js"
    before = path.read_text(encoding="utf-8")
    after = before.replace("return Math.round(amount * 0.1);", "return Math.round(amount * 0.2);", 1)
    path.write_text(after, encoding="utf-8")
    try:
        return run_tests({"work_dir": str(work), "path": "src/pricing.js", "before": before, "after": after})
    finally:
        path.write_text(before, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
