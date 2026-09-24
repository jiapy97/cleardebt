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
from cleardebt.triage import describe_message, llm_repairable, sonar_tier, tier_for
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
    try:
        fetched = fetch_issues(host, token, name)
    except Exception as error:
        raise ValueError(f"连不上 Sonar（{host}）：{error}。先确认 Sonar 容器在跑。") from error
    for issue in fetched:
        rows.append(_sonar_row(name, issue))
    try:
        for risk in fetch_dependency_risks(host, token, name):
            rows.append(risk)
    except Exception:
        pass
    rows.sort(key=lambda item: (item["path"], item["rule"]))
    return _enrich(name, rows)


def _sonar_row(name: str, issue: dict) -> dict:
    rule = issue.get("rule") or ""
    path = issue_path(issue.get("component", ""), name)
    text = issue.get("message") or ""
    text_range = issue.get("textRange") or {}
    impacts = issue.get("impacts") or []
    return {
        "repo": name,
        "rule": rule,
        "path": path,
        "line": int(text_range.get("startLine") or 0),
        "message": text,
        "sonar_key": issue.get("key") or "",
        # Native Sonar signals: tiering reads only these, never a hand-written list.
        "sonar_type": issue.get("type") or "",
        "sonar_severity": issue.get("severity") or "",
        "sonar_impacts": impacts,
        "sonar_effort": issue.get("effort") or issue.get("debt") or "",
        "quick_fix": bool(issue.get("quickFixAvailable")),
        "clean_code_attribute": issue.get("cleanCodeAttribute") or "",
    }


def _enrich(name: str, rows: list[dict]) -> list[dict]:
    """Attach display fields computed from local data (no Sonar call)."""
    for item in rows:
        rule = item.get("rule") or ""
        text = item.get("message") or ""
        item["message_zh"] = describe_message(rule, text)
        item["eligible"] = llm_repairable(rule)
        item["line"] = item.get("line") or 0
        if item.get("sonar_type") or item.get("sonar_impacts"):
            item["tier"] = sonar_tier(item)
            item["tier_source"] = "sonar"
        else:
            item["tier"] = tier_for(rule)
            item["tier_source"] = "policy"
    suppressed = suppressed_map(name)
    seen = first_seen_map(name)
    for item in rows:
        key = _suppression_key(item)
        item["suppressed"] = key in suppressed
        item["first_seen"] = seen.get(key) or ""
        item["is_new"] = _is_recent(seen.get(key))
    statuses = issue_status_map([(item.get("rule") or "", item.get("path") or "") for item in rows])
    for item in rows:
        item["status"] = statuses.get((item.get("rule") or "", item.get("path") or ""))
    rows.sort(key=lambda item: (not item.get("is_new"), item.get("path") or "", item.get("rule") or ""))
    return rows


def _is_recent(stamp: str | None, days: int = 7) -> bool:
    if not stamp:
        return True
    from datetime import datetime, timedelta

    try:
        seen_at = datetime.strptime(stamp, "%Y-%m-%d %H:%M").astimezone()
        now = datetime.now().astimezone()
    except ValueError:
        return False
    return now - seen_at < timedelta(days=days)


def _assign_workers(total: int) -> int:
    import os

    try:
        configured = int(os.environ.get("CLEARDEBT_ASSIGN_WORKERS", "2"))
    except ValueError:
        configured = 2
    return max(1, min(configured, total or 1))


def clean_error(error: BaseException) -> str:
    """One human line for a scan failure: drop Java/Python stack traces.

    Scanner errors arrive as multi-line dumps; the console shows only the
    first meaningful line so users see a cause, not a traceback.
    """
    text = str(error).strip().replace("\r", "\n")
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("at ", "Caused by", "Traceback", "File \"")):
            continue
        if "ERROR" in line and len(line) > 120:
            continue
        return line[:200]
    return text[:200] or "未知错误"


