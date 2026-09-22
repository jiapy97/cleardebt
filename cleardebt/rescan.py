"""Decide whether a rescan shows the fixed issue gone and nothing new."""

from __future__ import annotations


def verdict(before: list[dict], after: list[dict], fixed_rule: str) -> dict:
    before_by_fp = {row["fingerprint"]: row for row in before}
    after_by_fp = {row["fingerprint"]: row for row in after}
    removed = [before_by_fp[key] for key in before_by_fp.keys() - after_by_fp.keys()]
    added = [after_by_fp[key] for key in after_by_fp.keys() - before_by_fp.keys()]
    removed.sort(key=_sort_key)
    added.sort(key=_sort_key)
    target_gone = any(row["rule"] == fixed_rule for row in removed)
    ok = target_gone and not added
    return {"ok": ok, "removed": removed, "added": added}


def _sort_key(row: dict) -> tuple:
    return (row.get("path", ""), row.get("line", 0), row.get("rule", ""))
