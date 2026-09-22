"""Group finished issues into small per-rule merge requests, with a daily cap."""

from __future__ import annotations

DAILY_MR_CAP = 2


def plan_merges(rows: list[dict], existing: dict[str, dict], opened_today: int, cap: int = DAILY_MR_CAP) -> list[dict]:
    """rows are finished issue results. existing maps fingerprint to a saved merge request."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["rule"], []).append(row)
    slots = cap - opened_today
    decisions = []
    for rule in sorted(grouped):
        group = grouped[rule]
        passed = [row for row in group if row.get("level") == "L1"]
        if not passed:
            decisions.append(
                {
                    "rule": rule,
                    "action": "no_mr",
                    "level": group[0].get("level"),
                    "reason": group[0].get("reason"),
                    "path": group[0].get("path"),
                    "count": len(group),
                }
            )
            continue
        saved = [existing[row["fingerprint"]] for row in passed if row["fingerprint"] in existing]
        if len(saved) == len(passed):
            decisions.append(
                {
                    "rule": rule,
                    "action": "already",
                    "level": "L1",
                    "web_url": saved[0]["web_url"],
                    "count": len(passed),
                }
            )
            continue
        if slots <= 0:
            decisions.append(
                {
                    "rule": rule,
                    "action": "held",
                    "level": "L1",
                    "reason": "今天的合并请求额度已满，留下次再开。",
                    "path": passed[0].get("path"),
                    "count": len(passed),
                }
            )
            continue
        decisions.append(
            {
                "rule": rule,
                "action": "open",
                "level": "L1",
                "count": len(passed),
                "issues": passed,
            }
        )
        slots -= 1
    return decisions