def refresh_backlog(repo: str) -> tuple[list[dict], str, str]:
    """Rescan the main branch, list live issues, and persist the snapshot.

    Returns (issues, scan_note, analysis_date). Only this path touches
    Sonar analysis; page entries read the snapshot instead.
    """
    from cleardebt.baseline_scan import scan_baseline

    name = (repo or "").strip()
    try:
        scan = scan_baseline(name)
        stamp = scan.get("analysis_date") or ""
        if scan.get("skipped"):
            scan_note = f"上次分析是 {stamp}，10 分钟内扫过就不再重扫，下面是最新的告警。"
        elif stamp:
            scan_note = f"刚重扫过主分支（分析时间 {stamp}），下面是最新的告警。"
        else:
            scan_note = "刚重扫过主分支，下面是最新的告警。"
    except ValueError as error:
        scan_note = f"重扫没跑成（{error}），下面是上次分析的告警。"
        from cleardebt.scan_progress import report as report_progress

        report_progress(name, f"失败：{clean_error(error)}")
        stamp = ""
    issues = list_backlog_issues(name)
    record_first_seen(name, issues)
    save_snapshot(name, stamp, issues)
    from cleardebt.scan_progress import report as report_progress

    report_progress(name, "DONE")
    return issues, scan_note, stamp


def read_backlog(repo: str) -> tuple[list[dict], str, str]:
    """Read the persisted snapshot; never triggers a Sonar scan.

    Returns every row with suppressed/is_new flags attached; the caller
    (console) decides whether hidden rows are shown.
    """
    """Read the persisted snapshot; never triggers a Sonar scan."""
    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目，列不出告警。")
    snapshot = load_snapshot(name)
    if snapshot is None:
        raise ValueError("这个项目还没扫过，点重新扫描先扫一遍。")
    rows = []
    for item in snapshot["issues"]:
        row = dict(item)
        row["repo"] = name
        rows.append(row)
    issues = _enrich(name, rows)
    return issues, snapshot["note"], snapshot["analysis_date"]


def _suppression_key(item: dict) -> tuple[str, str, int]:
    return (
        (item.get("rule") or "").strip(),
        (item.get("path") or "").strip(),
        int(item.get("line") or 0),
    )


