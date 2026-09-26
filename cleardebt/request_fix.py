"""Remediate quality-gate failures on an open merge request.

Opens a *second* merge request that targets the original MR's source branch.
Never hard-pushes onto that branch.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import open_merge_request
import run_issue
from cleardebt.assign import _sonar_row, create_session, finish_session, resolve_selected_issues
from cleardebt.controls import gate, gitlab_credentials, load_controls, save_report, unbound_reason
from cleardebt.gitlab_mr import NotEligible
from cleardebt.issue_graph import sonar_base_url
from cleardebt.triage import describe_message, issue_repairable, tier_for_issue
from list_issues import fetch_issues, load_token


def request_fix_gate(settings: dict, repo: str) -> str | None:
    from cleardebt.controls import project_read_only, project_switches

    refused = gate(settings, repo)
    if refused:
        return refused
    if project_read_only(settings, repo):
        return f"{repo} 是无令牌只读仓库，只能扫描和查看问题。"
    if not settings.get("request_fix", True):
        return "请求修复关掉了。"
    if not project_switches(settings, repo)["request_fix"]:
        return f"{repo} 的请求修复关掉了。"
    return None


def load_merge_request(repo: str, mr_iid: int) -> dict:
    from cleardebt.hosting import HostingError, load_pull_request

    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目。")
    saved = gitlab_credentials(name)
    if not saved:
        raise ValueError(unbound_reason(name))
    try:
        iid = int(mr_iid)
    except (TypeError, ValueError) as error:
        raise ValueError("合并请求号不对。") from error
    try:
        payload = load_pull_request(saved, iid)
    except HostingError as error:
        raise ValueError(str(error)) from error
    source = payload.get("source_branch") or ""
    if not source:
        raise ValueError("这条合并请求没有源分支。")
    return {
        "repo": name,
        "mr_iid": int(payload.get("iid") or iid),
        "title": payload.get("title") or "",
        "web_url": payload.get("web_url") or "",
        "source_branch": source,
        "target_branch": payload.get("target_branch") or "",
        "state": payload.get("state") or "",
        "provider": payload.get("provider") or saved.get("provider") or "gitlab",
        "project_id": saved.get("project_id"),
        "project_path": saved.get("project_path") or "",
        "gitlab_url": saved["url"],
        "token": saved["token"],
        "credentials": saved,
    }


def list_mr_issues(repo: str, mr_iid: int) -> dict:
    """Sonar issues on the MR analysis (pullRequest = iid)."""
    mr = load_merge_request(repo, mr_iid)
    token = load_token(None)
    rows = []
    for issue in fetch_issues(
        sonar_base_url(),
        token,
        mr["repo"],
        pull_request=str(mr["mr_iid"]),
    ):
        rule = issue.get("rule") or ""
        text = issue.get("message") or ""
        row = _sonar_row(mr["repo"], issue)
        row["message_zh"] = describe_message(rule, text)
        row["tier"] = tier_for_issue(row)
        row["eligible"] = issue_repairable(row)
        rows.append(row)
    rows.sort(key=lambda item: (item["path"], item["rule"]))
    return {
        "merge_request": {
            k: mr[k]
            for k in (
                "repo",
                "mr_iid",
                "title",
                "web_url",
                "source_branch",
                "target_branch",
                "state",
                "provider",
            )
            if k in mr
        },
        "issues": rows,
    }


def post_run_agent_note(repo: str, mr_iid: int) -> dict:
    """Comment on the MR/PR listing open issues and how to run remediation."""
    from cleardebt.hosting import HostingError, post_comment

    settings = load_controls()
    refused = request_fix_gate(settings, (repo or "").strip())
    if refused:
        raise ValueError(refused)
    listed = list_mr_issues(repo, mr_iid)
    mr = listed["merge_request"]
    issues = listed["issues"]
    eligible = [item for item in issues if item["eligible"]]
    lines = [
        "## ClearDebt · 运行修复 Agent",
        "",
        "这条合并/拉取请求在 Sonar 分析后仍有告警。勾选可修项后，在审核页「请求修复」点运行，或调用：",
        "",
        "```",
        f'POST /mrs/remediate  {{"repo":"{mr["repo"]}","mr_iid":{mr["mr_iid"]},"issues":[...]}}',
        "```",
        "",
        f"- 源分支（修复请求将打向这里，不会硬推）：`{mr['source_branch']}`",
        f"- 当前打开告警：{len(issues)}（可修 {len(eligible)}）",
        "",
    ]
    if not issues:
        lines.append("_暂无打开的告警。_")
    else:
        for item in issues:
            mark = "可修" if item["eligible"] else "跳过"
            lines.append(f"- [{mark}] `{item['rule']}` `{item['path']}` — {item['message']}")
    body = "\n".join(lines)
    saved = gitlab_credentials(mr["repo"])
    if not saved:
        raise ValueError(unbound_reason(mr["repo"]))
    try:
        note = post_comment(saved, mr["mr_iid"], body)
    except HostingError as error:
        raise ValueError(str(error)) from error
    return {
        "posted": True,
        "note_id": note.get("id"),
        "provider": note.get("provider"),
        "merge_request": mr,
        "issue_count": len(issues),
    }


def remediate_merge_request(
    repo: str, mr_iid: int, selections: list[dict], *, session_id: int | None = None
) -> dict:
    """Run selected MR issues; open fix MRs targeting the original source branch."""
    settings = load_controls()
    name = (repo or "").strip()
    refused = request_fix_gate(settings, name)
    if refused:
        raise ValueError(refused)
    mr = load_merge_request(name, mr_iid)
    current = list_mr_issues(name, mr_iid)["issues"]
    picks = resolve_selected_issues(selections, current)
    if not picks:
        raise ValueError("没有勾选告警。")
    ineligible = [item for item in picks if not item["eligible"]]
    eligible = [item for item in picks if item["eligible"]]
    session_id = session_id or create_session(
        source="request_fix",
        repo=name,
        issue_count=len(picks),
        status="running",
    )
    results = []
    decisions = []
    try:
        for item in eligible:
            try:
                kwargs = {
                    "path": item["path"],
                    "git_branch": mr["source_branch"],
                    "pull_request": str(mr["mr_iid"]),
                }
                if item.get("sonar_key"):
                    kwargs["issue_key"] = item["sonar_key"]
                ran = run_issue.execute(
                    item["rule"],
                    name,
                    **kwargs,
                )
            except SystemExit as error:
                text = error.code if isinstance(error.code, str) else "没有跑完。"
                ran = {
                    "rule": item["rule"],
                    "path": item["path"],
                    "level": "L3",
                    "reason": text or "没有跑完。",
                    "project": name,
                }
            results.append(ran)
            decision = {
                "repo": name,
                "rule": ran.get("rule") or item["rule"],
                "path": ran.get("path") or item["path"],
                "level": ran.get("level"),
                "reason": ran.get("reason"),
                "fingerprint": ran.get("fingerprint"),
                "action": "no_mr",
                "target_branch": mr["source_branch"],
                "parent_mr_iid": mr["mr_iid"],
            }
            if ran.get("level") == "L1" and not settings.get("dry_run"):
                try:
                    opened = open_merge_request.execute(
                        ran.get("rule") or item["rule"],
                        name,
                        path=ran.get("path") or item["path"],
                        target_branch=mr["source_branch"],
                        fingerprint=ran.get("fingerprint"),
                    )
                    decision["action"] = "opened" if opened.get("action") == "opened" else "already"
                    decision["web_url"] = opened.get("web_url")
                    decision["fix_mr_source"] = opened.get("source_branch")
                except NotEligible as error:
                    decision["action"] = "no_mr"
                    decision["reason"] = str(error)
            elif ran.get("level") == "L1" and settings.get("dry_run"):
                decision["action"] = "dry_run"
                decision["reason"] = "空跑，不开合并请求。"
            decisions.append(decision)
        for item in ineligible:
            decisions.append(
                {
                    "repo": name,
                    "rule": item["rule"],
                    "path": item["path"],
                    "level": "",
                    "action": "no_mr",
                    "reason": "这条规则不在可自动修范围，已跳过。",
                    "target_branch": mr["source_branch"],
                    "parent_mr_iid": mr["mr_iid"],
                }
            )
        if decisions:
            save_report(name, bool(settings.get("dry_run")), decisions)
        finish_session(
            session_id,
            status="completed",
            details={
                "kind": "request_fix",
                "mr_iid": mr["mr_iid"],
                "source_branch": mr["source_branch"],
                "selected": len(picks),
                "ran": len(eligible),
                "skipped_ineligible": len(ineligible),
                "decisions": decisions,
                "warning": "勾选里含有不可修规则，已跳过那些。" if ineligible else "",
            },
        )
    except Exception as error:
        finish_session(session_id, status="failed", details={"error": str(error)})
        raise
    return {
        "started": True,
        "session_id": session_id,
        "source": "request_fix",
        "repo": name,
        "merge_request": {
            k: mr[k] for k in ("mr_iid", "source_branch", "target_branch", "web_url")
        },
        "results": results,
        "decisions": decisions,
        "skipped_ineligible": len(ineligible),
    }
