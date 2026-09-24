import os
from pathlib import Path
"""OSS smell bench: run the agent on real dayjs/axios issues, record levels."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.issue_graph import sonar_base_url
from cleardebt.triage import llm_repairable
from list_issues import fetch_issues, issue_path, load_token

import run_issue

PICKS = {"bench-dayjs": 15, "bench-axios": 15}


def collect(project: str, want: int) -> list[dict]:
    issues = fetch_issues(sonar_base_url(), load_token(None), project)
    by_rule: dict[str, list] = {}
    for issue in issues:
        rule = issue.get("rule") or ""
        if llm_repairable(rule):
            by_rule.setdefault(rule, []).append(issue)
    chosen = []
    rules = sorted(by_rule)
    index = 0
    while len(chosen) < want and any(by_rule.values()):
        bucket = by_rule[rules[index % len(rules)]]
        if bucket:
            chosen.append(bucket.pop(0))
        index += 1
        if index > want * len(rules) + 10:
            break
    out = []
    for issue in chosen:
        out.append(
            {
                "project": project,
                "rule": issue.get("rule") or "",
                "path": issue_path(issue.get("component", ""), project),
                "message": issue.get("message") or "",
            }
        )
    return out


def run_one(item: dict) -> dict:
    started = time.time()
    try:
        ran = run_issue.execute(
            item["rule"], item["project"], path=item["path"], message=item["message"]
        )
        return {
            **item,
            "level": ran.get("level"),
            "reason": (ran.get("reason") or "")[:200],
            "fix_method": ran.get("fix_method"),
            "seconds": round(time.time() - started),
        }
    except SystemExit as error:
        return {**item, "level": "L3", "reason": str(error.code)[:200], "seconds": round(time.time() - started)}
    except Exception as error:  # noqa: BLE001
        return {**item, "level": "L3", "reason": f"harness: {error}"[:200], "seconds": round(time.time() - started)}


def main() -> None:
    jobs = []
    for project, want in PICKS.items():
        jobs.extend(collect(project, want))
    print(f"collected {len(jobs)} issues", flush=True)
    results = list(ThreadPoolExecutor(max_workers=2).map(run_one, jobs))
    with open(os.environ.get("BENCH_OUT", "/tmp/bench/results.json"), "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=1)
    for project in PICKS:
        sub = [r for r in results if r["project"] == project]
        l1 = sum(1 for r in sub if r["level"] == "L1")
        print(f"{project}: {len(sub)} ran, L1 {l1} ({l1 / max(len(sub), 1) * 100:.0f}%)", flush=True)


if __name__ == "__main__":
    main()
