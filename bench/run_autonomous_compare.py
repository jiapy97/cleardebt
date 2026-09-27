#!/usr/bin/env python3
"""Paired, fresh, no-MR comparison of fixed AI repair and autonomous AI repair.

Run one frozen issue in each mode, sequentially. The benchmark namespace gives
each arm a new checkpoint and work directory without deleting production data.
This script calls run_issue.execute only; it never opens a merge request.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.a_fix import has_mechanical_fix
from cleardebt.b_fix import llm_credentials
from cleardebt.controls import gitlab_credentials, load_controls
from list_issues import fetch_issues, issue_path, load_token
from cleardebt.issue_graph import sonar_base_url
from run_issue import execute

CASES = ROOT / "bench" / (os.environ.get("BENCH_CASE_FILE") or "oss_smell_cases_v2.json")


def selected_cases(manifest: dict, per_project: int, start_at: int = 1) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for issue in manifest["issues"]:
        if not has_mechanical_fix(issue["rule"], issue["path"]):
            grouped[issue["project"]].append(issue)
    return [
        item
        for project in manifest["repos"]
        for item in grouped[project][start_at - 1:per_project]
    ]


def _head(work_dir: str | None) -> str:
    if not work_dir or not Path(work_dir).is_dir():
        return ""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work_dir, text=True,
        capture_output=True, check=False, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def run_arm(item: dict, mode: str, run_id: str) -> dict:
    os.environ["CLEARDEBT_AUTONOMOUS_AGENT"] = "1" if mode == "agent" else "0"
    os.environ["CLEARDEBT_BENCH_RUN_ID"] = f"{run_id}:{mode}"
    # The frozen axios suite needs external services. Both arms get the same
    # documented rescan-only gate; dayjs keeps the full test/coverage gate.
    os.environ["CLEARDEBT_SKIP_TEST_GATE"] = "1" if item["project"] == "bench-axios" else "0"
    started = time.monotonic()
    for attempt in range(1, 4):
        try:
            result = execute(
                item["rule"], item["project"], path=item["path"], message=item["message"],
                benchmark_read_only=True, benchmark_sha=item["benchmark_sha"],
            )
            break
        except SystemExit as error:
            if "拉不下来分支" in str(error) and attempt < 3:
                time.sleep(attempt)
                continue
            return {
                "status": "harness_error", "level": None,
                "reason": f"{type(error).__name__}: {error}"[:500],
                "attempts": attempt, "seconds": round(time.monotonic() - started, 1),
            }
        except Exception as error:  # noqa: BLE001
            return {
                "status": "harness_error", "level": None,
                "reason": f"{type(error).__name__}: {error}"[:500],
                "attempts": attempt, "seconds": round(time.monotonic() - started, 1),
            }
    try:
        return {
            "status": "completed", "level": result.get("level"),
            "reason": (result.get("reason") or "")[:500],
            "fix_method": result.get("fix_method"),
            "action": result.get("action"),
            "base_commit": _head(result.get("work_dir")),
            "tests_skipped": result.get("tests_skipped"),
            "rescan_ok": result.get("rescan_ok"),
            "tool_calls": result.get("agent_tool_count"),
            "patches": result.get("agent_patch_count"),
            "full_checks": result.get("agent_full_count"),
            "reported_tokens": result.get("agent_usage_tokens"),
            "attempts": attempt,
            "seconds": round(time.monotonic() - started, 1),
        }
    except Exception as error:  # noqa: BLE001
        return {
            "status": "harness_error", "level": None,
            "reason": f"{type(error).__name__}: {error}"[:500],
            "seconds": round(time.monotonic() - started, 1),
        }


def valid_pair(pair: dict, pinned_sha: str) -> bool:
    fixed, agent = pair["fixed"], pair["agent"]
    gate = pair["gate"]
    if gate not in {"full", "rescan-only"}:
        return False
    for arm in (fixed, agent):
        if arm.get("level") == "L1" and (
            arm.get("rescan_ok") is not True
            or arm.get("tests_skipped") is not (gate == "rescan-only")
        ):
            return False
    return bool(
        fixed["status"] == agent["status"] == "completed"
        and fixed["action"] == agent["action"] == "start"
        and fixed["fix_method"] == "llm"
        and agent["fix_method"] == "agent"
        and fixed["base_commit"] == agent["base_commit"]
        and fixed["base_commit"].startswith(pinned_sha)
    )


def summary(pairs: list[dict]) -> dict:
    valid = [pair for pair in pairs if pair.get("valid")]
    return {
        "attempted_pairs": len(pairs), "valid_pairs": len(valid),
        "fixed_l1": sum(pair["fixed"]["level"] == "L1" for pair in valid),
        "agent_l1": sum(pair["agent"]["level"] == "L1" for pair in valid),
        "fixed_seconds": round(sum(pair["fixed"]["seconds"] for pair in valid), 1),
        "agent_seconds": round(sum(pair["agent"]["seconds"] for pair in valid), 1),
        "agent_tool_calls": sum(pair["agent"].get("tool_calls") or 0 for pair in valid),
        "agent_reported_tokens": sum(pair["agent"].get("reported_tokens") or 0 for pair in valid),
    }


def write_result(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-project", type=int, default=2)
    parser.add_argument("--start-at", type=int, default=1,
                        help="1-based first case within each project; per-project is the last case")
    parser.add_argument("--case-index", type=int, help="run one 1-based case from the selected list")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.per_project < 1 or not 1 <= args.start_at <= args.per_project:
        parser.error("case range must satisfy 1 <= start-at <= per-project")
    manifest = json.loads(CASES.read_text(encoding="utf-8"))
    cases = selected_cases(manifest, args.per_project, args.start_at)
    if args.case_index is not None:
        if not 1 <= args.case_index <= len(cases):
            parser.error("--case-index is outside the selected case list")
        cases = [cases[args.case_index - 1]]
    controls = load_controls()
    if not controls.get("configured") or not controls.get("enabled"):
        parser.error("project controls are not configured or enabled")
    allowed = set(controls.get("whitelist") or [])
    if any(item["project"] not in allowed for item in cases):
        parser.error("one or more benchmark projects are not whitelisted")
    for project, repo in manifest["repos"].items():
        binding = gitlab_credentials(project) or {}
        if binding.get("url") != repo["url"] or not binding.get("read_only"):
            parser.error(f"{project} must be bound read-only to the frozen public repository")
    credentials = llm_credentials()
    if urlsplit(credentials["base_url"]).hostname != "api.deepseek.com":
        parser.error("this benchmark is approved only for the configured api.deepseek.com endpoint")
    token = load_token(None)
    available = {}
    for project in manifest["repos"]:
        available[project] = {
            (row.get("rule") or "", issue_path(row.get("component") or "", project))
            for row in fetch_issues(sonar_base_url(), token, project)
        }
    run_id = uuid.uuid4().hex[:12]
    out = args.out or ROOT / "var" / "bench" / f"autonomous-compare-{run_id}.json"
    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_file": str(CASES.relative_to(ROOT)),
        "model": credentials["model"],
        "agent_protocol": "v5",
        "method": "sequential paired fresh checkpoints; execute() only; no merge requests",
        "pairs": [],
    }
    write_result(out, payload)
    print(f"run_id={run_id} cases={len(cases)} out={out}", flush=True)
    for index, item in enumerate(cases, 1):
        item = {**item, "benchmark_sha": manifest["repos"][item["project"]]["sha"]}
        pair = {"project": item["project"], "rule": item["rule"],
                "path": item["path"], "gate": manifest["repos"][item["project"]]["gate"]}
        if (item["rule"], item["path"]) not in available[item["project"]]:
            pair["valid"] = False
            pair["reason"] = "frozen issue is not open in baseline Sonar project"
        else:
            print(f"[{index}/{len(cases)}] {item['project']} {item['rule']} {item['path']}", flush=True)
            pair["fixed"] = run_arm(item, "fixed", run_id)
            print(f"  fixed: {pair['fixed']['level']} ({pair['fixed']['seconds']}s)", flush=True)
            pair["agent"] = run_arm(item, "agent", run_id)
            print(f"  agent: {pair['agent']['level']} ({pair['agent']['seconds']}s)", flush=True)
            pair["valid"] = valid_pair(pair, manifest["repos"][item["project"]]["sha"])
            if not pair["valid"]:
                pair["reason"] = "mode, gate, checkpoint, or pinned repository SHA did not match"
        payload["pairs"].append(pair)
        payload["summary"] = summary(payload["pairs"])
        write_result(out, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    return 0 if payload["summary"]["valid_pairs"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
