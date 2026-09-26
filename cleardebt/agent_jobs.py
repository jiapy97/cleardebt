"""Submit long-running repair sessions to the existing ARQ worker."""

from __future__ import annotations

import asyncio
import hashlib
import json

from arq import create_pool

from cleardebt.batch_worker import WorkerSettings


def job_key(kind: str, repo: str, selections: list[dict], *, mr_iid: int = 0) -> str:
    normalized = sorted(
        selections,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    raw = json.dumps(
        {"kind": kind, "repo": repo, "mr_iid": mr_iid, "issues": normalized},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def enqueue(function: str, *args, session_id: int) -> None:
    redis = await create_pool(WorkerSettings.redis_settings)
    try:
        job = await redis.enqueue_job(function, *args, _job_id=f"cleardebt-session-{session_id}")
        if job is None:
            raise RuntimeError("任务已经在队列中")
    finally:
        await redis.aclose()


def submit(function: str, *args, session_id: int) -> None:
    asyncio.run(enqueue(function, *args, session_id=session_id))
