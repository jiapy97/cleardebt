"""HTTP door in front of the existing issue graph. It does not fix code itself."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres import PostgresSaver

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.controls import connect_integration, latest_sheet, load_controls, merge_bindings, save_controls
from cleardebt.gitlab_mr import NotEligible
from cleardebt.issue_graph import build_graph
from cleardebt.review import render_page
from open_merge_request import find_merge_request
from run_batch import run_controlled, run_whitelist
from run_issue import DB_URI
import open_merge_request
import run_issue

app = FastAPI(title="ClearDebt")
app.mount("/static", StaticFiles(directory=ROOT / "cleardebt" / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def console_index() -> HTMLResponse:
    index = ROOT / "cleardebt" / "static" / "console" / "index.html"
    if not index.is_file():
        return HTMLResponse(
            "<p>前端还没构建。在项目目录执行：<code>cd frontend && npm install && npm run build</code>，然后刷新。</p>",
            status_code=503,
        )
    return FileResponse(index)


@app.get("/legacy", response_class=HTMLResponse)
def review_page() -> str:
    from cleardebt.assign import list_sessions

    return render_page(latest_sheet(), _form_settings(), sessions=list_sessions())


@app.post("/setup", response_class=HTMLResponse)
def setup(
    sonar_url: str = Form(...),
    sonar_token: str = Form(""),
    gitlab_token: str = Form(""),
    github_token: str = Form(""),
    azure_token: str = Form(""),
    llm_token: str = Form(""),
    whitelist: list[str] = Form(default=[]),
    project_keys: str = Form(""),
    bindings: str = Form(""),
) -> HTMLResponse:
    names = []
    typed = [part.strip() for part in project_keys.replace("，", ",").split(",")]
    for item in [*whitelist, *typed]:
        if item and item not in names:
            names.append(item)
    paired = merge_bindings(names, bindings)
    try:
        connect_integration(
            sonar_url=sonar_url.strip(),
            sonar_token=sonar_token.strip(),
            gitlab_token=gitlab_token.strip(),
            github_token=github_token.strip(),
            azure_token=azure_token.strip(),
            llm_token=llm_token.strip(),
            whitelist=[item["sonar_key"] for item in paired],
            bindings=paired,
        )
    except (ValueError, RuntimeError) as error:
        from cleardebt.assign import list_sessions

        page = render_page(latest_sheet(), _form_settings(), error=str(error), sessions=list_sessions())
        return HTMLResponse(page, status_code=400)
    return RedirectResponse("/", status_code=303)


@app.get("/controls")
def read_controls() -> dict:
    return load_controls()


@app.post("/controls")
def update_controls(body: dict = Body(...)) -> dict:
    from cleardebt.controls import save_project_switches

    saved = save_controls(
        enabled=body.get("enabled"),
        dry_run=body.get("dry_run"),
        retrieve=body.get("retrieve"),
        backlog_automation=body.get("backlog_automation"),
        request_fix=body.get("request_fix"),
    )
    if body.get("project_switches") is not None:
        saved = save_project_switches(body.get("project_switches") or [])
    return saved


@app.post("/project-switches")
def project_switches_form(
    project: list[str] = Form(default=[]),
    backlog_fix: list[str] = Form(default=[]),
    request_fix: list[str] = Form(default=[]),
    schedule_override: list[str] = Form(default=[]),
    schedule_enabled: list[str] = Form(default=[]),
    pause_project: list[str] = Form(default=[]),
    pause_value: list[str] = Form(default=[]),
) -> RedirectResponse:
    from cleardebt.controls import save_project_switches

    backlog_on = set(backlog_fix)
    request_on = set(request_fix)
    override_on = set(schedule_override)
    schedule_on = set(schedule_enabled)
    pause_by_key = {}
    for key, value in zip(pause_project, pause_value):
        name = (key or "").strip()
        if name:
            pause_by_key[name] = (value or "").strip()
    updates = []
    for name in project:
        key = (name or "").strip()
        if not key:
            continue
        item = {
            "sonar_key": key,
            "backlog_fix": key in backlog_on,
            "request_fix": key in request_on,
        }
        if key in override_on:
            pause = pause_by_key.get(key) or None
            item["automation"] = {
                "enabled": key in schedule_on,
                "pause_when_open_mrs": pause,
            }
        else:
            item["automation"] = {}
        updates.append(item)
    save_project_switches(updates)
    return RedirectResponse("/", status_code=303)


@app.post("/switches")
def switches(
    enabled: str = Form(""),
    dry_run: str = Form(""),
    retrieve: str = Form(""),
    request_fix: str = Form(""),
) -> RedirectResponse:
    save_controls(
        enabled=enabled == "true",
        dry_run=dry_run == "true",
        retrieve=retrieve == "true",
        request_fix=request_fix == "true",
    )
    return RedirectResponse("/", status_code=303)


@app.post("/schedule")
def schedule_form(
    schedule_enabled: str = Form(""),
    frequency: str = Form("daily"),
    weekday: str = Form("0"),
    hour: str = Form("8"),
    minute: str = Form("0"),
    timezone: str = Form("Asia/Shanghai"),
    pause_when_open_mrs: str = Form(""),
) -> RedirectResponse:
    pause = (pause_when_open_mrs or "").strip()
    save_controls(
        backlog_automation={
            "enabled": schedule_enabled == "true",
            "frequency": frequency,
            "weekday": weekday,
            "hour": hour,
            "minute": minute,
            "timezone": timezone,
            "pause_when_open_mrs": pause or None,
        }
    )
    return RedirectResponse("/", status_code=303)


@app.post("/batch/run")
def run_batch(repo: str | None = None) -> dict:
    if repo:
        return run_controlled(repo)
    return run_whitelist()


@app.get("/issues")
def list_issues(repo: str = "") -> dict:
    from cleardebt.assign import list_backlog_issues

    try:
        return {"repo": repo.strip(), "issues": list_backlog_issues(repo)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/issues/assign")
def assign_issues(body: dict = Body(...)) -> dict:
    from cleardebt.agent_jobs import job_key, submit
    from cleardebt.assign import backlog_gate, finish_session, reserve_session

    name = (body.get("repo") or "").strip()
    selections = body.get("issues") or []
    if not name:
        raise HTTPException(status_code=400, detail="没有写项目，不能指派。")
    if not selections:
        raise HTTPException(status_code=400, detail="没有勾选告警。")
    refused = backlog_gate(load_controls(), name)
    if refused:
        raise HTTPException(status_code=400, detail=refused)
    session_id, created = reserve_session(
        source="manual", repo=name, issue_count=len(selections),
        job_key=job_key("manual", name, selections),
    )
    if not created:
        return {"started": True, "already_running": True, "repo": name, "session_id": session_id}
    try:
        submit("run_assign_session", name, selections, session_id, session_id=session_id)
    except Exception as error:
        finish_session(session_id, status="failed", details={"error": str(error)})
        raise HTTPException(status_code=503, detail="任务队列不可用，请稍后重试。") from error
    return {"started": True, "already_running": False, "repo": name, "session_id": session_id}


@app.get("/sessions")
def sessions(limit: int = 20) -> dict:
    from cleardebt.assign import list_sessions

    return {"sessions": list_sessions(limit)}


@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: int) -> dict:
    from cleardebt.assign import get_session

    try:
        return get_session(session_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/sessions/{session_id}/events")
def api_session_events(session_id: int) -> dict:
    from cleardebt.agent_events import events_for_session
    from cleardebt.assign import get_session

    try:
        session = get_session(session_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    fingerprints = []
    for decision in (session.get("details") or {}).get("decisions") or []:
        fingerprint = str(decision.get("fingerprint") or "").strip()
        if fingerprint and fingerprint not in fingerprints:
            fingerprints.append(fingerprint)
    return events_for_session(session_id, fingerprints)


@app.post("/api/sessions/{session_id}/cancel")
def api_cancel_session(session_id: int) -> dict:
    from cleardebt.assign import cancel_session

    return {"cancelled": cancel_session(session_id)}


@app.get("/mrs/issues")
def mr_issues(repo: str = "", mr_iid: int = 0) -> dict:
    from cleardebt.request_fix import list_mr_issues

    try:
        return list_mr_issues(repo, mr_iid)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/mrs/offer")
def mr_offer(body: dict = Body(...)) -> dict:
    from cleardebt.request_fix import post_run_agent_note

    try:
        return post_run_agent_note(body.get("repo") or "", body.get("mr_iid") or 0)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/mrs/remediate")
def mr_remediate(body: dict = Body(...)) -> dict:
    from cleardebt.agent_jobs import job_key, submit
    from cleardebt.assign import finish_session, reserve_session
    from cleardebt.request_fix import request_fix_gate

    name = (body.get("repo") or "").strip()
    try:
        iid = int(body.get("mr_iid") or 0)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="合并请求号不对。") from error
    selections = body.get("issues") or []
    if iid < 1:
        raise HTTPException(status_code=400, detail="合并请求号不对。")
    if not selections:
        raise HTTPException(status_code=400, detail="没有勾选告警。")
    refused = request_fix_gate(load_controls(), name)
    if refused:
        raise HTTPException(status_code=400, detail=refused)
    session_id, created = reserve_session(
        source="request_fix", repo=name, issue_count=len(selections),
        job_key=job_key("request_fix", name, selections, mr_iid=iid),
    )
    if not created:
        return {"started": True, "already_running": True, "repo": name, "mr_iid": iid, "session_id": session_id}
    try:
        submit("run_request_fix_session", name, iid, selections, session_id, session_id=session_id)
    except Exception as error:
        finish_session(session_id, status="failed", details={"error": str(error)})
        raise HTTPException(status_code=503, detail="任务队列不可用，请稍后重试。") from error
    return {"started": True, "already_running": False, "repo": name, "mr_iid": iid, "session_id": session_id}


@app.post("/issues/list", response_class=HTMLResponse)
def list_issues_form(repo: str = Form("")) -> HTMLResponse:
    from cleardebt.assign import list_sessions

    name = repo.strip()
    try:
        issues, scan_note = _list_issues_with_scan(name)
    except ValueError as error:
        page = render_page(
            latest_sheet(),
            _form_settings(),
            error=str(error),
            sessions=list_sessions(),
            assign_repo=name,
        )
        return HTMLResponse(page, status_code=400)
    return HTMLResponse(
        render_page(
            latest_sheet(),
            _form_settings(),
            sessions=list_sessions(),
            issues=issues,
            assign_repo=name,
            assign_notice=scan_note,
        )
    )


def _list_issues_with_scan(name: str) -> tuple[list, str]:
    from cleardebt.assign import refresh_backlog

    issues, scan_note, _stamp = refresh_backlog(name)
    return issues, scan_note


@app.post("/api/issues/suppress")
def api_suppress_issue(body: dict = Body(...)) -> dict:
    from cleardebt.assign import suppress_issue

    try:
        suppress_issue(
            body.get("repo") or "",
            body.get("rule") or "",
            body.get("path") or "",
            int(body.get("line") or 0),
            (body.get("reason") or ""),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True}


@app.post("/api/issues/unsuppress")
def api_unsuppress_issue(body: dict = Body(...)) -> dict:
    from cleardebt.assign import unsuppress_issue

    unsuppress_issue(
        body.get("repo") or "",
        body.get("rule") or "",
        body.get("path") or "",
        int(body.get("line") or 0),
    )
    return {"ok": True}


@app.get("/api/issues/snapshot")
def api_issue_snapshot(repo: str = "") -> dict:
    from cleardebt.assign import read_backlog
    from cleardebt.time_display import iso_beijing

    name = (repo or "").strip()
    try:
        issues, note, stamp = read_backlog(name)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    hidden = sum(1 for item in issues if item.get("suppressed"))
    return {
        "repo": name,
        "issues": issues,
        "scan_note": note,
        "analysis_date": iso_beijing(stamp),
        "suppressed_count": hidden,
    }


@app.get("/api/scan/progress")
def api_scan_progress(repo: str = "") -> dict:
    from cleardebt.scan_progress import read

    return {"repo": (repo or "").strip(), **read(repo)}


@app.post("/api/rules/refresh")
def api_rules_refresh() -> dict:
    from cleardebt.rules import refresh

    try:
        catalog = refresh()
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Sonar 规则拉取失败：{error}") from error
    return {"ok": True, "count": len(catalog)}


@app.post("/api/rules/pin")
def api_rules_pin(body: dict = Body(...)) -> dict:
    from cleardebt.rules import save_pin

    try:
        return save_pin(
            body.get("rule") or "",
            zh=body.get("zh") or "",
            zh_source="manual",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/bindings")
def api_bindings_list() -> dict:
    from cleardebt.controls import list_bindings

    return {"bindings": list_bindings()}


@app.post("/api/bindings")
def api_bindings_upsert(body: dict = Body(...)) -> dict:
    from cleardebt.controls import upsert_binding

    try:
        return upsert_binding(body.get("sonar_key") or "", body.get("gitlab_url") or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/bindings")
def api_bindings_delete(sonar_key: str = "") -> dict:
    from cleardebt.controls import delete_binding

    delete_binding(sonar_key)
    return {"ok": True}


@app.post("/api/bindings/test")
def api_bindings_test(body: dict = Body(...)) -> dict:
    from cleardebt.controls import test_binding

    return test_binding(body.get("sonar_key") or "", body.get("gitlab_url") or "")


@app.get("/api/bindings/health")
def api_bindings_health() -> dict:
    from cleardebt.controls import binding_health

    return {"bindings": binding_health()}


@app.get("/api/sonar/projects")
def api_sonar_projects() -> dict:
    from cleardebt.controls import form_values, sonar_projects

    values = form_values()
    url = values.get("sonar_url") or ""
    token = values.get("sonar_token") or ""
    if not url or not token:
        raise HTTPException(status_code=400, detail="先填 Sonar 地址与令牌。")
    return {"projects": sonar_projects(url, token)}


@app.get("/api/hosting/projects")
def api_hosting_projects(provider: str = "gitlab") -> dict:
    from cleardebt.hosting import list_owned_projects

    try:
        return {"projects": list_owned_projects(provider)}
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/hosting/create")
def api_hosting_create(body: dict = Body(...)) -> dict:
    from cleardebt.controls import upsert_binding
    from cleardebt.hosting import create_project

    name = (body.get("name") or "").strip()
    provider = (body.get("provider") or "gitlab").strip()
    sonar_key = (body.get("sonar_key") or name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="仓库名不能为空。")
    try:
        created = create_project(provider, name)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    try:
        binding = upsert_binding(sonar_key, created["url"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"project": created, "binding": binding}


@app.get("/api/rules")
def api_rules_list(prefix: str = "") -> dict:
    from cleardebt.rules import pins
    from cleardebt.triage import describe, tier_for
    from cleardebt.ai_codefix_rules import configured as ai_codefix_rules_configured, listed

    catalog = {}
    try:
        from cleardebt.rules import catalog as live_catalog

        catalog = live_catalog()
    except Exception:
        catalog = {}
    wanted = (prefix or "").strip().lower()
    rows = []
    for key in sorted(catalog):
        if wanted and wanted not in key.lower():
            continue
        number = key.split(":")[-1]
        pin = pins().get(number, {})
        meta = catalog.get(key) or {}
        rows.append(
            {
                "key": key,
                "number": number,
                "name": meta.get("name") or "",
                "type": meta.get("type") or "",
                "severity": meta.get("severity") or "",
                "impacts": meta.get("impacts") or [],
                "clean_code_attribute": meta.get("cleanCodeAttribute") or "",
                "tier": tier_for(key),
                "ai_codefix_listed": listed(key),
                "label": describe(key),
                "pinned": bool(pin),
                "zh_source": pin.get("zh_source") or "",
            }
        )
        if len(rows) >= 500:
            break
    return {"total": len(catalog), "ai_codefix_list_enabled": ai_codefix_rules_configured(), "rules": rows}


@app.get("/api/suggestions/{fingerprint}")
def api_suggestion(fingerprint: str) -> dict:
    from cleardebt.suggestion import load

    found = load(fingerprint.strip())
    if found is None:
        raise HTTPException(status_code=404, detail="没有找到这条告警的修复建议。")
    return found


@app.get("/api/repairable-rules")
def api_repairable_rules() -> dict:
    from cleardebt.ai_codefix_rules import rule_keys
    from cleardebt.controls import sonar_credentials
    from cleardebt.repairable_rules import fetch_open_issues, summarize
    from cleardebt.rules import catalog

    credentials = sonar_credentials()
    if not credentials:
        raise HTTPException(status_code=400, detail="先在接入配置中填写 Sonar 地址与令牌。")
    try:
        keys = rule_keys()
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    issues = None
    if keys is None:
        try:
            issues = fetch_open_issues(credentials["url"], credentials["token"])
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"读取 Sonar 告警失败：{error}") from error
    try:
        metadata = catalog()
    except Exception:
        metadata = {}
    return summarize(issues, keys, metadata)


_scan_threads: dict[str, "threading.Thread"] = {}


@app.post("/api/issues/list")
def api_list_issues(body: dict = Body(...)) -> dict:
    import threading

    from cleardebt.scan_progress import complete as complete_progress, read as read_progress, report as report_progress

    name = (body.get("repo") or "").strip()
    existing = _scan_threads.get(name)
    if existing is not None and existing.is_alive():
        return {"repo": name, "started": True, "already_running": True}
    progress = read_progress(name)
    if progress.get("status") == "running" and not progress.get("stale"):
        return {"repo": name, "started": True, "already_running": True}
    try:
        from cleardebt.assign import refresh_backlog
    except ImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    def _run() -> None:
        try:
            refresh_backlog(name)
        except Exception as error:
            from cleardebt.assign import clean_error

            complete_progress(name, ok=False, note=f"重新扫描失败：{clean_error(error)}")

    thread = threading.Thread(target=_run, name=f"scan-{name}", daemon=True)
    _scan_threads[name] = thread
    report_progress(name, "正在准备重扫…")
    thread.start()
    return {"repo": name, "started": True, "already_running": False}


@app.get("/api/overview")
def api_overview() -> dict:
    try:
        settings = _form_settings()
    except Exception as error:
        controls = load_controls()
        whitelist = controls.get("whitelist") or []
        settings = {
            "configured": False,
            "sonar_url": controls.get("sonar_url") or "http://localhost:9000",
            "binding_lines": "",
            "repo_choices": [{"key": name, "selected": True} for name in whitelist],
            "whitelist": whitelist,
            "bindings": controls.get("bindings") or [],
            "enabled": controls.get("enabled", True),
            "dry_run": controls.get("dry_run", True),
            "retrieve": controls.get("retrieve", False),
            "request_fix": controls.get("request_fix", True),
            "backlog_automation": controls.get("backlog_automation") or {},
            "overview_warning": f"Sonar 连不上，只显示已保存的名单：{error}",
        }
    return settings


@app.post("/api/setup")
def api_setup(body: dict = Body(...)) -> dict:
    typed = [part.strip() for part in (body.get("project_keys") or "").replace("，", ",").split(",")]
    whitelist = [str(item) for item in body.get("whitelist") or []]
    names = []
    for item in [*whitelist, *typed]:
        if item and item not in names:
            names.append(item)
    paired = merge_bindings(names, body.get("bindings") or "")
    try:
        connect_integration(
            sonar_url=(body.get("sonar_url") or "").strip(),
            sonar_token=(body.get("sonar_token") or "").strip(),
            gitlab_token=(body.get("gitlab_token") or "").strip(),
            github_token=(body.get("github_token") or "").strip(),
            azure_token=(body.get("azure_token") or "").strip(),
            llm_token=(body.get("llm_token") or "").strip(),
            whitelist=[item["sonar_key"] for item in paired],
            bindings=paired,
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True}


@app.get("/api/reports/latest")
def api_latest_sheet() -> dict:
    return {"sheet": latest_sheet()}


@app.post("/issues/assign-form", response_class=HTMLResponse)
def assign_issues_form(repo: str = Form(""), selected: list[str] = Form(default=[])) -> HTMLResponse:
    from cleardebt.assign import list_backlog_issues, list_sessions

    name = repo.strip()
    picks = []
    for item in selected:
        if "|" not in item:
            continue
        rule, path = item.split("|", 1)
        picks.append({"rule": rule, "path": path})
    try:
        result = assign_issues({"repo": name, "issues": picks})
    except HTTPException as error:
        try:
            issues = list_backlog_issues(name) if name else []
        except ValueError:
            issues = []
        page = render_page(
            latest_sheet(),
            _form_settings(),
            error=str(error.detail),
            sessions=list_sessions(),
            issues=issues,
            assign_repo=name,
        )
        return HTMLResponse(page, status_code=error.status_code)
    try:
        issues = list_backlog_issues(name)
    except ValueError:
        issues = []
    return HTMLResponse(
        render_page(
            latest_sheet(),
            _form_settings(),
            sessions=list_sessions(),
            issues=issues,
            assign_repo=name,
            assign_notice=f"会话 #{result['session_id']} 已排队；到 Agent 活动查看进度。",
        )
    )


def _assign_notice(result: dict) -> str:
    actions = [(item.get("action") or "") for item in result.get("decisions") or []]
    opened = sum(1 for action in actions if action in ("opened", "already"))
    dry = sum(1 for action in actions if action == "dry_run")
    rest = len(actions) - opened - dry
    parts = [f"已指派 {len(actions)} 条"]
    if opened:
        parts.append(f"开请求 {opened}")
    if dry:
        parts.append(f"空跑 {dry}（没开请求）")
    if rest:
        parts.append(f"未开请求 {rest}")
    skipped = result.get("skipped_ineligible") or 0
    if skipped:
        parts.append(f"跳过不可修 {skipped}")
    return "；".join(parts) + "。下面是刷新后的列表，最新状态已更新。"


@app.post("/issues/run")
def run_one_issue(repo: str = "", rule: str = "") -> dict:
    from cleardebt.controls import backlog_gate

    settings = load_controls()
    name = repo.strip()
    if not name:
        return {"started": False, "reason": "没有写项目，不会跑。"}
    refused = backlog_gate(settings, name)
    if refused:
        return {"started": False, "reason": refused}
    chosen_rule = rule.strip() or run_issue.RULE
    try:
        ran = run_issue.execute(chosen_rule, name)
        merge_request = None
        if ran.get("level") == "L1" and not settings["dry_run"]:
            merge_request = open_merge_request.execute(
                ran.get("rule") or chosen_rule,
                name,
                path=ran.get("path"),
                fingerprint=ran.get("fingerprint"),
            )
    except NotEligible as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SystemExit as error:
        text = error.code if isinstance(error.code, str) else ""
        return {"started": False, "reason": text or "没有跑。"}
    return {"started": True, "run": ran, "merge_request": merge_request}


@app.get("/issues/{fingerprint}")
def issue_status(fingerprint: str) -> dict:
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        graph = build_graph(checkpointer)
        snapshot = graph.get_state({"configurable": {"thread_id": fingerprint}})
    values = snapshot.values or {}
    merge_request = find_merge_request(fingerprint)
    if not values and merge_request is None:
        raise HTTPException(status_code=404, detail="没有这条告警的记录")
    return {
        "fingerprint": fingerprint,
        "rule": values.get("rule"),
        "path": values.get("path"),
        "tier": values.get("tier"),
        "level": values.get("level"),
        "reason": values.get("reason"),
        "history": values.get("history"),
        "next": list(snapshot.next),
        "merge_request": merge_request,
    }


def _form_settings() -> dict:
    from cleardebt.controls import form_values, sonar_projects

    settings = form_values()
    controls = load_controls()
    settings["enabled"] = controls["enabled"]
    settings["dry_run"] = controls["dry_run"]
    settings["retrieve"] = controls["retrieve"]
    settings["request_fix"] = controls.get("request_fix", True)
    settings["backlog_automation"] = controls.get("backlog_automation") or {}
    settings["bindings"] = controls.get("bindings") or settings.get("bindings") or []
    settings["whitelist"] = controls.get("whitelist") or settings.get("whitelist") or []
    selected = set(settings["whitelist"])
    sonar_token = settings.get("sonar_token") or ""
    choices = sonar_projects(settings["sonar_url"], sonar_token)
    for name in selected:
        if name not in choices:
            choices.append(name)
    settings["repo_choices"] = [{"key": name, "selected": name in selected} for name in choices]
    # Never echo secrets into HTML; show "already saved" placeholders instead.
    settings["sonar_token_set"] = bool(sonar_token) or bool(controls.get("sonar_token_set"))
    settings["gitlab_token_set"] = bool(settings.get("gitlab_token")) or bool(controls.get("gitlab_token_set"))
    settings["github_token_set"] = bool(settings.get("github_token")) or bool(controls.get("github_token_set"))
    settings["azure_token_set"] = bool(settings.get("azure_token")) or bool(controls.get("azure_token_set"))
    settings["llm_token_set"] = bool(settings.get("llm_token")) or bool(controls.get("llm_token_set"))
    for key in ("sonar_token", "gitlab_token", "github_token", "azure_token", "llm_token"):
        settings[key] = ""
    return settings
