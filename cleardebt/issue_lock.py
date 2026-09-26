"""Serialize work on one issue fingerprint across local API and ARQ processes."""

from __future__ import annotations

import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def issue_lock(fingerprint: str):
    folder = ROOT / "var" / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest() + ".lock"
    with (folder / name).open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
