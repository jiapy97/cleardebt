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
from cleardebt.b_fix import ModelOutputError, apply_once, mechanical_fix_enabled, model_ladder, propose_patch
from cleardebt.coverage_gate import changed_lines, uncovered_changed_lines
from cleardebt.evidence import collect
from cleardebt.fake_fix import review_patch
from cleardebt.languages import TEST_EXCLUSIONS, has_node_test_stack, sonar_sources_value
from cleardebt.sandbox import run_project_tests
from cleardebt.sca import apply_bump, is_sca_rule, parse_risk, verify_bump
from cleardebt.triage import describe, llm_repairable, tier_for

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


class IssueState(TypedDict, total=False):
    fingerprint: str
    rule: str
    path: str
    message: str
    start_line: int
    end_line: int
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
    tests_skipped: bool
    uncovered_lines: list
    project: str
    proposed_old: str
    proposed_new: str
    model_error: str
    fix_method: str
    fix_attempt: int
    model_used: str
    model_attempts: Annotated[list, operator.add]
    sca_package: str
    sca_to_version: str
    history: Annotated[list[str], operator.add]


def triage(state: IssueState) -> dict:
    return {"tier": tier_for(state["rule"]), "history": ["triage"]}


def fix(state: IssueState) -> dict:
    file_path = Path(state["work_dir"]) / state["path"]
    rule = state["rule"]
    if not llm_repairable(rule):
        raise RuntimeError(f"没有这条规则的改写：{rule}")

    if is_sca_rule(rule):
        try:
            risk = parse_risk(
                state.get("message") or "",
                state.get("path") or "",
                package=state.get("sca_package") or "",
                to_version=state.get("sca_to_version") or "",
            )
            bumped = apply_bump(Path(state["work_dir"]), risk)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            before = file_path.read_text(encoding="utf-8") if file_path.is_file() else ""
            return {
                "before": before,
                "after": before,
                "model_error": str(error),
                "fix_method": "sca",
                "history": ["fix"],
            }
        return {
            "before": bumped["before"],
            "after": bumped["after"],
            "path": bumped["path"],
            "proposed_old": bumped["before"][:500],
            "proposed_new": bumped["after"][:500],
            "fix_method": "sca",
            "sca_package": bumped["package"],
            "sca_to_version": bumped["to_version"],
            "history": ["fix"],
        }

    before = file_path.read_text(encoding="utf-8")
    if mechanical_fix_enabled():
        after = apply_mechanical(rule, before, state.get("path", ""))
        if after is not None:
            file_path.write_text(after, encoding="utf-8")
            return {
                "before": before,
                "after": after,
                "fix_method": "mechanical",
                "history": ["fix"],
            }

    try:
        from cleardebt.controls import load_controls
        from cleardebt.examples import same_rule_examples

        examples = same_rule_examples(rule) if load_controls().get("retrieve") else []
        evidence = collect(
            rule,
            before,
            state.get("path", ""),
            message=state.get("message", ""),
            start_line=state.get("start_line"),
            end_line=state.get("end_line"),
        )
        attempt = int(state.get("fix_attempt") or 0)
        ladder = model_ladder()
        model = ladder[min(attempt, len(ladder) - 1)]
        old, new = propose_patch(
            rule=rule,
            source=before,
            path=state.get("path", ""),
            message=state.get("message", ""),
            evidence=evidence,
            examples=examples,
            model=model,
        )
        after = apply_once(before, old, new)
    except (ModelOutputError, ValueError, RuntimeError) as error:
        attempt = int(state.get("fix_attempt") or 0)
        ladder = model_ladder()
        model = ladder[min(attempt, len(ladder) - 1)] if ladder else ""
        return {
            "before": before,
            "after": before,
            "model_error": str(error),
            "fix_method": "llm",
            "fix_attempt": attempt,
            "model_used": model,
            "model_attempts": [{"model": model, "error": str(error)}],
            "history": ["fix"],
        }
    file_path.write_text(after, encoding="utf-8")
    return {
        "before": before,
        "after": after,
        "proposed_old": old,
        "proposed_new": new,
        "fix_method": "llm",
        "fix_attempt": attempt,
        "model_used": model,
        "model_attempts": [{"model": model, "ok": True}],
        "model_error": "",
        "history": ["fix"],
    }


def retry_fix(state: IssueState) -> dict:
    """Restore the original file and bump the model attempt after a gate or parse failure."""
    file_path = Path(state["work_dir"]) / state["path"]
    before = state.get("before") or ""
    if before and file_path.is_file():
        file_path.write_text(before, encoding="utf-8")
    attempt = int(state.get("fix_attempt") or 0) + 1
    reason = state.get("model_error") or ""
    if state.get("rejections"):
        reason = state["rejections"][0].get("reason") or reason
    elif "rescan_ok" in state and not state.get("rescan_ok"):
        reason = "重扫没通过"
    elif state.get("tests_passed") is False:
        reason = "测试没通过"
    elif state.get("uncovered_lines"):
        reason = "改动行缺覆盖"
    return {
        "after": before,
        "rejections": [],
        "rescan_ok": False,
        "rescan_removed": [],
        "rescan_added": [],
        "tests_passed": False,
        "tests_skipped": False,
        "uncovered_lines": [],
        "model_error": "",
        "proposed_old": "",
        "proposed_new": "",
        "fix_attempt": attempt,
        "model_attempts": [{"retry_after": reason, "next_attempt": attempt}],
        "history": ["retry_fix"],
    }


