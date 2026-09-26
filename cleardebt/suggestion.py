"""One issue's agent fix suggestion, for the console detail page.

The saved suggestion row (issue_suggestions) always exists; the graph
checkpoint adds the full-file diff and gate results when it is still there.
A later run of the same issue can overwrite the checkpoint without saving a
new snippet, so the checkpoint wins whenever it holds a finished run.
"""

from __future__ import annotations

import difflib

import psycopg

from cleardebt.assign import DB_URI
from cleardebt.triage import describe, describe_message

FIX_METHODS = {"sca": "依赖升级", "mechanical": "规则改写", "llm": "AI 修复"}


def unified_diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def _diffs(row: dict, state: dict) -> tuple[list[dict], str]:
    """Full-file diffs from the checkpoint, else the saved snippet ("snippet")."""
    changed = [item for item in state.get("changed_files") or [] if item.get("before") != item.get("after")]
    if not changed and state.get("before") and state.get("after") and state["before"] != state["after"]:
        changed = [{"path": state.get("path") or row["path"], "before": state["before"], "after": state["after"]}]
    if changed:
        return [{"path": item["path"], "diff": unified_diff(item["path"], item["before"], item["after"])} for item in changed], "file"
    return [{"path": row["path"], "diff": unified_diff(row["path"], row["old_string"], row["new_string"])}], "snippet"


def _checks(state: dict) -> list[dict]:
    """Gate results in pipeline order; a gate that never ran is left out."""
    checks = []
    rejections = state.get("rejections") or []
    if "anti_cheat" in (state.get("history") or []) or rejections:
        checks.append({
            "name": "防作弊检查",
            "ok": not rejections,
            "detail": "；".join(item.get("reason") or "" for item in rejections) or "没有发现投机取巧的改法。",
        })
    if "rescan_ok" in state:
        added = state.get("rescan_added") or []
        detail = "原来的告警消失了，没有新告警。" if state["rescan_ok"] else "原来的告警还在，或者出现了新告警。"
        if added:
            detail += " 新告警：" + "、".join(f"{item.get('rule')} {item.get('path')}" for item in added)
        checks.append({"name": "Sonar 重扫", "ok": bool(state["rescan_ok"]), "detail": detail})
    if state.get("tests_skipped"):
        checks.append({"name": "测试", "ok": None, "detail": "这个项目没有可跑的测试，已跳过。"})
    elif "tests_passed" in state:
        uncovered = state.get("uncovered_lines") or []
        if state["tests_passed"] is False:
            detail = "测试没通过。"
        elif uncovered:
            detail = "测试通过，但改动的行没有测试覆盖：第 " + ", ".join(str(n) for n in uncovered) + " 行。"
        else:
            detail = "测试通过，改动的行都有测试覆盖。"
        checks.append({"name": "测试", "ok": bool(state["tests_passed"]) and not uncovered, "detail": detail})
    return checks


def build(row: dict, state: dict, mr_url: str = "") -> dict:
    rule = row["rule"]
    if not state.get("level"):
        state = {"message": state.get("message") or "", "start_line": state.get("start_line")}
    diffs, diff_scope = _diffs(row, state)
    message = state.get("message") or ""
    return {
        "fingerprint": row["fingerprint"],
        "rule": rule,
        "rule_name": describe(rule),
        "path": row["path"],
        "line": state.get("start_line") or 0,
        "message": message,
        "message_zh": describe_message(rule, message) if message else "",
        "level": state.get("level") or row["level"],
        "reason": state.get("reason") or row["reason"],
        "fix_method": FIX_METHODS.get(state.get("fix_method") or "", ""),
        "model_used": state.get("model_used") or "",
        "model_attempts": state.get("model_attempts") or [],
        "checks": _checks(state),
        "diffs": diffs,
        "diff_scope": diff_scope,
        "mr_url": mr_url,
    }


def _checkpoint_state(fingerprint: str) -> dict:
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        from cleardebt.issue_graph import build_graph

        with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
            snapshot = build_graph(checkpointer).get_state({"configurable": {"thread_id": fingerprint}})
        return dict(snapshot.values or {})
    except Exception:
        return {}


def load(fingerprint: str) -> dict | None:
    with psycopg.connect(DB_URI) as conn:
        found = conn.execute(
            "SELECT fingerprint, rule, path, level, reason, old_string, new_string"
            " FROM issue_suggestions WHERE fingerprint = %s",
            (fingerprint,),
        ).fetchone()
        if found is None:
            return None
        try:
            mr = conn.execute(
                "SELECT web_url FROM issue_merge_requests WHERE fingerprint = %s", (fingerprint,)
            ).fetchone()
        except psycopg.Error:
            mr = None
    keys = ("fingerprint", "rule", "path", "level", "reason", "old_string", "new_string")
    return build(dict(zip(keys, found)), _checkpoint_state(fingerprint), mr[0] if mr else "")
