#!/usr/bin/env python3
"""Run one Sonar issue through the LangGraph. No web page and no batch."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from langgraph.checkpoint.postgres import PostgresSaver

from cleardebt.issue_graph import build_graph, next_action, sonar_base_url
from list_issues import fetch_issues, fingerprint, issue_path, line_span, load_token
import rescan_check

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)
RULE = "javascript:S1128"


def execute(rule: str = RULE, project: str | None = None) -> dict:
    project = (project or "").strip()
    if not project:
        raise SystemExit("没有写项目，不会跑。")
    from cleardebt.controls import gate, load_controls

    refused = gate(load_controls(), project)
    if refused:
        raise SystemExit(refused)
    token = load_token(None)
    issue = _find_issue(token, rule, project)
    work = ROOT / "var" / "work" / issue["fingerprint"]
    config = {"configurable": {"thread_id": issue["fingerprint"]}}
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        graph = build_graph(checkpointer)
        snapshot = graph.get_state(config)
        action = next_action(snapshot)
        if action == "start":
            _prepare_work_dir(work, issue)
            result = graph.invoke(_initial_state(issue, work), config)
        elif action == "resume":
            result = graph.invoke(None, config)
        else:
            result = snapshot.values
        steps = _steps(graph, config)
    return {
        "action": action,
        "fingerprint": result["fingerprint"],
        "rule": result["rule"],
        "path": result["path"],
        "work_dir": result.get("work_dir"),
        "tier": result.get("tier"),
        "level": result.get("level"),
        "reason": result.get("reason"),
        "history": result.get("history"),
        "proposed_old": result.get("proposed_old"),
        "proposed_new": result.get("proposed_new"),
        "project": result.get("project") or project,
        "checkpoints": steps,
    }


def main() -> int:
    if len(sys.argv) < 3 or not sys.argv[1].strip() or not sys.argv[2].strip():
        print("要写上规则和白名单里的项目。不传项目不会跑。")
        return 1
    payload = execute(sys.argv[1].strip(), sys.argv[2].strip())
    if payload.get("level") in {"L2", "L3"} and payload.get("proposed_old"):
        payload["suggestion"] = _save_suggestion(payload)
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


def _find_issue(token: str, rule: str = RULE, project: str | None = None) -> dict:
    project = (project or "").strip()
    if not project:
        raise SystemExit("没有写项目，不会跑。")
    sources: dict[str, str] = {}
    for issue in fetch_issues(sonar_base_url(), token, project):
        if issue["rule"] != rule:
            continue
        path = issue_path(issue.get("component", ""), project)
        text_range = issue.get("textRange") or {}
        start = int(text_range.get("startLine") or 1)
        end = int(text_range.get("endLine") or start)
        component = issue["component"]
        if component not in sources:
            sources[component] = rescan_check.api_text(sonar_base_url(), token, "/api/sources/raw", {"key": component})
        line_text = line_span(sources[component], start, end)
        return {
            "fingerprint": fingerprint(issue["rule"], path, line_text),
            "rule": issue["rule"],
            "path": path,
            "message": issue.get("message", ""),
            "source": sources[component],
            "project": project,
        }
    raise SystemExit(f"no open {rule} issue on {project}")


def _prepare_work_dir(work: Path, issue: dict) -> None:
    from cleardebt.checkout import checkout_default
    from cleardebt.controls import gitlab_credentials, unbound_reason

    project = issue.get("project") or ""
    saved = gitlab_credentials(project or None)
    if not saved:
        raise SystemExit(unbound_reason(project or "这个项目"))
    checkout_default(work, saved)
    target = work / issue["path"]
    if not target.is_file():
        raise SystemExit(f"默认分支上没有 {issue['path']}")


def _initial_state(issue: dict, work: Path) -> dict:
    return {
        "fingerprint": issue["fingerprint"],
        "rule": issue["rule"],
        "path": issue["path"],
        "message": issue["message"],
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
        "history": [],
    }


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
