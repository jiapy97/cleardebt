#!/usr/bin/env python3
"""Run one Sonar issue through the LangGraph. No web page and no batch."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from langgraph.checkpoint.postgres import PostgresSaver

from cleardebt.issue_lock import issue_lock
from cleardebt.issue_graph import _autonomous_enabled, build_graph, next_action, sonar_base_url
from cleardebt.triage import same_route, tier_for_issue
from list_issues import fetch_issues, fingerprint, issue_path, line_span, load_token
import rescan_check

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)
RULE = "javascript:S1128"


def execute(
    rule: str = RULE,
    project: str | None = None,
    path: str | None = None,
    git_branch: str | None = None,
    pull_request: str | None = None,
    message: str = "",
    sca_package: str = "",
    sca_to_version: str = "",
    issue_key: str = "",
    session_id: int | None = None,
    benchmark_read_only: bool = False,
    benchmark_sha: str = "",
) -> dict:
    project = (project or "").strip()
    if not project:
        raise SystemExit("没有写项目，不会跑。")
    from cleardebt.controls import backlog_gate, gate, gitlab_credentials, load_controls, project_switches
    from cleardebt.sca import is_sca_rule

    settings = load_controls()
    if benchmark_sha and not benchmark_read_only:
        raise SystemExit("冻结提交只允许在只读评测入口使用。")
    if benchmark_read_only:
        public_bench_repos = {
            "bench-dayjs": ("https://github.com/iamkun/dayjs", "436bde0bcded312781cbe45dc2b0ef079a36d8e3"),
            "bench-axios": ("https://github.com/axios/axios", "5fc40e1c7478d342ec64c4e865ed4cd1a334207c"),
        }
        saved = gitlab_credentials(project)
        if (
            not os.environ.get("CLEARDEBT_BENCH_RUN_ID")
            or bool(pull_request)
            or public_bench_repos.get(project) != ((saved or {}).get("url"), benchmark_sha)
            or not (saved or {}).get("read_only")
        ):
            raise SystemExit("只读评测只允许已绑定的公开冻结仓库。")
        refused = gate(settings, project)
        if not refused and not project_switches(settings, project)["backlog_fix"]:
            refused = f"{project} 的 backlog 修复关掉了。"
    elif pull_request:
        from cleardebt.request_fix import request_fix_gate

        refused = request_fix_gate(settings, project)
    else:
        refused = backlog_gate(settings, project)
    if refused:
        raise SystemExit(refused)
    if is_sca_rule(rule):
        issue = _sca_issue(
            rule,
            project,
            path=path or "",
            message=message,
            package=sca_package,
            to_version=sca_to_version,
        )
    else:
        token = load_token(None)
        issue = _find_issue(
            token,
            rule,
            project,
            path=path,
            issue_key=issue_key,
            pull_request=pull_request,
            branch=None if pull_request else git_branch,
        )
    issue["sonar_fingerprint"] = issue["fingerprint"]
    issue["agent_mode"] = not is_sca_rule(rule) and _autonomous_enabled({
        "project": project,
        "agent_mode": any(
            item.get("sonar_key") == project and bool(item.get("agent_mode"))
            for item in settings.get("bindings") or []
        ),
    })
    issue["git_branch"] = (git_branch or "").strip()
    issue["pull_request"] = (pull_request or "").strip()
    issue["session_id"] = int(session_id or 0)
    probe_parent = ROOT / "var" / "probes"
    if issue["agent_mode"]:
        probe_parent.mkdir(parents=True, exist_ok=True)
    probe_context = tempfile.TemporaryDirectory(prefix="agent-", dir=probe_parent) if issue["agent_mode"] else nullcontext(None)
    with probe_context as probe_root:
        probe = Path(probe_root) / "repo" if probe_root else None
        if probe:
            _prepare_work_dir(probe, issue, git_branch=git_branch, pinned_sha=benchmark_sha)
        issue["fingerprint"] = execution_fingerprint(
            issue["sonar_fingerprint"], project,
            git_branch=git_branch, pull_request=pull_request,
            agent_mode=bool(issue["agent_mode"]), base_commit=issue.get("base_commit") or "",
            benchmark_run_id=os.environ.get("CLEARDEBT_BENCH_RUN_ID", ""),
        )
        with issue_lock(issue["fingerprint"]):
            with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
                checkpointer.setup()
                graph = build_graph(checkpointer)
                config, snapshot, action = _checkpoint_for_issue(graph, issue)
                config["recursion_limit"] = 2 * _agent_limit() + 15
                work = ROOT / "var" / "work" / issue["fingerprint"]
                if action == "start":
                    if probe:
                        work.parent.mkdir(parents=True, exist_ok=True)
                        if work.exists():
                            shutil.rmtree(work)
                        shutil.move(str(probe), str(work))
                    else:
                        _prepare_work_dir(work, issue, git_branch=git_branch, pinned_sha=benchmark_sha)
                    result = graph.invoke(_initial_state(issue, work), config)
                elif action == "resume":
                    if issue["agent_mode"] and not work.exists():
                        from cleardebt.agent_tools import replay_receipts

                        work.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(probe), str(work))
                        replay_receipts({"work_dir": str(work), "path": issue["path"]})
                    result = graph.invoke(None, config)
                else:
                    result = snapshot.values
                steps = _steps(graph, config)
    payload = {
        "action": action,
        "fingerprint": result["fingerprint"],
        "rule": result["rule"],
        "path": result["path"],
        "work_dir": result.get("work_dir"),
        "tier": result.get("tier"),
        "fix_method": result.get("fix_method") or "",
        "level": result.get("level"),
        "reason": result.get("reason"),
        "history": result.get("history"),
        "proposed_old": result.get("proposed_old"),
        "proposed_new": result.get("proposed_new"),
        "project": result.get("project") or project,
        "model_attempts": result.get("model_attempts"),
        "changed_files": result.get("changed_files") or [],
        "agent_tool_count": result.get("agent_tool_count") or 0,
        "agent_patch_count": result.get("agent_patch_count") or 0,
        "agent_full_count": result.get("agent_full_count") or 0,
        "agent_usage_tokens": result.get("agent_usage_tokens") or 0,
        "tests_skipped": bool(result.get("tests_skipped")),
        "rescan_ok": bool(result.get("rescan_ok")),
        "checkpoints": steps,
    }
    if payload.get("proposed_old") and payload.get("level") in {"L1", "L2", "L3"}:
        payload["suggestion"] = _save_suggestion(payload)
    return payload


def _checkpoint_for_issue(graph, issue: dict) -> tuple[dict, object, str]:
    """Reuse a checkpoint only while its triage agrees with this Sonar issue."""
    config = {"configurable": {"thread_id": issue["fingerprint"]}}
    snapshot = graph.get_state(config)
    action = next_action(snapshot)
    if action != "start":
        current_tier = tier_for_issue(issue)
        if not same_route((snapshot.values or {}).get("tier"), current_tier):
            # Keep the old result intact while giving the changed decision its own work directory.
            raw = f"{issue['fingerprint']}\ntriage:{current_tier}"
            issue["fingerprint"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            config = {"configurable": {"thread_id": issue["fingerprint"]}}
            snapshot = graph.get_state(config)
            action = next_action(snapshot)
    return config, snapshot, action


def execution_fingerprint(
    issue_fingerprint: str,
    project: str,
    *,
    git_branch: str | None = None,
    pull_request: str | None = None,
    agent_mode: bool = False,
    base_commit: str = "",
    benchmark_run_id: str = "",
) -> str:
    """Identity for checkpoints/work/MRs, scoped to one repo and ref.

    Sonar issue fingerprints intentionally remain project-agnostic so a
    baseline and its temporary rescan can be compared. They must not be used
    as durable job ids because two repositories can contain identical code.
    """
    if pull_request:
        ref = f"pr:{pull_request}:{(git_branch or '').strip()}"
    elif git_branch:
        ref = f"branch:{git_branch.strip()}"
    else:
        ref = "default"
    raw = f"{project.strip()}\n{ref}\n{issue_fingerprint}"
    if agent_mode:
        # A protocol change must not reuse a completed checkpoint that stopped
        # before the model could call a tool under the previous adapter.
        raw += f"\nagent:v5\n{base_commit}"
    if benchmark_run_id:
        raw += f"\nbenchmark:{benchmark_run_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) < 3 or not sys.argv[1].strip() or not sys.argv[2].strip():
        print("要写上规则和白名单里的项目。不传项目不会跑。")
        return 1
    payload = execute(sys.argv[1].strip(), sys.argv[2].strip())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("level") else 1


def _save_suggestion(payload: dict) -> dict:
    import psycopg

    record = {
        "fingerprint": payload["fingerprint"],
        "rule": payload["rule"],
        "path": payload["path"],
        "level": payload["level"],
        "reason": payload["reason"],
        "old_string": payload["proposed_old"],
        "new_string": payload["proposed_new"],
    }
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_suggestions (
                fingerprint TEXT PRIMARY KEY,
                rule TEXT NOT NULL,
                path TEXT NOT NULL,
                level TEXT NOT NULL,
                reason TEXT NOT NULL,
                old_string TEXT NOT NULL,
                new_string TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO issue_suggestions
                (fingerprint, rule, path, level, reason, old_string, new_string)
            VALUES (%(fingerprint)s, %(rule)s, %(path)s, %(level)s, %(reason)s, %(old_string)s, %(new_string)s)
            ON CONFLICT (fingerprint) DO UPDATE SET
                level = EXCLUDED.level,
                reason = EXCLUDED.reason,
                old_string = EXCLUDED.old_string,
                new_string = EXCLUDED.new_string
            """,
            record,
        )
    return record


