"""One Sonar issue through triage, fix, checks, and a level.

L1, L2, and L3 are written here from gate results. A model does not decide them.
"""

from __future__ import annotations

import json
import operator
import sys
import uuid
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from cleardebt.a_fix import apply_mechanical
from cleardebt.b_fix import ModelOutputError, apply_once, propose_s6679
from cleardebt.coverage_gate import changed_lines, uncovered_changed_lines
from cleardebt.evidence import collect_s6679
from cleardebt.fake_fix import review_patch
from cleardebt.sandbox import run_project_tests
from cleardebt.triage import describe, rule_number, tier_for
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rescan_check  # noqa: E402


def sonar_base_url() -> str:
    from cleardebt.controls import sonar_credentials

    saved = sonar_credentials()
    if not saved:
        raise RuntimeError("还没填写 Sonar 地址，服务碰不到任何仓库。")
    return saved["url"]


def _docker_sonar_url(url: str) -> str:
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1"}:
        host = "host.docker.internal"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunparse(parsed._replace(netloc=f"{host}{port}"))


TEST_EXCLUSIONS = "**/*.test.js,**/*.test.ts,**/*.spec.js,**/*.spec.ts"


class IssueState(TypedDict, total=False):
    fingerprint: str
    rule: str
    path: str
    message: str
    tier: str
    level: str
    reason: str
    work_dir: str
    before: str
    after: str
    rejections: list
    rescan_ok: bool
    rescan_removed: list
    rescan_added: list
    tests_passed: bool
    uncovered_lines: list
    project: str
    proposed_old: str
    proposed_new: str
    model_error: str
    history: Annotated[list[str], operator.add]


def triage(state: IssueState) -> dict:
    return {"tier": tier_for(state["rule"]), "history": ["triage"]}


def fix(state: IssueState) -> dict:
    file_path = Path(state["work_dir"]) / state["path"]
    before = file_path.read_text(encoding="utf-8")
    if rule_number(state["rule"]) != "S6679":
        after = apply_mechanical(state["rule"], before, state.get("path", ""))
        if after is None:
            raise RuntimeError(f"没有这条规则的改写：{state['rule']}")
        file_path.write_text(after, encoding="utf-8")
        return {"before": before, "after": after, "history": ["fix"]}
    try:
        from cleardebt.controls import load_controls
        from cleardebt.examples import same_rule_examples

        examples = same_rule_examples(state["rule"]) if load_controls().get("retrieve") else []
        old, new = propose_s6679(collect_s6679(before, state.get("path", "")), examples)
        after = apply_once(before, old, new)
    except (ModelOutputError, ValueError, RuntimeError) as error:
        return {
            "before": before,
            "after": before,
            "model_error": str(error),
            "history": ["fix"],
        }
    file_path.write_text(after, encoding="utf-8")
    return {
        "before": before,
        "after": after,
        "proposed_old": old,
        "proposed_new": new,
        "history": ["fix"],
    }


def anti_cheat(state: IssueState) -> dict:
    rejections = review_patch([(state["path"], state.get("before", ""), state.get("after", ""))])
    return {"rejections": rejections, "history": ["anti_cheat"]}


def rescan(state: IssueState) -> dict:
    project = (state.get("project") or "").strip()
    if not project:
        raise RuntimeError("这条告警没有项目名，不会重扫。")
    token = rescan_check.load_token(None)
    temp_key = rescan_check.TEMP_PREFIX + uuid.uuid4().hex[:12]
    stamp = rescan_check.analysis_date(sonar_base_url(), token, project)
    try:
        rescan_check.scan_temp_project(
            temp_key,
            token,
            sources=Path(state["work_dir"]),
            exclusions=TEST_EXCLUSIONS,
            sonar_url=_docker_sonar_url(sonar_base_url()),
        )
        rescan_check.wait_until_processed(sonar_base_url(), token, temp_key)
        before = rescan_check.issue_rows(sonar_base_url(), token, project)
        after = rescan_check.issue_rows(sonar_base_url(), token, temp_key)
        result = rescan_check.verdict(before, after, state["rule"])
    finally:
        rescan_check.delete_temp_project(sonar_base_url(), token, temp_key)
    if rescan_check.analysis_date(sonar_base_url(), token, project) != stamp:
        raise RuntimeError("baseline project was overwritten")
    removed_fingerprints = {row["fingerprint"] for row in result["removed"]}
    ok = bool(result["ok"] and state["fingerprint"] in removed_fingerprints)
    return {
        "rescan_ok": ok,
        "rescan_removed": [_brief(row) for row in result["removed"]],
        "rescan_added": [_brief(row) for row in result["added"]],
        "history": ["rescan"],
    }


