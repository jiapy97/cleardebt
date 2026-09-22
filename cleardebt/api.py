"""HTTP door in front of the existing issue graph. It does not fix code itself."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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
def review_page() -> str:
    return render_page(latest_sheet(), _form_settings())


@app.post("/setup", response_class=HTMLResponse)
def setup(
    sonar_url: str = Form(...),
    sonar_token: str = Form(""),
    gitlab_token: str = Form(""),
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
            whitelist=[item["sonar_key"] for item in paired],
            bindings=paired,
        )
    except (ValueError, RuntimeError) as error:
        page = render_page(latest_sheet(), _form_settings(), error=str(error))
        return HTMLResponse(page, status_code=400)
    return RedirectResponse("/", status_code=303)


@app.get("/controls")
def read_controls() -> dict:
    return load_controls()


@app.post("/controls")
def update_controls(body: dict = Body(...)) -> dict:
    return save_controls(
        enabled=body.get("enabled"),
        dry_run=body.get("dry_run"),
        retrieve=body.get("retrieve"),
    )


@app.post("/switches")
def switches(
    enabled: str = Form(""),
    dry_run: str = Form(""),
    retrieve: str = Form(""),
) -> RedirectResponse:
    save_controls(enabled=enabled == "true", dry_run=dry_run == "true", retrieve=retrieve == "true")
    return RedirectResponse("/", status_code=303)


@app.post("/batch/run")
def run_batch(repo: str | None = None) -> dict:
    if repo:
        return run_controlled(repo)
    return run_whitelist()


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
    selected = set(settings["whitelist"])
    choices = sonar_projects(settings["sonar_url"], settings["sonar_token"])
    for name in selected:
        if name not in choices:
            choices.append(name)
    settings["repo_choices"] = [{"key": name, "selected": name in selected} for name in choices]
    return settings