def anti_cheat(state: IssueState) -> dict:
    if is_sca_rule(state.get("rule") or ""):
        # Manifest/lock edits are expected; skip emptied-function AST checks.
        return {"rejections": [], "history": ["anti_cheat"]}
    rejections = review_patch([(state["path"], state.get("before", ""), state.get("after", ""))])
    return {"rejections": rejections, "history": ["anti_cheat"]}


def rescan(state: IssueState) -> dict:
    if is_sca_rule(state.get("rule") or ""):
        risk = {
            "package": state.get("sca_package") or "",
            "to_version": state.get("sca_to_version") or "",
            "path": state.get("path") or "",
            "ecosystem": "",
            "message": state.get("message") or "",
        }
        if not risk["package"] or not risk["to_version"]:
            try:
                parsed = parse_risk(risk["message"], risk["path"])
                risk.update(parsed)
            except ValueError as error:
                return {
                    "rescan_ok": False,
                    "rescan_removed": [],
                    "rescan_added": [],
                    "history": ["rescan"],
                    "reason": str(error),
                }
        checked = verify_bump(Path(state["work_dir"]), risk)
        return {
            "rescan_ok": bool(checked.get("ok")),
            "rescan_removed": (
                [{"rule": state.get("rule"), "path": risk.get("path"), "package": risk.get("package")}]
                if checked.get("ok")
                else []
            ),
            "rescan_added": [],
            "history": ["rescan"],
            "reason": checked.get("reason") or "",
        }
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
            sonar_sources=sonar_sources_value(Path(state["work_dir"])),
            sonar_url=_docker_sonar_url(sonar_base_url()),
            baseline=project,
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
    if not has_node_test_stack(work):
        # Python / Java / C# (and any non-npm repo): Sonar rescan is the hard gate.
        return {
            "tests_passed": True,
            "tests_skipped": True,
            "uncovered_lines": [],
            "history": ["test"],
        }
    completed = run_project_tests(work)
    if completed.returncode != 0:
        return {"tests_passed": False, "tests_skipped": False, "uncovered_lines": [], "history": ["test"]}
    coverage = json.loads((work / "coverage" / "coverage-final.json").read_text(encoding="utf-8"))
    missed = uncovered_changed_lines(
        coverage,
        work / state["path"],
        changed_lines(state.get("before", ""), state.get("after", "")),
        state.get("after", ""),
    )
    return {"tests_passed": True, "tests_skipped": False, "uncovered_lines": missed, "history": ["test"]}


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
    elif state.get("tests_skipped"):
        if is_sca_rule(state.get("rule") or ""):
            level, reason = "L1", "依赖已升到建议版本。可以开合并请求。"
        else:
            level, reason = "L1", "重扫过了。这个仓库没有 Node 测试栈，测试闸已跳过。可以开合并请求。"
    else:
        level, reason = "L1", "重扫和测试都过了。可以开合并请求，这一步先不开。"
    return {"level": level, "reason": reason, "history": ["decide"]}


def route_after_triage(state: IssueState) -> str:
    if state.get("tier") in {"A", "B"}:
        return "fix"
    return "decide"


def route_after_fix(state: IssueState) -> str:
    if state.get("model_error"):
        if _can_retry(state):
            return "retry_fix"
        return "decide"
    return "anti_cheat"


def route_after_anti_cheat(state: IssueState) -> str:
    if state.get("rejections"):
        if _can_retry(state):
            return "retry_fix"
        return "decide"
    return "rescan"


def route_after_rescan(state: IssueState) -> str:
    if not state.get("rescan_ok"):
        if _can_retry(state):
            return "retry_fix"
        return "decide"
    return "test"


def route_after_test(state: IssueState) -> str:
    failed = state.get("tests_passed") is False or bool(state.get("uncovered_lines"))
    if failed and _can_retry(state):
        return "retry_fix"
    return "decide"


def _can_retry(state: IssueState) -> bool:
    if state.get("fix_method") == "sca" or mechanical_fix_enabled():
        return False
    attempt = int(state.get("fix_attempt") or 0)
    return attempt + 1 < len(model_ladder())


def build_graph(checkpointer, *, rescan_node: Callable | None = None, test_node: Callable | None = None, interrupt_before: list[str] | None = None):
    builder = StateGraph(IssueState)
    builder.add_node("triage", triage)
    builder.add_node("fix", fix)
    builder.add_node("retry_fix", retry_fix)
    builder.add_node("anti_cheat", anti_cheat)
    builder.add_node("rescan", rescan_node or rescan)
    builder.add_node("test", test_node or run_tests)
    builder.add_node("decide", decide)
    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", route_after_triage, {"fix": "fix", "decide": "decide"})
    builder.add_conditional_edges(
        "fix",
        route_after_fix,
        {"decide": "decide", "anti_cheat": "anti_cheat", "retry_fix": "retry_fix"},
    )
    builder.add_edge("retry_fix", "fix")
    builder.add_conditional_edges(
        "anti_cheat",
        route_after_anti_cheat,
        {"decide": "decide", "rescan": "rescan", "retry_fix": "retry_fix"},
    )
    builder.add_conditional_edges(
        "rescan",
        route_after_rescan,
        {"decide": "decide", "test": "test", "retry_fix": "retry_fix"},
    )
    builder.add_conditional_edges("test", route_after_test, {"decide": "decide", "retry_fix": "retry_fix"})
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
