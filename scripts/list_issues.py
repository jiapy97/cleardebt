#!/usr/bin/env python3
"""Print open Sonar issues for a named project, with our own fingerprints.

Identity is sha256(rule + normalized path + sha256(issue line text)).
Sonar's issue key is shown only so it is obvious we do not use it as identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_FILE = ROOT / "deploy" / "sonarqube" / ".token"


def fingerprint(rule_key: str, path: str, line_text: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    line_hash = hashlib.sha256(line_text.encode("utf-8")).hexdigest()
    raw = f"{rule_key}\n{normalized}\n{line_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_path(component: str, project_key: str) -> str:
    prefix = f"{project_key}:"
    if component.startswith(prefix):
        return component[len(prefix) :]
    return component


def line_span(source: str, start_line: int, end_line: int) -> str:
    lines = source.splitlines()
    if start_line < 1 or start_line > len(lines):
        raise ValueError(f"line {start_line} is outside the file ({len(lines)} lines)")
    end_line = max(start_line, min(end_line, len(lines)))
    return "\n".join(lines[start_line - 1 : end_line])


def fetch_issues(
    host: str,
    token: str,
    project_key: str,
    *,
    pull_request: str | None = None,
    branch: str | None = None,
) -> list[dict]:
    issues: list[dict] = []
    page = 1
    while True:
        params = {
            "componentKeys": project_key,
            "resolved": "false",
            "ps": "500",
            "p": str(page),
        }
        if pull_request:
            params["pullRequest"] = str(pull_request)
        elif branch:
            params["branch"] = branch
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/issues/search?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        batch = payload.get("issues", [])
        issues.extend(batch)
        total = payload.get("total", len(issues))
        if not batch or len(issues) >= total or page >= 20:
            return issues
        page += 1


def load_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("SONAR_TOKEN")
    if env:
        return env
    from cleardebt.controls import sonar_credentials

    saved = sonar_credentials()
    if saved and saved.get("token"):
        return saved["token"]
    if DEFAULT_TOKEN_FILE.is_file():
        return DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "missing token: pass --token, set SONAR_TOKEN, or write deploy/sonarqube/.token"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("SONAR_HOST_URL", "http://localhost:9000"))
    parser.add_argument("--token", default=None)
    parser.add_argument("--project", required=True, help="Sonar 项目 key；不传不会跑。")
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="本地源码目录。省略时只打出规则和路径，不从本地算指纹。",
    )
    args = parser.parse_args()

    token = load_token(args.token)
    try:
        issues = fetch_issues(args.host, token, args.project)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Sonar API {error.code}: {detail}") from error

    rows = []
    for issue in issues:
        path = issue_path(issue.get("component", ""), args.project)
        text_range = issue.get("textRange") or {}
        start = int(text_range.get("startLine") or 1)
        end = int(text_range.get("endLine") or start)
        rule_key = issue["rule"]
        row = {
            "rule": rule_key,
            "path": path,
            "line": start,
            "message": issue.get("message", ""),
            "sonar_key_not_identity": issue.get("key", ""),
        }
        if args.sources is not None:
            source_file = args.sources / path
            if not source_file.is_file():
                raise SystemExit(f"issue points at missing file: {source_file}")
            text = line_span(source_file.read_text(encoding="utf-8"), start, end)
            row["fingerprint"] = fingerprint(rule_key, path, text)
        rows.append(row)

    rows.sort(key=lambda row: (row["path"], row["line"], row["rule"]))
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if not rows:
        raise SystemExit("no open issues; the target is empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
