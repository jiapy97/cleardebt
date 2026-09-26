"""ARQ worker. Each job runs one issue through the existing graph."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from arq import cron
from arq.connections import RedisSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_issue import execute


async def run_one(ctx, rule: str, project: str | None = None) -> dict:
    name = (project or "").strip()
    if not name:
        return {"started": False, "reason": "没有写项目，不会跑。"}
    return await asyncio.to_thread(execute, rule, name)


async def run_assign_session(ctx, repo: str, selections: list[dict], session_id: int) -> dict:
    from cleardebt.assign import assign_to_agent, finish_session, mark_running, session_cancelled

    if session_cancelled(session_id):
        return {"started": False, "reason": "会话已取消"}
    mark_running(session_id)
    try:
        return await asyncio.to_thread(assign_to_agent, repo, selections, session_id=session_id)
    except Exception as error:
        finish_session(session_id, status="failed", details={"error": str(error)})
        raise


async def run_request_fix_session(ctx, repo: str, mr_iid: int, selections: list[dict], session_id: int) -> dict:
    from cleardebt.assign import finish_session, mark_running, session_cancelled
    from cleardebt.request_fix import remediate_merge_request

    if session_cancelled(session_id):
        return {"started": False, "reason": "会话已取消"}
    mark_running(session_id)
    try:
        return await asyncio.to_thread(remediate_merge_request, repo, mr_iid, selections, session_id=session_id)
    except Exception as error:
        finish_session(session_id, status="failed", details={"error": str(error)})
        raise


async def nightly(ctx) -> dict:
    """Tick every hour; each whitelist repo runs only when its schedule is due."""
    from cleardebt.controls import automation_for, load_controls, save_report
    from cleardebt.schedule import schedule_skip_reason
    from run_batch import run_controlled

    settings = load_controls()
    if not settings.get("configured"):
        result = {"started": False, "reason": "还没填写接入信息，服务碰不到任何仓库。", "repos": []}
        _note(result)
        return result
    if not settings.get("enabled"):
        result = {"started": False, "reason": "总开关关掉了，这一轮不开始。", "repos": []}
        _note(result)
        return result
    names = [name for name in settings.get("whitelist") or [] if name]
    if not names:
        result = {"started": False, "reason": "白名单是空的，这一轮碰不到任何仓库。", "repos": []}
        _note(result)
        return result
    repos = []
    decisions = []
    for name in names:
        auto = automation_for(settings, name)
        skipped = schedule_skip_reason(auto)
        if skipped:
            outcome = {
                "started": False,
                "reason": skipped,
                "opened_now": [],
                "decisions": [
                    {
                        "repo": name,
                        "rule": "",
                        "path": "",
                        "level": "",
                        "action": "no_mr",
                        "reason": skipped,
                    }
                ],
            }
        else:
            from cleardebt.assign import create_session, finish_session

            session_id = create_session(source="scheduled", repo=name, issue_count=0, status="running")
            try:
                outcome = dict(await asyncio.to_thread(run_controlled, name, session_id=session_id))
                finish_session(
                    session_id,
                    status="completed" if outcome.get("started") else "failed",
                    details={
                        "decisions": outcome.get("decisions") or [],
                        "reason": outcome.get("reason") or "",
                        "opened_now": outcome.get("opened_now") or [],
                    },
                    issue_count=len(outcome.get("decisions") or []),
                )
            except Exception as error:
                finish_session(session_id, status="failed", details={"error": str(error)})
                raise
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
    result = {"started": True, "repos": repos}
    _note(result)
    return result


def _note(result: dict) -> None:
    path = ROOT / "var" / "nightly.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    repos = result.get("repos")
    if not repos:
        rows = [
            {
                "repo": None,
                "started": bool(result.get("started")),
                "dry_run": result.get("dry_run"),
                "opened_now": len(result.get("opened_now") or []),
                "reason": result.get("reason"),
            }
        ]
    else:
        rows = [
            {
                "repo": item.get("repo"),
                "started": bool(item.get("started")),
                "dry_run": item.get("dry_run"),
                "opened_now": len(item.get("opened_now") or []),
                "reason": item.get("reason"),
            }
            for item in repos
        ]
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class WorkerSettings:
    functions = [run_one, run_assign_session, run_request_fix_session]
    # Tick every minute; schedule_due() decides whether each repo's configured
    # local hour/minute is due.
    cron_jobs = [cron(nightly)]
    redis_settings = RedisSettings(host="127.0.0.1", port=6379)
    job_timeout = 7200
    max_jobs = 4
