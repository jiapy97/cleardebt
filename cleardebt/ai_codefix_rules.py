"""Operator-provided Sonar AI CodeFix rule membership.

The official list is versioned by Sonar and is not bundled with ClearDebt.
Set CLEARDEBT_AI_CODEFIX_RULES_FILE to an authorized local export containing
one full Sonar rule key per line (for example ``javascript:S6582``).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

_RULE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*:S[0-9]+")
_lock = threading.Lock()
_cached_path = ""
_cached_signature: tuple[int, int] | None = None
_cached_keys: frozenset[str] = frozenset()


def configured() -> bool:
    return bool(os.environ.get("CLEARDEBT_AI_CODEFIX_RULES_FILE", "").strip())


def rule_keys() -> frozenset[str] | None:
    """Return the exact configured keys, or None when no list is configured.

    Invalid configured data raises; no configured list authorizes no Sonar repairs.
    """
    global _cached_path, _cached_signature, _cached_keys
    name = os.environ.get("CLEARDEBT_AI_CODEFIX_RULES_FILE", "").strip()
    if not name:
        return None
    path = Path(name)
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with _lock:
            if name == _cached_path and signature == _cached_signature:
                return _cached_keys
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"无法读取 AI CodeFix 规则清单：{path}") from error
    keys: set[str] = set()
    for lineno, line in enumerate(lines, 1):
        key = line.strip()
        if not key or key.startswith("#"):
            continue
        if not _RULE_KEY.fullmatch(key):
            raise ValueError(f"AI CodeFix 清单第 {lineno} 行不是完整 Sonar 规则键：{key}")
        if key in keys:
            raise ValueError(f"AI CodeFix 清单有重复规则键：{key}")
        keys.add(key)
    if not keys:
        raise ValueError("AI CodeFix 规则清单为空。")
    result = frozenset(keys)
    with _lock:
        _cached_path, _cached_signature, _cached_keys = name, signature, result
    return result


def listed(rule: str) -> bool | None:
    keys = rule_keys()
    if keys is None:
        return None
    return (rule or "").strip() in keys
