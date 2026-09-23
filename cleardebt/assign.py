"""Manual Assign to Agent and session activity (manual vs scheduled)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import open_merge_request
import run_issue
from cleardebt.controls import backlog_gate, gate, load_controls, save_report
from cleardebt.gitlab_mr import NotEligible
from cleardebt.issue_graph import sonar_base_url
from cleardebt.sca import fetch_dependency_risks
from cleardebt.triage import llm_repairable
from list_issues import fetch_issues, issue_path, load_token

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)


def list_backlog_issues(repo: str) -> list[dict]:
    """Open Sonar issues + dependency risks on a project, marked eligible for the agent."""
    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目，列不出告警。")
    token = load_token(None)
    host = sonar_base_url()
    rows = []
    for issue in fetch_issues(host, token, name):
        rule = issue.get("rule") or ""
        path = issue_path(issue.get("component", ""), name)
        rows.append(
            {
                "repo": name,
                "rule": rule,
                "path": path,
                "message": issue.get("message") or "",
                "sonar_key": issue.get("key") or "",
                "eligible": llm_repairable(rule),
            }
        )
    for risk in fetch_dependency_risks(host, token, name):
        rows.append(risk)
    rows.sort(key=lambda item: (item["path"], item["rule"]))
    return rows


def assign_to_agent(repo: str, selections: list[dict], *, source: str = "manual") -> dict:
    """Run selected backlog issues through the graph. Only L1 opens merge requests."""
    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目，不能指派。")
    settings = load_controls()
    refused = backlog_gate(settings, name)
    if refused:
        raise ValueError(refused)
    picks = []
    for item in selections or []:
        rule = (item.get("rule") or "").strip()
        path = (item.get("path") or "").strip()
        if not rule or not path:
            continue
        picks.append(
            {
                "rule": rule,
                "path": path,
                "message": item.get("message") or "",
                "package": item.get("package") or "",
                "to_version": item.get("to_version") or "",
                "eligible": llm_repairable(rule),
            }
        )
    if not picks:
        raise ValueError("没有勾选告警。")
    ineligible = [item for item in picks if not item["eligible"]]
    eligible = [item for item in picks if item["eligible"]]
    session_id = create_session(source=source, repo=name, issue_count=len(picks), status="running")
    results = []
    decisions = []
    try:
        for item in eligible:
            try:
                ran = run_issue.execute(
                    item["rule"],
                    name,
                    path=item["path"],
                    message=item.get("message") or "",
                    sca_package=item.get("package") or "",
                    sca_to_version=item.get("to_version") or "",
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
            }
            if ran.get("level") == "L1" and not settings.get("dry_run"):
                try:
                    opened = open_merge_request.execute(ran.get("rule") or item["rule"], name)
                    decision["action"] = "opened" if opened.get("action") == "opened" else "already"
                    decision["web_url"] = opened.get("web_url")
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
                }
            )
        if decisions:
            save_report(name, bool(settings.get("dry_run")), decisions)
        finish_session(
            session_id,
            status="completed",
            details={
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
        "source": source,
        "repo": name,
        "results": results,
        "decisions": decisions,
        "skipped_ineligible": len(ineligible),
    }


def create_session(*, source: str, repo: str, issue_count: int, status: str = "pending") -> int:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        row = conn.execute(
            """
            INSERT INTO agent_sessions (source, status, repo, issue_count, details)
            VALUES (%s, %s, %s, %s, '{}'::jsonb)
            RETURNING id
            """,
            (source, status, repo, issue_count),
        ).fetchone()
    return int(row[0])


def finish_session(
    session_id: int, *, status: str, details: dict, issue_count: int | None = None
) -> None:
    from psycopg.types.json import Json

    _ensure()
    with psycopg.connect(DB_URI) as conn:
        if issue_count is None:
            conn.execute(
                """
                UPDATE agent_sessions
                SET status = %s, details = %s, finished_at = now()
                WHERE id = %s
                """,
                (status, Json(details), session_id),
            )
        else:
            conn.execute(
                """
                UPDATE agent_sessions
                SET status = %s, details = %s, issue_count = %s, finished_at = now()
                WHERE id = %s
                """,
                (status, Json(details), issue_count, session_id),
            )


def list_sessions(limit: int = 20) -> list[dict]:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source, status, repo, issue_count, details, finished_at
            FROM agent_sessions
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        created = row[1].astimezone().strftime("%Y-%m-%d %H:%M") if row[1] else ""
        finished = row[7].astimezone().strftime("%Y-%m-%d %H:%M") if row[7] else ""
        out.append(
            {
                "id": row[0],
                "created_at": created,
                "source": row[2],
                "status": row[3],
                "repo": row[4],
                "issue_count": row[5],
                "details": row[6] or {},
                "finished_at": finished,
            }
        )
    return out


def _ensure() -> None:
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                repo TEXT NOT NULL,
                issue_count INTEGER NOT NULL DEFAULT 0,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                finished_at TIMESTAMPTZ
            )
            """
        )
