#!/usr/bin/env python3
"""Open one fix request (GitLab / GitHub / Azure DevOps) for a saved L1 issue. A second run does nothing."""

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
from cleardebt.issue_lock import issue_lock
from cleardebt.issue_graph import build_graph
from run_issue import DB_URI, _find_issue, execution_fingerprint


def execute(
    rule: str | None = None,
    project: str | None = None,
    *,
    path: str | None = None,
    target_branch: str | None = None,
    fingerprint: str | None = None,
) -> dict:
    if fingerprint:
        with issue_lock(fingerprint):
            return _execute_unlocked(rule, project, path=path, target_branch=target_branch, fingerprint=fingerprint)
    return _execute_unlocked(rule, project, path=path, target_branch=target_branch, fingerprint=fingerprint)


def _execute_unlocked(
    rule: str | None = None,
    project: str | None = None,
    *,
    path: str | None = None,
    target_branch: str | None = None,
    fingerprint: str | None = None,
) -> dict:
    from cleardebt.checkout import checkout_branch, checkout_default
    from cleardebt.controls import gitlab_credentials, unbound_reason

    project = (project or "").strip()
    if not project:
        raise NotEligible("没有写项目，不会跑。")
    if fingerprint:
        with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
            checkpointer.setup()
            graph = build_graph(checkpointer)
            state = graph.get_state({"configurable": {"thread_id": fingerprint}}).values or {}
        if not state:
            raise NotEligible("没有这条告警的过闸记录。")
        if (state.get("project") or "").strip() != project:
            raise NotEligible("这条过闸记录属于另一个项目，不会复用。")
        state_branch = (state.get("git_branch") or "").strip()
        if target_branch and state_branch and state_branch != target_branch.strip():
            raise NotEligible("这条过闸记录属于另一个分支，不会复用。")
        issue = {
            "fingerprint": fingerprint,
            "rule": state.get("rule") or rule or "javascript:S1128",
            "path": state.get("path") or path or "",
            "project": project,
        }
    else:
        issue = _find_issue(load_sonar_token(), rule or "javascript:S1128", project, path=path)
        fingerprint = execution_fingerprint(issue["fingerprint"], project)
        issue["fingerprint"] = fingerprint
        with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
            checkpointer.setup()
            graph = build_graph(checkpointer)
            state = graph.get_state({"configurable": {"thread_id": fingerprint}}).values
    saved = gitlab_credentials(issue["project"])
    if not saved:
        raise NotEligible(unbound_reason(issue["project"]))
    if saved.get("read_only") or not saved.get("token"):
        raise NotEligible(f"{issue['project']} 是无令牌只读仓库，只能扫描和查看问题。")
    from cleardebt.hosting import HostingError, create_request, ensure_push_access

    try:
        ensure_push_access(saved)
    except HostingError as error:
        raise NotEligible(str(error)) from error
    ensure_eligible(state.get("level", ""))
    existing = find_merge_request(fingerprint)
    if existing:
        return {"action": "skip", **existing}

    repo = ROOT / "var" / "merge" / fingerprint[:12]
    base = (target_branch or "").strip()
    if base:
        checkout_branch(repo, saved, base)
        default = base
    else:
        default = checkout_default(repo, saved)
    ensure_verified_base(repo, state)
    branch = "cleardebt/" + state["rule"].split(":")[-1].lower() + "-" + fingerprint[:8]
    git(repo, ["config", "user.name", "ClearDebt"])
    git(repo, ["config", "user.email", "cleardebt@localhost"])
    git(repo, ["checkout", "-b", branch])
    changed = state.get("changed_files") or [
        {"path": state["path"], "after": state.get("after") or ""}
    ]
    changed_paths = _apply_verified_files(repo, changed)
    git(repo, ["add", "--", *changed_paths])
    git(repo, ["commit", "-m", f"ClearDebt 修复（{state['rule']}）"])
    push(repo, saved["token"], branch, provider=saved.get("provider") or "gitlab")
    try:
        opened = create_request(
            saved,
            source_branch=branch,
            target_branch=default,
            title=f"ClearDebt 修复（{state['rule']}）",
            description=render_description(state),
        )
    except HostingError as error:
        raise NotEligible(str(error)) from error
    record = {
        "action": "opened",
        "fingerprint": fingerprint,
        "rule": state.get("rule") or issue.get("rule") or "",
        "path": state.get("path") or issue.get("path") or "",
        "merge_request_iid": opened["iid"],
        "web_url": opened["web_url"],
        "source_branch": branch,
        "target_branch": default,
        "provider": opened.get("provider") or saved.get("provider") or "gitlab",
    }
    save_merge_request(record)
    return record


def _apply_verified_files(repo: Path, changed: list[dict]) -> list[str]:
    paths = []
    root = repo.resolve()
    for item in changed:
        relative = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not relative:
            raise NotEligible("过闸记录里有空文件名，不会开请求。")
        target = (repo / relative).resolve()
        if target != root and root not in target.parents:
            raise NotEligible("过闸记录里的文件超出仓库，不会开请求。")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("after") or ""), encoding="utf-8")
        paths.append(relative)
    if not paths:
        raise NotEligible("过闸记录里没有可提交的文件。")
    return paths


def ensure_verified_base(repo: Path, state: dict) -> None:
    expected = (state.get("base_commit") or "").strip()
    if not expected:
        return
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    if actual != expected:
        raise NotEligible("目标分支在修复验证后已变化，请重新运行告警修复。")


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("要写上白名单里的项目。不传项目不会跑。")
        return 1
    rule = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None
    try:
        payload = execute(rule, sys.argv[1].strip())
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


def push(repo: Path, token: str, ref: str, *, provider: str = "gitlab") -> None:
    run_git(repo, ["push", "origin", f"{ref}:{ref}"], token, provider=provider)


def run_git(repo: Path, args: list[str], token: str, *, provider: str = "gitlab") -> None:
    from cleardebt.hosting import askpass_username

    user = askpass_username(provider)
    askpass = Path(tempfile.mkdtemp(prefix="cleardebt-askpass-")) / "askpass"
    askpass.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  *[Uu]sername*) echo {user} ;;\n'
        '  *) echo "$CLEARDEBT_GIT_TOKEN" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    askpass.chmod(askpass.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["CLEARDEBT_GIT_TOKEN"] = token
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    # An empty helper clears keychain credentials so the project token is used.
    completed = subprocess.run(
        ["git", "-c", "credential.helper=", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git 没有给出原因。").strip()
        if token:
            detail = detail.replace(token, "***")
        raise RuntimeError(f"git {' '.join(args)} 失败：{detail[-500:]}")


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
        raise NotEligible("还没填写代码仓库地址，服务碰不到任何仓库。")
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
        conn.execute("ALTER TABLE issue_merge_requests ADD COLUMN IF NOT EXISTS rule TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE issue_merge_requests ADD COLUMN IF NOT EXISTS path TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            INSERT INTO issue_merge_requests
                (fingerprint, merge_request_iid, web_url, source_branch, target_branch, rule, path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint) DO UPDATE SET
                merge_request_iid = EXCLUDED.merge_request_iid,
                web_url = EXCLUDED.web_url,
                rule = EXCLUDED.rule,
                path = EXCLUDED.path
            """,
            (
                record["fingerprint"],
                record["merge_request_iid"],
                record["web_url"],
                record["source_branch"],
                record["target_branch"],
                record.get("rule") or "",
                record.get("path") or "",
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
