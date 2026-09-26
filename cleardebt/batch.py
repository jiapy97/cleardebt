"""Group finished issues into small merge requests by rule and file kind."""

from __future__ import annotations

from pathlib import Path

DAILY_MR_CAP = 2


def file_kind(path: str) -> str:
    suffix = Path(path or "").suffix.lower().lstrip(".")
    return suffix or "unknown"


def group_key(row: dict) -> tuple[str, str]:
    return (row.get("rule") or "", file_kind(row.get("path") or ""))


def plan_merges(
    rows: list[dict],
    existing: dict[str, dict],
    opened_today: int,
    cap: int = DAILY_MR_CAP,
    *,
    open_agent_mrs: int = 0,
    pause_when_open_mrs: int | None = None,
) -> list[dict]:
    """rows are finished issue results. existing maps fingerprint to a saved merge request.

    Groups by Sonar rule and file kind (extension), matching Remediation Agent style.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault(group_key(row), []).append(row)
    slots = cap - opened_today
    paused = pause_when_open_mrs is not None and open_agent_mrs >= pause_when_open_mrs
    decisions = []
    for rule, kind in sorted(grouped):
        group = grouped[(rule, kind)]
        passed = [row for row in group if row.get("level") == "L1"]
        label = {
            "rule": rule,
            "file_kind": kind,
            "path": group[0].get("path"),
            "fix_method": (passed or group)[0].get("fix_method") or "",
        }
        if not passed:
            decisions.append(
                {
                    **label,
                    "action": "no_mr",
                    "level": group[0].get("level"),
                    "reason": group[0].get("reason"),
                    "count": len(group),
                }
            )
            continue
        saved = [existing[row["fingerprint"]] for row in passed if row["fingerprint"] in existing]
        pending = [row for row in passed if row["fingerprint"] not in existing]
        if len(saved) == len(passed):
            decisions.append(
                {
                    **label,
                    "action": "already",
                    "level": "L1",
                    "web_url": saved[0]["web_url"],
                    "count": len(passed),
                }
            )
            continue
        if paused:
            decisions.append(
                {
                    **label,
                    "action": "held",
                    "level": "L1",
                    "reason": f"打开的 Agent 请求已有 {open_agent_mrs} 个，达到暂停上限 {pause_when_open_mrs}，先不开新的。",
                    "count": len(passed),
                }
            )
            continue
        if slots <= 0:
            decisions.append(
                {
                    **label,
                    "action": "held",
                    "level": "L1",
                    "reason": "今天的合并请求额度已满，留下次再开。",
                    "count": len(passed),
                }
            )
            continue
        decisions.append(
            {
                **label,
                "action": "open",
                "level": "L1",
                "count": len(passed),
                "issues": pending,
            }
        )
        slots -= 1
    return decisions
