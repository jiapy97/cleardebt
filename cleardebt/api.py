"""HTTP door in front of the existing issue graph. It does not fix code itself."""

from __future__ import annotations

import sys
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
    from cleardebt.assign import assign_to_agent

    try:
        return assign_to_agent(body.get("repo") or "", body.get("issues") or [])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/sessions")
def sessions(limit: int = 20) -> dict:
    from cleardebt.assign import list_sessions

    return {"sessions": list_sessions(limit)}


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
    from cleardebt.request_fix import remediate_merge_request

    try:
        return remediate_merge_request(
            body.get("repo") or "",
            body.get("mr_iid") or 0,
            body.get("issues") or [],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get("/api/issues/snapshot")
def api_issue_snapshot(repo: str = "") -> dict:
    from cleardebt.assign import read_backlog

    name = (repo or "").strip()
    try:
        issues, note, stamp = read_backlog(name)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"repo": name, "issues": issues, "scan_note": note, "analysis_date": stamp}


@app.post("/api/issues/list")
def api_list_issues(body: dict = Body(...)) -> dict:
    name = (body.get("repo") or "").strip()
    try:
        issues, scan_note = _list_issues_with_scan(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"repo": name, "issues": issues, "scan_note": scan_note}


@app.get("/api/overview")
def api_overview() -> dict:
    from cleardebt.controls import form_values

    real = form_values()
    tokens = {key: real.get(key) or "" for key in ("sonar_token", "gitlab_token", "github_token", "azure_token", "llm_token")}
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
    settings.update(tokens)
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


@app.post("/api/tokens/reveal")
def api_reveal_tokens() -> dict:
    """Return the real saved tokens for the local admin to view/edit.

    The console only listens on 127.0.0.1; values are filled into the form
    on explicit user action (never echoed into the initial page render).
    """
    from cleardebt.controls import form_values

    values = form_values()
    return {
        "sonar_token": values.get("sonar_token") or "",
        "gitlab_token": values.get("gitlab_token") or "",
        "github_token": values.get("github_token") or "",
        "azure_token": values.get("azure_token") or "",
        "llm_token": values.get("llm_token") or "",
    }


@app.post("/issues/assign-form", response_class=HTMLResponse)
def assign_issues_form(repo: str = Form(""), selected: list[str] = Form(default=[])) -> HTMLResponse:
    from cleardebt.assign import assign_to_agent, list_backlog_issues, list_sessions

    name = repo.strip()
    picks = []
    for item in selected:
        if "|" not in item:
            continue
        rule, path = item.split("|", 1)
        picks.append({"rule": rule, "path": path})
    try:
        result = assign_to_agent(name, picks)
    except ValueError as error:
        try:
            issues = list_backlog_issues(name) if name else []
        except ValueError:
            issues = []
        page = render_page(
            latest_sheet(),
            _form_settings(),
            error=str(error),
            sessions=list_sessions(),
            issues=issues,
            assign_repo=name,
        )
        return HTMLResponse(page, status_code=400)
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
            assign_notice=_assign_notice(result),
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
    from cleardebt.controls import gate

    settings = load_controls()
    name = repo.strip()
    if not name:
        return {"started": False, "reason": "没有写项目，不会跑。"}
    refused = gate(settings, name)
    if refused:
        return {"started": False, "reason": refused}
    chosen_rule = rule.strip() or run_issue.RULE
    try:
        ran = run_issue.execute(chosen_rule, name)
        merge_request = None
        if ran.get("level") == "L1" and not settings["dry_run"]:
            merge_request = open_merge_request.execute(ran.get("rule") or chosen_rule, name)
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
