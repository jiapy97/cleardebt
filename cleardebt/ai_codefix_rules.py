"""Sonar AI CodeFix rule membership: the agent's repairable rule list.

By default the bundled snapshot in data/public_fix_lists is used. Set
CLEARDEBT_AI_CODEFIX_RULES_FILE to another list: a snapshot JSON with
``rules: [{"key": ...}]`` or text with one full Sonar rule key per line
(for example ``javascript:S6582``). Setting it to an empty string disables the
list, and eligibility falls back to Sonar's per-issue quickFixAvailable flag.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

DEFAULT_RULES_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "public_fix_lists" / "sonar_ai_codefix-2026-09-26.json"
)
_RULE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*:S[0-9]+")
_lock = threading.Lock()
_cached_path = ""
_cached_signature: tuple[int, int] | None = None
_cached_keys: frozenset[str] = frozenset()


def _configured_path() -> str:
    name = os.environ.get("CLEARDEBT_AI_CODEFIX_RULES_FILE")
    return str(DEFAULT_RULES_FILE) if name is None else name.strip()


def configured() -> bool:
    return bool(_configured_path())


def _entries(path: Path, text: str) -> list[tuple[str, str]]:
    """(location, key) pairs from a snapshot JSON or a one-key-per-line export."""
    if path.suffix.lower() == ".json":
        rows = json.loads(text).get("rules")
        if not isinstance(rows, list):
            raise ValueError("AI CodeFix 清单 JSON 缺少 rules 列表。")
        return [(f"第 {index} 条", str((row or {}).get("key") or "").strip()) for index, row in enumerate(rows, 1)]
    return [
        (f"第 {lineno} 行", line.strip())
        for lineno, line in enumerate(text.splitlines(), 1)
        if line.strip() and not line.strip().startswith("#")
    ]


def rule_keys() -> frozenset[str] | None:
    """Return the exact configured keys, or None when no list is configured.

    Invalid configured data raises; no configured list authorizes no Sonar repairs.
    """
    global _cached_path, _cached_signature, _cached_keys
    name = _configured_path()
    if not name:
        return None
    path = Path(name)
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with _lock:
            if name == _cached_path and signature == _cached_signature:
                return _cached_keys
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"无法读取 AI CodeFix 规则清单：{path}") from error
    try:
        entries = _entries(path, text)
    except json.JSONDecodeError as error:
        raise ValueError(f"AI CodeFix 清单不是有效 JSON：{path}") from error
    keys: set[str] = set()
    for where, key in entries:
        if not _RULE_KEY.fullmatch(key):
            raise ValueError(f"AI CodeFix 清单{where}不是完整 Sonar 规则键：{key}")
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
