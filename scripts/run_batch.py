#!/usr/bin/env python3
"""Run the open Sonar issues as a batch: one small merge request per rule."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.batch import DAILY_MR_CAP, plan_merges
from cleardebt.checkout import checkout_default
from cleardebt.controls import automation_for, backlog_gate, gitlab_credentials, load_controls, save_report, unbound_reason
from cleardebt.triage import tier_for
from list_issues import fetch_issues, load_token
from open_merge_request import (
    find_merge_request,
    git,
    push,
    save_merge_request,
)
from run_issue import DB_URI, execute, sonar_base_url

TITLES = {
    "S1128": "去掉未使用的 import",
    "S1481": "去掉未使用的变量",
    "S1854": "去掉无用赋值",
    "S1656": "去掉自己赋给自己",
    "S905": "去掉没有作用的表达式",
    "S3923": "去掉两个一模一样的分支",
    "S1862": "去掉永远到不了的条件",
    "S1871": "去掉和前面一样的分支",
}


def main() -> int:
    result = run_whitelist()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("started") else 1


def run_whitelist() -> dict:
    settings = load_controls()
    if not settings.get("configured"):
        return {"started": False, "reason": "还没填写接入信息，服务碰不到任何仓库。", "repos": []}
    if not settings.get("enabled"):
        return {"started": False, "reason": "总开关关掉了，这一轮不开始。", "repos": []}
    names = [name for name in settings.get("whitelist") or [] if name]
    if not names:
        return {"started": False, "reason": "白名单是空的，这一轮碰不到任何仓库。", "repos": []}
    repos = []
    decisions = []
    for name in names:
        outcome = dict(run_controlled(name))
        outcome["repo"] = name
        repos.append(outcome)
        rows = outcome.get("decisions") or []
        if rows:
            for item in rows:
                row = dict(item)
                row.setdefault("repo", name)
                decisions.append(row)
        elif outcome.get("reason"):
            decisions.append(
                {
                    "repo": name,
                    "rule": "",
                    "path": "",
                    "level": "",
                    "action": "no_mr",
                    "reason": outcome["reason"],
                }
            )
    if decisions:
        save_report("、".join(names), bool(settings.get("dry_run")), decisions)
    return {"started": True, "repos": repos}


def run_controlled(repo: str) -> dict:
    settings = load_controls()
    refused = backlog_gate(settings, repo)
    if refused:
        return {"started": False, "reason": refused, "opened_now": [], "decisions": []}
    saved = gitlab_credentials(repo)
    if not saved:
        reason = unbound_reason(repo)
        decisions = [
            {
                "repo": repo,
                "rule": "",
                "path": "",
                "level": "",
                "action": "no_mr",
                "reason": reason,
            }
        ]
        save_report(repo, bool(settings.get("dry_run")), decisions)
        return {
            "started": False,
            "dry_run": settings.get("dry_run"),
            "reason": reason,
            "opened_now": [],
            "decisions": decisions,
        }
    try:
        before = _mr_count()
        token = load_token(None)
        issues = _issues(token, repo)
        results = [execute(issue["rule"], project=repo) for issue in issues]
        sheet = _settle(results, dry_run=settings["dry_run"], repo=repo)
    except SystemExit as error:
        reason = _exit_text(error)
        decisions = [
            {
                "repo": repo,
                "rule": "",
                "path": "",
                "level": "",
                "action": "no_mr",
                "reason": reason,
            }
        ]
        save_report(repo, bool(settings.get("dry_run")), decisions)
        return {
            "started": False,
            "dry_run": settings.get("dry_run"),
            "reason": reason,
            "opened_now": [],
            "decisions": decisions,
        }
    for item in sheet["decisions"]:
        item["repo"] = repo
    save_report(repo, settings["dry_run"], sheet["decisions"])
    return {
        "started": True,
        "dry_run": settings["dry_run"],
        "opened_now": sheet["opened_now"],
        "open_merge_requests_before": before,
        "open_merge_requests": _mr_count(),
        "decisions": sheet["decisions"],
    }


def _exit_text(error: SystemExit) -> str:
    text = error.code if isinstance(error.code, str) else ""
    return text or "这一项没有跑完。"


def _issues(token: str, project: str) -> list[dict]:
    seen = set()
    rows = []
    for issue in fetch_issues(sonar_base_url(), token, project):
        rule = issue["rule"]
        if rule in seen:
            continue
        seen.add(rule)
        path = issue["component"].split(":", 1)[-1]
        rows.append({"rule": rule, "path": path})
    return rows


def _settle(results: list[dict], dry_run: bool = False, repo: str | None = None) -> dict:
    existing = {}
    for row in results:
        saved = find_merge_request(row["fingerprint"])
        if saved:
            existing[row["fingerprint"]] = saved
    settings = load_controls()
    automation = automation_for(settings, repo) if repo else (settings.get("backlog_automation") or {})
    decisions = plan_merges(
        results,
        existing,
        _opened_today(),
        open_agent_mrs=_mr_count(),
        pause_when_open_mrs=automation.get("pause_when_open_mrs"),
    )
    opened = []
    saved = gitlab_credentials(repo)
    gitlab_token = "" if dry_run else (saved or {}).get("token") or ""
    if not dry_run and not gitlab_token:
        raise SystemExit("还没填写代码仓库令牌，服务碰不到任何仓库。")
    for decision in decisions:
        if decision["action"] != "open":
            continue
        if dry_run:
            decision["action"] = "dry_run"
            decision["reason"] = "空跑，不开合并请求。"
            decision.pop("issues", None)
            continue
        issue = dict(decision["issues"][0])
        issue.setdefault("project", repo)
        record = _open_one(gitlab_token, issue, repo)
        decision["web_url"] = record["web_url"]
        decision["merge_request_iid"] = record["merge_request_iid"]
        opened.append(record)
        decision.pop("issues", None)
    return {
        "in": len(results),
        "cap": DAILY_MR_CAP,
        "opened_today_before": _opened_today() - len(opened),
        "opened_now": opened,
        "open_merge_requests": _mr_count(),
        "decisions": decisions,
        "levels": _level_counts(results),
    }


def _open_one(token: str, issue: dict, repo: str | None = None) -> dict:
    from cleardebt.hosting import HostingError, create_request

    existing = find_merge_request(issue["fingerprint"])
    if existing:
        return existing
    saved = gitlab_credentials(issue.get("project") or repo)
    if not saved:
        raise SystemExit(unbound_reason(issue.get("project") or repo or "这个项目"))
    branch = f"cleardebt/{issue['rule'].split(':')[-1].lower()}-{issue['fingerprint'][:8]}"
    work = ROOT / "var" / "merge" / issue["fingerprint"][:12]
    default = checkout_default(work, saved)
    git(work, ["config", "user.name", "ClearDebt"])
    git(work, ["config", "user.email", "cleardebt@localhost"])
    git(work, ["checkout", "-b", branch])
    target = work / issue["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(Path(issue["work_dir"], issue["path"]).read_text(encoding="utf-8"), encoding="utf-8")
    git(work, ["add", issue["path"]])
    git(work, ["commit", "-m", f"{_title(issue['rule'])}（{issue['rule']}）"])
    push(work, saved["token"], branch, provider=saved.get("provider") or "gitlab")
    try:
        opened = create_request(
            saved,
            source_branch=branch,
            target_branch=default,
            title=f"{_title(issue['rule'])}（{issue['rule']}）",
            description=_description(issue),
        )
    except HostingError as error:
        raise SystemExit(str(error)) from error
    record = {
        "fingerprint": issue["fingerprint"],
        "merge_request_iid": opened["iid"],
        "web_url": opened["web_url"],
        "source_branch": branch,
        "target_branch": default,
        "provider": opened.get("provider") or saved.get("provider") or "gitlab",
    }
    save_merge_request(record)
    return record


def _title(rule: str) -> str:
    return TITLES.get(rule.split(":")[-1], "修复")


def _description(issue: dict) -> str:
    return "\n".join(
        [
            "ClearDebt 自动修复，待审。同一条规则的改动放在这一个请求里。",
            "",
            f"- 规则：{issue['rule']}",
            f"- 文件：{issue['path']}",
            f"- 指纹：{issue['fingerprint']}",
            f"- 级别：{issue['level']}",
            f"- 重扫和测试：{issue.get('reason')}",
            "",
            "不同规则不会混进这个请求。今天最多开两个合并请求。",
        ]
    )


def _opened_today() -> int:
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "ALTER TABLE issue_merge_requests ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"
        )
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT merge_request_iid)
            FROM issue_merge_requests
            WHERE (created_at AT TIME ZONE 'UTC')::date = (now() AT TIME ZONE 'UTC')::date
            """
        ).fetchone()
    return int(row[0])


