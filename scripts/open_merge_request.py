#!/usr/bin/env python3
"""Open one GitLab merge request for the saved L1 issue. A second run does nothing."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.gitlab_mr import NotEligible, ensure_access, ensure_eligible, render_description
from cleardebt.issue_graph import build_graph
from run_issue import DB_URI, _find_issue

TOKEN_FILE = ROOT / "deploy" / "gitlab" / ".token"


def execute(rule: str | None = None, project: str | None = None) -> dict:
    from cleardebt.checkout import checkout_default
    from cleardebt.controls import gitlab_credentials, unbound_reason

    project = (project or "").strip()
    if not project:
        raise NotEligible("没有写项目，不会跑。")
    issue = _find_issue(load_sonar_token(), rule or "javascript:S1128", project)
    saved = gitlab_credentials(issue["project"])
    if not saved:
        raise NotEligible(unbound_reason(issue["project"]))
    token = saved["token"]
    ensure_access(project_access_level(token, saved["project_id"], saved["url"]))
    fingerprint = issue["fingerprint"]
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        graph = build_graph(checkpointer)
        state = graph.get_state({"configurable": {"thread_id": fingerprint}}).values
    ensure_eligible(state.get("level", ""))
    existing = find_merge_request(fingerprint)
    if existing:
        return {"action": "skip", **existing}

    default = checkout_default(ROOT / "var" / "gitlab-toy", saved)
    repo = ROOT / "var" / "gitlab-toy"
    branch = "cleardebt/" + state["rule"].split(":")[-1].lower() + "-" + fingerprint[:8]
    git(repo, ["config", "user.name", "ClearDebt"])
    git(repo, ["config", "user.email", "cleardebt@localhost"])
    git(repo, ["checkout", "-b", branch])
    target = repo / state["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(state.get("after") or "", encoding="utf-8")
    git(repo, ["add", state["path"]])
    git(repo, ["commit", "-m", f"去掉未使用的 import（{state['rule']}）"])
    push(repo, token, branch)
    opened = create_merge_request(
        token,
        source_branch=branch,
        target_branch=default,
        title=f"去掉未使用的 import（{state['rule']}）",
        description=render_description(state),
        project_id=saved["project_id"],
        gitlab_url=saved["url"],
    )
    record = {
        "action": "opened",
        "fingerprint": fingerprint,
        "merge_request_iid": opened["iid"],
        "web_url": opened["web_url"],
        "source_branch": branch,
        "target_branch": default,
    }
    save_merge_request(record)
    return record


def main() -> int:
    try:
        payload = execute()
    except NotEligible as error:
        print(str(error))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def project_access_level(token: str, project_id: int | None = None, gitlab_url: str | None = None) -> int:
    project_id = _require_project(project_id)
    payload = gitlab("GET", f"/projects/{project_id}", token, gitlab_url=gitlab_url)
    access = (payload.get("permissions") or {}).get("project_access") or {}
    return int(access.get("access_level") or 0)


def clone_repo(token: str) -> Path:
    from cleardebt.checkout import checkout_default

    repo = ROOT / "var" / "gitlab-toy"
    checkout_default(repo)
    return repo


def push(repo: Path, token: str, ref: str) -> None:
    run_git(repo, ["push", "origin", f"{ref}:{ref}"], token)


def run_git(repo: Path, args: list[str], token: str) -> None:
    askpass = Path(tempfile.mkdtemp(prefix="cleardebt-askpass-")) / "askpass"
    askpass.write_text(
        '#!/bin/sh\ncase "$1" in\n  *[Uu]sername*) echo oauth2 ;;\n  *) echo "$GITLAB_TOKEN" ;;\nesac\n',
        encoding="utf-8",
    )
    askpass.chmod(askpass.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["GITLAB_TOKEN"] = token
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", *args], cwd=repo, env=env, check=True)


def create_merge_request(
    token: str,
    *,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    project_id: int | None = None,
    gitlab_url: str | None = None,
) -> dict:
    project_id = _require_project(project_id)
    return gitlab(
        "POST",
        f"/projects/{project_id}/merge_requests",
        token,
        {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": False,
        },
        gitlab_url=gitlab_url,
    )


def _require_project(project_id: int | None) -> int:
    if project_id is None:
        raise NotEligible("还没填写 GitLab 地址，服务碰不到任何仓库。")
    return project_id


def find_merge_request(fingerprint: str) -> dict | None:
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_merge_requests (
                fingerprint TEXT PRIMARY KEY,
                merge_request_iid INTEGER NOT NULL,
                web_url TEXT NOT NULL,
                source_branch TEXT NOT NULL,
                target_branch TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            """
            SELECT fingerprint, merge_request_iid, web_url, source_branch, target_branch
            FROM issue_merge_requests WHERE fingerprint = %s
            """,
            (fingerprint,),
        ).fetchone()
    if row is None:
        return None
    return {
        "fingerprint": row[0],
        "merge_request_iid": row[1],
        "web_url": row[2],
        "source_branch": row[3],
        "target_branch": row[4],
    }


def save_merge_request(record: dict) -> None:
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            INSERT INTO issue_merge_requests
                (fingerprint, merge_request_iid, web_url, source_branch, target_branch)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                record["fingerprint"],
                record["merge_request_iid"],
                record["web_url"],
                record["source_branch"],
                record["target_branch"],
            ),
        )


def gitlab(method: str, path: str, token: str, body: dict | None = None, gitlab_url: str | None = None) -> dict:
    data = None if body is None else urllib.parse.urlencode(body).encode("utf-8")
    request = urllib.request.Request(
        _api_root(gitlab_url) + path,
        data=data,
        headers={"PRIVATE-TOKEN": token},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitLab {error.code}: {detail}") from error


def _api_root(gitlab_url: str | None) -> str:
    if not gitlab_url:
        return "https://gitlab.com/api/v4"
    parsed = urllib.parse.urlparse(gitlab_url)
    if not parsed.scheme or not parsed.netloc:
        raise NotEligible("GitLab 地址不对，服务碰不到任何仓库。")
    return f"{parsed.scheme}://{parsed.netloc}/api/v4"


def git(repo: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def load_sonar_token() -> str:
    from list_issues import load_token

    return load_token(None)


if __name__ == "__main__":
    raise SystemExit(main())
