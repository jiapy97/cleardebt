"""Current Sonar repair eligibility for the console rule list."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from cleardebt.languages import language_of, language_supported


def fetch_open_issues(host: str, token: str) -> list[dict]:
    """Read open issues from the Sonar instance's default branch, page by page."""
    issues: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"resolved": "false", "ps": 500, "p": page})
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/issues/search?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        batch = payload.get("issues")
        if not isinstance(batch, list):
            raise ValueError("Sonar 没有返回告警列表。")
        issues.extend(batch)
        total = int(payload.get("total", len(issues)))
        if len(issues) >= total:
            return issues
        if not batch or page >= 20:
            raise ValueError(f"Sonar 告警未读取完整：已读 {len(issues)} 条，共 {total} 条。")
        page += 1


def summarize(issues: list[dict], rule_keys: frozenset[str] | None, metadata: dict[str, dict]) -> dict:
    """Aggregate exact rule keys without turning issue Quick Fix into a rule whitelist."""
    list_mode = rule_keys is not None
    rows: dict[str, dict] = {}

    def row_for(key: str) -> dict:
        if key not in rows:
            rows[key] = {
                "key": key,
                "language": language_of(key),
                "name": (metadata.get(key) or {}).get("name") or "",
                "issue_count": 0,
                "projects": set(),
            }
        return rows[key]

    if list_mode:
        for key in rule_keys:
            if language_supported(key):
                row_for(key)

    eligible_issues = 0
    for issue in issues:
        key = (issue.get("rule") or "").strip()
        if not language_supported(key):
            continue
        eligible = key in rule_keys if list_mode else issue.get("quickFixAvailable") is True
        if not eligible:
            continue
        row = row_for(key)
        row["issue_count"] += 1
        project = (issue.get("project") or "").strip()
        if project:
            row["projects"].add(project)
        eligible_issues += 1

    ordered = []
    for key in sorted(rows):
        row = rows[key]
        ordered.append({**row, "projects": sorted(row["projects"])})
    return {
        "mode": "ai_codefix_list" if list_mode else "sonar_quick_fix",
        "rule_count": len(ordered),
        "open_issue_count": len(issues),
        "eligible_issue_count": eligible_issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rules": ordered,
    }
