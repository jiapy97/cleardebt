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


def summarize(issues: list[dict] | None, rule_keys: frozenset[str] | None, metadata: dict[str, dict]) -> dict:
    """List the rules the agent can repair, keyed by exact rule key.

    With a configured AI CodeFix list the list alone decides; otherwise the rules
    come from open issues Sonar marks quickFixAvailable=true. Sonar's secrets
    repository is always repairable, so its catalog rules are listed in both modes.
    """
    list_mode = rule_keys is not None
    if list_mode:
        keys = {key for key in rule_keys if language_supported(key)}
    else:
        keys = {
            key
            for issue in issues or []
            if (key := (issue.get("rule") or "").strip())
            and language_supported(key)
            and issue.get("quickFixAvailable") is True
        }
    keys |= {key for key in metadata if language_of(key) == "secrets"}
    ordered = [
        {"key": key, "language": language_of(key), "name": (metadata.get(key) or {}).get("name") or ""}
        for key in sorted(keys)
    ]
    return {
        "mode": "ai_codefix_list" if list_mode else "sonar_quick_fix",
        "rule_count": len(ordered),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rules": ordered,
    }