def _find_issue(
    token: str,
    rule: str = RULE,
    project: str | None = None,
    path: str | None = None,
    *,
    issue_key: str = "",
    pull_request: str | None = None,
    branch: str | None = None,
) -> dict:
    project = (project or "").strip()
    if not project:
        raise SystemExit("没有写项目，不会跑。")
    want = (path or "").strip()
    sources: dict[str, str] = {}
    for issue in fetch_issues(
        sonar_base_url(),
        token,
        project,
        pull_request=pull_request,
        branch=branch,
    ):
        if issue["rule"] != rule:
            continue
        if issue_key and issue.get("key") != issue_key:
            continue
        issue_file = issue_path(issue.get("component", ""), project)
        if want and issue_file != want:
            continue
        text_range = issue.get("textRange") or {}
        start = int(text_range.get("startLine") or 1)
        end = int(text_range.get("endLine") or start)
        component = issue["component"]
        if component not in sources:
            sources[component] = rescan_check.api_text(sonar_base_url(), token, "/api/sources/raw", {"key": component})
        line_text = line_span(sources[component], start, end)
        return {
            "fingerprint": fingerprint(issue["rule"], issue_file, line_text),
            "rule": issue["rule"],
            "path": issue_file,
            "message": issue.get("message", ""),
            "start_line": start,
            "end_line": end,
            "source": sources[component],
            "project": project,
            "sonar_type": issue.get("type") or "",
            "sonar_severity": issue.get("severity") or "",
            "sonar_impacts": issue.get("impacts") or [],
            "sonar_effort": issue.get("effort") or issue.get("debt") or "",
            "quick_fix": bool(issue.get("quickFixAvailable")),
        }
    where = f"{project}" + (f" 文件 {want}" if want else "")
    if pull_request:
        where += f" 合并请求 {pull_request}"
    elif branch:
        where += f" 分支 {branch}"
    raise SystemExit(f"{where} 上没有没修好的 {rule} 告警。刚重扫过的话，点“重新扫描”刷新列表再勾。")