def suppress_issue(repo: str, rule: str, path: str, line: int = 0, reason: str = "") -> None:
    """Remember 'don't bother me with this one'; survives rescans."""
    name = (repo or "").strip()
    if not name or not (rule or "").strip() or not (path or "").strip():
        raise ValueError("仓库、规则、文件都要有，才能忽略。")
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suppressed_issues (
                repo TEXT NOT NULL,
                rule TEXT NOT NULL,
                path TEXT NOT NULL,
                line INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (repo, rule, path, line)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO suppressed_issues (repo, rule, path, line, reason)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (repo, rule, path, line) DO UPDATE SET reason = EXCLUDED.reason
            """,
            (name, rule.strip(), path.strip(), int(line or 0), reason or ""),
        )


def unsuppress_issue(repo: str, rule: str, path: str, line: int = 0) -> None:
    name = (repo or "").strip()
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "DELETE FROM suppressed_issues WHERE repo = %s AND rule = %s AND path = %s AND line = %s",
            (name, (rule or "").strip(), (path or "").strip(), int(line or 0)),
        )


def suppressed_map(repo: str) -> set[tuple[str, str, int]]:
    name = (repo or "").strip()
    if not name:
        return set()
    try:
        with psycopg.connect(DB_URI) as conn:
            rows = conn.execute(
                "SELECT rule, path, line FROM suppressed_issues WHERE repo = %s",
                (name,),
            ).fetchall()
    except Exception:
        return set()
    return {(row[0], row[1], int(row[2] or 0)) for row in rows}


def record_first_seen(repo: str, rows: list[dict]) -> None:
    """Remember when each issue first appeared; never overwrites."""
    name = (repo or "").strip()
    if not name or not rows:
        return
    try:
        with psycopg.connect(DB_URI) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_issues (
                    repo TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    path TEXT NOT NULL,
                    line INTEGER NOT NULL DEFAULT 0,
                    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (repo, rule, path, line)
                )
                """
            )
            for item in rows:
                rule, path, line = _suppression_key(item)
                if not rule:
                    continue
                conn.execute(
                    """
                    INSERT INTO seen_issues (repo, rule, path, line)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (name, rule, path, line),
                )
    except Exception:
        pass


def first_seen_map(repo: str) -> dict[tuple[str, str, int], str]:
    name = (repo or "").strip()
    if not name:
        return {}
    try:
        with psycopg.connect(DB_URI) as conn:
            rows = conn.execute(
                "SELECT rule, path, line, first_seen FROM seen_issues WHERE repo = %s",
                (name,),
            ).fetchall()
    except Exception:
        return {}
    out = {}
    for rule, path, line, seen in rows:
        try:
            stamp = seen.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            stamp = ""
        out[(rule, path, int(line or 0))] = stamp
    return out


def save_snapshot(repo: str, analysis_date: str, issues: list[dict]) -> None:
    from psycopg.types.json import Json

    _ensure()
    raw = [
        {k: item.get(k) for k in ("rule", "path", "line", "message", "message_zh", "sonar_key",
                                 "sonar_type", "sonar_severity", "sonar_impacts",
                                 "sonar_effort", "quick_fix", "clean_code_attribute")}
        for item in issues or []
    ]
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backlog_snapshots (
                repo TEXT PRIMARY KEY,
                analysis_date TEXT NOT NULL DEFAULT '',
                issues JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            INSERT INTO backlog_snapshots (repo, analysis_date, issues, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (repo) DO UPDATE SET
                analysis_date = EXCLUDED.analysis_date,
                issues = EXCLUDED.issues,
                updated_at = now()
            """,
            (repo, analysis_date or "", Json(raw)),
        )