def run_tests(state: IssueState) -> dict:
    work = Path(state["work_dir"])
    completed = run_project_tests(work)
    if completed.returncode != 0:
        return {"tests_passed": False, "uncovered_lines": [], "history": ["test"]}
    coverage = json.loads((work / "coverage" / "coverage-final.json").read_text(encoding="utf-8"))
    missed = uncovered_changed_lines(
        coverage,
        work / state["path"],
        changed_lines(state.get("before", ""), state.get("after", "")),
        state.get("after", ""),
    )
    return {"tests_passed": True, "uncovered_lines": missed, "history": ["test"]}


def decide(state: IssueState) -> dict:
    if state.get("tier") == "C":
        level, reason = "C", f"C 档不修：{describe(state['rule'])}。"
    elif state.get("tier") not in {"A", "B"}:
        level, reason = "L3", "不是已接入的规则，这一步不修。"
    elif state.get("model_error"):
        level, reason = "L3", state["model_error"]
    elif state.get("rejections"):
        level, reason = "L3", state["rejections"][0]["reason"]
    elif "rescan_ok" in state and not state["rescan_ok"]:
        level, reason = "L3", "重扫没通过：原来的告警还在，或者出现了新告警。"
    elif state.get("tests_passed") is False:
        level, reason = "L3", "测试没通过。"
    elif state.get("uncovered_lines"):
        lines = ", ".join(str(line) for line in state["uncovered_lines"])
        level, reason = "L2", f"改动的行没有测试覆盖：第 {lines} 行。只留建议，不开合并请求。"
    else:
        level, reason = "L1", "重扫和测试都过了。可以开合并请求，这一步先不开。"
    return {"level": level, "reason": reason, "history": ["decide"]}


def route_after_triage(state: IssueState) -> str:
    if state.get("tier") in {"A", "B"}:
        return "fix"
    return "decide"


def route_after_fix(state: IssueState) -> str:
    if state.get("model_error"):
        return "decide"
    return "anti_cheat"


def route_after_anti_cheat(state: IssueState) -> str:
    if state.get("rejections"):
        return "decide"
    return "rescan"


def route_after_rescan(state: IssueState) -> str:
    if not state.get("rescan_ok"):
        return "decide"
    return "test"


def build_graph(checkpointer, *, rescan_node: Callable | None = None, test_node: Callable | None = None, interrupt_before: list[str] | None = None):
    builder = StateGraph(IssueState)
    builder.add_node("triage", triage)
    builder.add_node("fix", fix)
    builder.add_node("anti_cheat", anti_cheat)
    builder.add_node("rescan", rescan_node or rescan)
    builder.add_node("test", test_node or run_tests)
    builder.add_node("decide", decide)
    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", route_after_triage, {"fix": "fix", "decide": "decide"})
    builder.add_conditional_edges("fix", route_after_fix, {"decide": "decide", "anti_cheat": "anti_cheat"})
    builder.add_conditional_edges("anti_cheat", route_after_anti_cheat, {"decide": "decide", "rescan": "rescan"})
    builder.add_conditional_edges("rescan", route_after_rescan, {"decide": "decide", "test": "test"})
    builder.add_edge("test", "decide")
    builder.add_edge("decide", END)
    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)


def next_action(snapshot) -> str:
    values = snapshot.values or {}
    if values.get("level") and not snapshot.next:
        return "skip"
    if snapshot.next:
        return "resume"
    return "start"


def _brief(row: dict) -> dict:
    return {"rule": row["rule"], "path": row["path"], "fingerprint": row["fingerprint"]}