def _sca_issue(
    rule: str,
    project: str,
    *,
    path: str,
    message: str,
    package: str,
    to_version: str,
) -> dict:
    from cleardebt.sca import fingerprint_risk, parse_risk

    try:
        risk = parse_risk(message, path, package=package, to_version=to_version)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    file_path = path or risk.get("path") or "package.json"
    return {
        "fingerprint": fingerprint_risk(
            risk["package"], file_path, risk["to_version"], message[:80]
        ),
        "rule": rule,
        "path": file_path,
        "message": message or f"Upgrade {risk['package']} to version {risk['to_version']}",
        "source": "",
        "project": project,
        "sca_package": risk["package"],
        "sca_to_version": risk["to_version"],
    }


def _prepare_work_dir(work: Path, issue: dict, git_branch: str | None = None, pinned_sha: str = "") -> None:
    from cleardebt.checkout import checkout_branch, checkout_default
    from cleardebt.controls import gitlab_credentials, unbound_reason
    from cleardebt.sca import is_sca_rule

    project = issue.get("project") or ""
    saved = gitlab_credentials(project or None)
    if not saved:
        raise SystemExit(unbound_reason(project or "这个项目"))
    if git_branch:
        checkout_branch(work, saved, git_branch)
    else:
        checkout_default(work, saved)
    if pinned_sha:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=work, text=True, capture_output=True, check=True,
        ).stdout.strip()
        if current != pinned_sha:
            subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", pinned_sha],
                cwd=work, text=True, capture_output=True, check=True, timeout=120,
            )
            subprocess.run(
                ["git", "checkout", "--detach", pinned_sha],
                cwd=work, text=True, capture_output=True, check=True, timeout=30,
            )
    target = work / issue["path"]
    if not target.is_file():
        kind = "依赖清单" if is_sca_rule(issue.get("rule") or "") else "源文件"
        where = f"分支 {git_branch}" if git_branch else "默认分支"
        raise SystemExit(f"{where} 上没有 {issue['path']}（{kind}）")
    if (work / ".git").exists():
        issue["base_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=work, text=True, capture_output=True, check=True
        ).stdout.strip()