def load_snapshot(repo: str) -> dict | None:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backlog_snapshots (
                repo TEXT PRIMARY KEY,
                analysis_date TEXT NOT NULL DEFAULT '',
                issues JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        row = conn.execute(
            "SELECT analysis_date, issues, updated_at FROM backlog_snapshots WHERE repo = %s",
            (repo,),
        ).fetchone()
    if row is None:
        return None
    stamp = row[2].astimezone().strftime("%Y-%m-%d %H:%M") if row[2] else ""
    note = f"库里快照（分析时间 {row[0]}，入库于 {stamp}）。点重新扫描才重扫入库。"
    return {"analysis_date": row[0] or "", "issues": row[1] or [], "note": note}


def issue_status_map(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Latest known state per (rule, path) from our own ledger.

    Sonar only shows OPEN issues, so "already fixed, waiting for re-analysis"
    is invisible there. We join issue_suggestions (L1/L2/L3 + reason) with
    issue_merge_requests (opened MR link). Match is by rule+path because the
    list view does not carry line text for exact fingerprints. Never raises:
    on DB trouble the list still renders, just without status.
    """
    keys = []
    for rule, path in pairs or []:
        key = ((rule or "").strip(), (path or "").strip())
        if key[0] and key not in keys:
            keys.append(key)
    if not keys:
        return {}
    try:
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
                CREATE TABLE IF NOT EXISTS issue_merge_requests (
                    fingerprint TEXT PRIMARY KEY,
                    merge_request_iid INTEGER NOT NULL,
                    web_url TEXT NOT NULL,
                    source_branch TEXT NOT NULL,
                    target_branch TEXT NOT NULL
                )
                """
            )
            suggestions = conn.execute(
                """
                SELECT fingerprint, rule, path, level, reason
                FROM issue_suggestions
                WHERE rule = ANY(%s) AND path = ANY(%s)
                """,
                ([key[0] for key in keys], [key[1] for key in keys]),
            ).fetchall()
            fingerprints = [row[0] for row in suggestions]
            mr_by_fingerprint = {}
            if fingerprints:
                for row in conn.execute(
                    "SELECT fingerprint, web_url FROM issue_merge_requests WHERE fingerprint = ANY(%s)",
                    (fingerprints,),
                ).fetchall():
                    mr_by_fingerprint[row[0]] = row[1]
            direct_mrs = {}
            try:
                for row in conn.execute(
                    "SELECT rule, path, web_url FROM issue_merge_requests WHERE rule = ANY(%s) AND path = ANY(%s)",
                    ([key[0] for key in keys], [key[1] for key in keys]),
                ).fetchall():
                    if (row[0], row[1]) in keys:
                        direct_mrs[(row[0], row[1])] = row[2]
            except Exception:
                direct_mrs = {}
    except Exception:
        return {}
    out: dict[tuple[str, str], dict] = {}
    for key, web_url in direct_mrs.items():
        out[key] = {"level": "L1", "reason": "已开过合并请求。", "mr_url": web_url}
    for fingerprint, rule, path, level, reason in suggestions:
        key = (rule, path)
        if key not in keys:
            continue
        entry = {"level": level, "reason": reason or "", "mr_url": mr_by_fingerprint.get(fingerprint, "")}
        current = out.get(key)
        if current is None or (not current["mr_url"] and entry["mr_url"]):
            out[key] = entry
        elif entry["level"] == "L1" and current["level"] != "L1" and not current["mr_url"]:
            out[key] = entry
    return out


def assign_to_agent(
    repo: str, selections: list[dict], *, source: str = "manual", session_id: int | None = None
) -> dict:
    """Run selected backlog issues through the graph. Only L1 opens merge requests."""
    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目，不能指派。")
    settings = load_controls()
    refused = backlog_gate(settings, name)
    if refused:
        raise ValueError(refused)
    picks = []
    seen_picks = set()
    for item in selections or []:
        rule = (item.get("rule") or "").strip()
        path = (item.get("path") or "").strip()
        if not rule or not path:
            continue
        key = f"{rule}|{path}"
        if key in seen_picks:
            continue
        seen_picks.add(key)
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
    from cleardebt.scan_progress import clear as clear_step, report as report_step

    session_id = session_id or create_session(
        source=source, repo=name, issue_count=len(picks), status="running"
    )
    results = []
    decisions = []
    try:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        total = len(eligible)
        workers = _assign_workers(total)
        report_step(name, f"正在并行处理 {total} 条（{workers} 路）…")
        done_count = 0
        done_lock = threading.Lock()

        def _run_one(index_item: tuple[int, dict]) -> dict:
            nonlocal done_count
            index, item = index_item
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
            with done_lock:
                done_count += 1
                report_step(name, f"第 {done_count}/{total} 条跑完（{item['rule']} {item['path']}）。")
            return {"index": index, "item": item, "ran": ran}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            ran_all = list(pool.map(_run_one, list(enumerate(eligible, start=1))))
        for entry in ran_all:
            item = entry["item"]
            ran = entry["ran"]
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
    finally:
        try:
            clear_step(name)
        except Exception:
            pass
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


def get_session(session_id: int) -> dict:
    """One session with its details (used by the console to poll assign runs)."""
    from psycopg.types.json import Json  # noqa: F401

    _ensure()
    with psycopg.connect(DB_URI) as conn:
        row = conn.execute(
            """
            SELECT id, created_at, source, status, repo, issue_count, details, finished_at
            FROM agent_sessions WHERE id = %s
            """,
            (int(session_id),),
        ).fetchone()
    if not row:
        raise ValueError(f"没有这个会话：{session_id}")
    details = row[6] or {}
    if isinstance(details, str):
        import json as _json

        try:
            details = _json.loads(details)
        except ValueError:
            details = {}
    return {
        "id": row[0],
        "created_at": row[1].isoformat() if row[1] else "",
        "source": row[2],
        "status": row[3],
        "repo": row[4],
        "issue_count": row[5],
        "details": details,
        "finished_at": row[7].isoformat() if row[7] else "",
    }


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
