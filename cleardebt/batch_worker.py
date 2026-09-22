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


async def nightly(ctx) -> dict:
    from run_batch import run_whitelist

    result = await asyncio.to_thread(run_whitelist)
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
    functions = [run_one]
    cron_jobs = [cron(nightly, hour=8, minute=0)]
    redis_settings = RedisSettings(host="127.0.0.1", port=6379)
    job_timeout = 600
    max_jobs = 4