def _initial_state(issue: dict, work: Path) -> dict:
    return {
        "fingerprint": issue["fingerprint"],
        "sonar_fingerprint": issue.get("sonar_fingerprint") or issue["fingerprint"],
        "rule": issue["rule"],
        "path": issue["path"],
        "message": issue["message"],
        "start_line": int(issue.get("start_line") or 0) or None,
        "end_line": int(issue.get("end_line") or 0) or None,
        "tier": "",
        "level": "",
        "reason": "",
        "work_dir": str(work),
        "before": "",
        "after": "",
        "rejections": [],
        "rescan_removed": [],
        "rescan_added": [],
        "uncovered_lines": [],
        "project": issue["project"],
        "session_id": issue.get("session_id") or 0,
        "base_commit": issue.get("base_commit") or "",
        "agent_mode": bool(issue.get("agent_mode")),
        "git_branch": issue.get("git_branch") or "",
        "pull_request": issue.get("pull_request") or "",
        "sca_package": issue.get("sca_package") or "",
        "sca_to_version": issue.get("sca_to_version") or "",
        "sonar_type": issue.get("sonar_type") or "",
        "sonar_severity": issue.get("sonar_severity") or "",
        "sonar_impacts": issue.get("sonar_impacts") or [],
        "sonar_effort": issue.get("sonar_effort") or "",
        "quick_fix": bool(issue.get("quick_fix")),
        "fix_attempt": 0,
        "history": [],
    }


def _agent_limit() -> int:
    try:
        return max(1, int(os.environ.get("CLEARDEBT_AGENT_MAX_TOOLS", "20")))
    except ValueError:
        return 20


def _steps(graph, config) -> list[dict]:
    steps = []
    for snapshot in graph.get_state_history(config):
        steps.append(
            {
                "history": snapshot.values.get("history"),
                "next": list(snapshot.next),
            }
        )
    steps.reverse()
    return steps


if __name__ == "__main__":
    raise SystemExit(main())