def _mr_count() -> int:
    """Count Agent requests opened in the last 30 days (proxy for still-open backlog)."""
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "ALTER TABLE issue_merge_requests ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"
        )
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT merge_request_iid)
            FROM issue_merge_requests
            WHERE created_at >= now() - interval '30 days'
            """
        ).fetchone()
    return int(row[0])


def _level_counts(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in results:
        level = row.get("level") or "?"
        counts[level] = counts.get(level, 0) + 1
    counts["C"] = sum(1 for row in results if row.get("tier") == "C")
    try:
        from cleardebt.rules import catalog, pins

        live = catalog()
        tiers = {"A": 0, "B": 0, "C": 0, "unknown": 0}
        for key in live:
            tiers[tier_for(key)] = tiers.get(tier_for(key), 0) + 1
        counts["rules"] = {"pinned": len(pins()), "live": len(live), **tiers}
    except Exception:
        counts["rules"] = {}
    return counts


def _run_parallel(rules: list[str]) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "deploy" / "redis" / "docker-compose.yml"), "up", "-d"],
        check=True,
    )
    for _ in range(30):
        probe = subprocess.run(["docker", "exec", "cleardebt-redis", "redis-cli", "ping"], capture_output=True, text=True)
        if probe.returncode == 0 and "PONG" in probe.stdout:
            break
        time.sleep(1)
    worker = subprocess.Popen(
        [sys.executable, "-m", "arq", "cleardebt.batch_worker.WorkerSettings"],
        cwd=ROOT,
    )
    try:
        time.sleep(2)
        asyncio.run(_enqueue(rules))
    finally:
        worker.terminate()
        worker.wait(timeout=10)


async def _enqueue(rules: list[str]) -> None:
    from arq import create_pool
    from arq.connections import RedisSettings

    redis = await create_pool(RedisSettings(host="127.0.0.1", port=6379))
    jobs = [await redis.enqueue_job("run_one", rule) for rule in rules]
    for job in jobs:
        await job.result(timeout=180)


if __name__ == "__main__":
    raise SystemExit(main())
