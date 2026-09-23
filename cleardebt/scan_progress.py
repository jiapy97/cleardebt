"""Live progress text for baseline rescans.

The scan runs inside one HTTP request for minutes; without feedback the
button looks dead. Phases report here, the console polls
GET /api/scan/progress?repo=... while waiting. In-memory only: a restart
clears it, and readers treat missing/old entries as "unknown".
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_steps: dict[str, dict] = {}
STALE_AFTER = 30.0


def report(repo: str, step: str) -> None:
    name = (repo or "").strip()
    if not name:
        return
    with _lock:
        _steps[name] = {"step": step, "updated_at": time.time()}


def read(repo: str) -> dict:
    name = (repo or "").strip()
    with _lock:
        entry = _steps.get(name)
        if not entry:
            return {"step": "", "stale": True}
        return {
            "step": entry["step"],
            "stale": (time.time() - entry["updated_at"]) > STALE_AFTER,
        }


def clear(repo: str) -> None:
    name = (repo or "").strip()
    with _lock:
        _steps.pop(name, None)
