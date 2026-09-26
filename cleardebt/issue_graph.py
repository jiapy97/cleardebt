"""One Sonar issue through triage, fix, checks, and a level.

L1, L2, and L3 are written here from gate results. A model does not decide them.
"""

from __future__ import annotations

import ast
import hashlib
import json
import operator
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from cleardebt.a_fix import apply_mechanical
from cleardebt.b_fix import ModelOutputError, apply_once, mechanical_fix_enabled, model_ladder, propose_patch
from cleardebt.coverage_gate import changed_lines, uncovered_changed_lines
from cleardebt.evidence import collect
from cleardebt.fake_fix import review_patch
from cleardebt.languages import TEST_EXCLUSIONS, has_node_test_stack, is_js_ts_path, sonar_sources_value, sources_covering
from cleardebt.sandbox import run_project_tests
from cleardebt.sca import apply_bump, is_sca_rule, parse_risk, verify_bump
from cleardebt.triage import REPAIR_TIERS, describe, issue_repairable, normalize_tier, tier_for_issue

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
    sonar_fingerprint: str
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
    git_branch: str
    pull_request: str
    proposed_old: str
    proposed_new: str
    model_error: str
    fix_method: str
    fix_attempt: int
    model_used: str
    model_attempts: Annotated[list, operator.add]
    sca_package: str
    sca_to_version: str
    sonar_type: str
    sonar_severity: str
    sonar_impacts: list[dict]
    sonar_effort: str
    quick_fix: bool
    history: Annotated[list[str], operator.add]
    changed_files: list[dict]
    session_id: int
    base_commit: str
    agent_mode: bool
    agent_ready: bool
    agent_verified: bool
    agent_messages: list[dict]
    agent_call: dict
    agent_pending_calls: list[dict]
    agent_tool_count: int
    agent_patch_count: int
    agent_full_count: int
    agent_usage_tokens: int
    agent_infra_count: int
    agent_last_action_hash: str
    agent_repeat_count: int
    agent_research_count: int
    agent_started_at: float


def triage(state: IssueState) -> dict:
    return {"tier": tier_for_issue(state), "history": ["triage"]}


def fix(state: IssueState) -> dict:
    file_path = Path(state["work_dir"]) / state["path"]
    rule = state["rule"]
    if not issue_repairable(state):
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
            "changed_files": bumped.get("changed_files") or [],
            "history": ["fix"],
        }

    before = file_path.read_text(encoding="utf-8")
    if int(state.get("fix_attempt") or 0) == 0:
        after = apply_mechanical(rule, before, state.get("path", ""))
        if isinstance(after, str) and after != before:
            file_path.write_text(after, encoding="utf-8")
            return {
                "before": before,
                "after": after,
                "fix_method": "mechanical",
                "changed_files": [{"path": state.get("path", ""), "before": before, "after": after}],
                "history": ["fix"],
            }

    if _autonomous_enabled(state):
        return {
            "before": before,
            "after": before,
            "fix_method": "agent",
            "agent_ready": True,
            "agent_verified": False,
            "agent_started_at": time.time(),
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
        "changed_files": [{"path": state.get("path", ""), "before": before, "after": after}],
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
    changed = state.get("changed_files") or [
        {"path": state["path"], "before": state.get("before", ""), "after": state.get("after", "")}
    ]
    rejections = review_patch([(item["path"], item.get("before", ""), item.get("after", "")) for item in changed])
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
        sources = sonar_sources_value(Path(state["work_dir"]))
        for item in state.get("changed_files") or [{"path": state.get("path") or ""}]:
            sources = sources_covering(sources, item.get("path") or "")
        rescan_check.scan_temp_project(
            temp_key,
            token,
            sources=Path(state["work_dir"]),
            exclusions=TEST_EXCLUSIONS,
            sonar_sources=sources,
            sonar_url=_docker_sonar_url(sonar_base_url()),
            baseline=project,
        )
        rescan_check.wait_until_processed(sonar_base_url(), token, temp_key)
        before = rescan_check.issue_rows(
            sonar_base_url(),
            token,
            project,
            pull_request=state.get("pull_request") or None,
            branch=(state.get("git_branch") or None) if not state.get("pull_request") else None,
        )
        after = rescan_check.issue_rows(sonar_base_url(), token, temp_key)
        result = rescan_check.verdict(before, after, state["rule"])
    finally:
        rescan_check.delete_temp_project(sonar_base_url(), token, temp_key)
    if rescan_check.analysis_date(sonar_base_url(), token, project) != stamp:
        raise RuntimeError("baseline project was overwritten")
    removed_fingerprints = {row["fingerprint"] for row in result["removed"]}
    target_fingerprint = state.get("sonar_fingerprint") or state["fingerprint"]
    ok = bool(result["ok"] and target_fingerprint in removed_fingerprints)
    return {
        "rescan_ok": ok,
        "rescan_removed": [_brief(row) for row in result["removed"]],
        "rescan_added": [_brief(row) for row in result["added"]],
        "history": ["rescan"],
    }


def run_tests(state: IssueState) -> dict:
    import os

    work = Path(state["work_dir"])
    if os.environ.get("CLEARDEBT_SKIP_TEST_GATE", "").strip().lower() in {"1", "true", "yes"}:
        return {
            "tests_passed": True,
            "tests_skipped": True,
            "uncovered_lines": [],
            "history": ["test"],
        }
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
    changed = state.get("changed_files") or [
        {"path": state["path"], "before": state.get("before", ""), "after": state.get("after", "")}
    ]
    missed = []
    for item in changed:
        lines = uncovered_changed_lines(
            coverage, work / item["path"],
            changed_lines(item.get("before", ""), item.get("after", "")),
            item.get("after", ""),
        )
        missed.extend(lines if len(changed) == 1 else [f"{item['path']}:{line}" for line in lines])
    return {"tests_passed": True, "tests_skipped": False, "uncovered_lines": missed, "history": ["test"]}


def decide(state: IssueState) -> dict:
    tier = normalize_tier(state.get("tier"))
    if tier == "skip":
        level, reason = "skip", f"不在可修规则清单里，不修：{describe(state['rule'])}。"
    elif tier not in REPAIR_TIERS:
        level, reason = "skip", "这门语言 Agent 还没接入，不修。"
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
    if normalize_tier(state.get("tier")) in REPAIR_TIERS:
        return "fix"
    return "decide"


def route_after_fix(state: IssueState) -> str:
    if state.get("agent_ready"):
        return "agent_model"
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
    if state.get("fix_method") == "sca":
        return False
    if state.get("fix_method") == "mechanical" and mechanical_fix_enabled():
        return False
    attempt = int(state.get("fix_attempt") or 0)
    return attempt + 1 < len(model_ladder())


def _autonomous_enabled(state: IssueState) -> bool:
    raw = os.environ.get("CLEARDEBT_AUTONOMOUS_AGENT", "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    if "agent_mode" in state:
        return bool(state["agent_mode"])
    from cleardebt.controls import load_controls

    project = state.get("project") or ""
    return any(
        item.get("sonar_key") == project and bool(item.get("agent_mode"))
        for item in load_controls().get("bindings") or []
    )


def _agent_limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def agent_model(state: IssueState) -> dict:
    """One model turn. LangGraph checkpoints after every model/tool pair."""
    from cleardebt.agent_model import AgentModelError, choose_tool
    from cleardebt.agent_tools import TOOLS

    session_id = int(state.get("session_id") or 0)
    if session_id:
        from cleardebt.assign import session_cancelled

        if session_cancelled(session_id):
            return {"model_error": "会话已取消。", "agent_call": {}, "agent_pending_calls": [], "history": ["agent_model"]}

    count = int(state.get("agent_tool_count") or 0)
    elapsed = time.time() - float(state.get("agent_started_at") or time.time())
    if count >= _agent_limit("CLEARDEBT_AGENT_MAX_TOOLS", 20) or elapsed > _agent_limit("CLEARDEBT_AGENT_MAX_SECONDS", 900):
        return {"model_error": "自主 Agent 达到工具次数或时间上限。", "agent_call": {}, "history": ["agent_model"]}
    if int(state.get("agent_usage_tokens") or 0) >= _agent_limit("CLEARDEBT_AGENT_MAX_TOKENS", 30000):
        return {"model_error": "自主 Agent 达到 token 上限。", "agent_call": {}, "history": ["agent_model"]}
    if int(state.get("agent_infra_count") or 0) >= 2:
        return {"model_error": "Sonar 或测试基础设施连续失败，任务已停止。", "agent_call": {}, "history": ["agent_model"]}
    if int(state.get("agent_repeat_count") or 0) >= 3:
        return {"model_error": "连续重复相同工具调用，任务已停止。", "agent_call": {}, "history": ["agent_model"]}
    research_count = int(state.get("agent_research_count") or 0)
    research_limit = _agent_limit("CLEARDEBT_AGENT_MAX_RESEARCH_TOOLS", 8)
    limited = research_count >= research_limit
    available_tools = [tool for tool in TOOLS if tool["function"]["name"] in {"apply_patch", "report_blocker"}] if limited else TOOLS
    context = {
        "rule": state.get("rule"), "path": state.get("path"), "message": state.get("message"),
        "start_line": state.get("start_line"), "end_line": state.get("end_line"),
    }
    messages = [
        {"role": "system", "content": (
            "你是 ClearDebt 修复 Agent。每轮必须调用恰好一个提供的工具。"
            "先取证，再提交最小补丁；补丁后调用 run_checks(full)。"
            "如果检查失败，阅读反馈，继续搜索或修改。你不能自行宣布修好，也不能调用未提供的工具。"
            "如果无法确定安全改法，调用 report_blocker 说明具体阻碍；不要反复做同样的搜索。"
            "不要修改测试、Sonar 配置或依赖文件。"
        )},
        {"role": "user", "content": "请修复这个 Sonar 告警：" + json.dumps(context, ensure_ascii=False)},
        *(state.get("agent_messages") or []),
    ]
    if limited:
        messages.append({"role": "user", "content": "连续取证已达上限。现在只能提交有依据的补丁，或调用 report_blocker 说明无法安全修复的原因。"})
    try:
        call = choose_tool(messages, available_tools)
    except (AgentModelError, ValueError) as error:
        if session_id:
            from cleardebt.agent_events import record

            record(session_id, state.get("fingerprint") or "", kind="error", tool="模型",
                   summary=f"选择工具失败：{error}")
        return {"model_error": str(error), "agent_call": {}, "history": ["agent_model"]}
    pending = call.get("pending_calls") or []
    offered = {tool["function"]["name"] for tool in available_tools}
    if any(item.get("name") not in offered for item in [call, *pending]):
        reason = "模型选择了当前未提供的工具。"
        if session_id:
            from cleardebt.agent_events import record

            record(session_id, state.get("fingerprint") or "", kind="error", tool="模型", summary=reason)
        return {"model_error": reason, "agent_call": {}, "agent_pending_calls": [], "history": ["agent_model"]}
    if count + 1 + len(pending) > _agent_limit("CLEARDEBT_AGENT_MAX_TOOLS", 20):
        reason = "模型一次选择的工具超过本任务剩余额度。"
        if session_id:
            from cleardebt.agent_events import record

            record(session_id, state.get("fingerprint") or "", kind="error", tool="模型", summary=reason)
        return {"model_error": reason, "agent_call": {}, "agent_pending_calls": [], "history": ["agent_model"]}
    if session_id:
        from cleardebt.agent_events import record

        record(session_id, state.get("fingerprint") or "", kind="model", tool="模型",
               summary="选择工具：" + "、".join([call.get("name") or "未知", *(item.get("name") or "未知" for item in pending)]))
    tokens = int((call.get("usage") or {}).get("total_tokens") or 0)
    return {
        "agent_call": call,
        "agent_pending_calls": pending,
        "agent_usage_tokens": int(state.get("agent_usage_tokens") or 0) + tokens,
        "model_used": call.get("model") or "",
        "history": ["agent_model"],
    }


def route_after_agent_model(state: IssueState) -> str:
    return "agent_tool" if state.get("agent_call") and not state.get("model_error") else "decide"


def _agent_checks(state: dict, level: str, scan: Callable, tests: Callable) -> tuple[dict, dict]:
    from cleardebt.agent_tools import ToolError

    if not state.get("changed_files"):
        raise ToolError("no_patch", "请先提交补丁再运行检查")
    checked = anti_cheat(state)
    if checked["rejections"]:
        return {"passed": False, "phase": "anti_cheat", "rejections": checked["rejections"]}, {
            **checked, "agent_verified": False,
        }
    syntax_errors = []
    for item in state.get("changed_files") or []:
        path = item.get("path") or ""
        source = item.get("after") or ""
        if path.endswith(".py"):
            try:
                ast.parse(source)
            except SyntaxError as error:
                syntax_errors.append(f"{path}:{error.lineno}: {error.msg}")
        elif is_js_ts_path(path):
            from cleardebt.grammar import parser_for

            if parser_for(path).parse(source.encode("utf-8")).root_node.has_error:
                syntax_errors.append(f"{path}: 语法树解析失败")
    if syntax_errors:
        return {"passed": False, "phase": "syntax", "errors": syntax_errors}, {"agent_verified": False}
    if level == "quick":
        return {"passed": True, "phase": "quick"}, {**checked, "agent_verified": False}
    try:
        scan_result = scan(state)
    except Exception as error:  # noqa: BLE001
        return {"passed": False, "phase": "infrastructure", "reason": str(error)[:500]}, {"agent_verified": False}
    if not scan_result.get("rescan_ok"):
        return {
            "passed": False, "phase": "sonar", "removed": scan_result.get("rescan_removed") or [],
            "added": scan_result.get("rescan_added") or [], "reason": scan_result.get("reason") or "原告警仍在或出现新告警",
        }, {**scan_result, "agent_verified": False}
    try:
        test_result = tests({**state, **scan_result})
    except Exception as error:  # noqa: BLE001
        return {"passed": False, "phase": "infrastructure", "reason": str(error)[:500]}, {**scan_result, "agent_verified": False}
    passed = bool(test_result.get("tests_passed") and not test_result.get("uncovered_lines"))
    if passed:
        work = Path(state["work_dir"])
        for item in state.get("changed_files") or []:
            if (work / item["path"]).read_text(encoding="utf-8") != item.get("after"):
                return {"passed": False, "phase": "workspace_changed", "reason": "检查期间源码发生变化"}, {
                    **scan_result, **test_result, "agent_verified": False,
                }
    return {
        "passed": passed, "phase": "full", "tests_passed": test_result.get("tests_passed"),
        "tests_skipped": test_result.get("tests_skipped", False),
        "uncovered_lines": test_result.get("uncovered_lines") or [],
    }, {**scan_result, **test_result, "agent_verified": passed, "rejections": []}


def agent_tool(state: IssueState, *, scan: Callable = rescan, tests: Callable = run_tests) -> dict:
    """Execute one selected tool and return its observation to the model."""
    from cleardebt.agent_tools import AgentTools

    session_id = int(state.get("session_id") or 0)
    if session_id:
        from cleardebt.assign import session_cancelled

        if session_cancelled(session_id):
            return {"model_error": "会话已取消。", "agent_call": {}, "agent_pending_calls": [], "history": ["agent_tool:cancelled"]}
    call = state.get("agent_call") or {}
    name = call.get("name") or ""
    args = call.get("arguments") or {}
    patch_count = int(state.get("agent_patch_count") or 0)
    full_count = int(state.get("agent_full_count") or 0)
    if name == "apply_patch" and patch_count >= _agent_limit("CLEARDEBT_AGENT_MAX_PATCHES", 3):
        result, update = {"ok": False, "error_code": "budget", "summary": "补丁尝试次数已用完"}, {}
    elif name == "run_checks" and args.get("level") == "full" and full_count >= _agent_limit("CLEARDEBT_AGENT_MAX_FULL_CHECKS", 2):
        result, update = {"ok": False, "error_code": "budget", "summary": "完整检查次数已用完"}, {}
    else:
        toolbox = AgentTools(state, check=lambda current, level: _agent_checks(current, level, scan, tests),
                             call_id=call.get("call_id") or "")
        result, update = toolbox.execute(name, args)
    if session_id:
        from cleardebt.agent_events import record

        data = result.get("data") or {}
        if name == "run_checks" and data:
            summary = f"{data.get('phase') or '检查'}：{'通过' if data.get('passed') else '未通过'}"
        elif name == "report_blocker" and data:
            summary = f"无法安全修复：{data.get('reason') or '原因未提供'}"
        else:
            summary = result.get("summary") or ("完成" if result.get("ok") else "失败")
        patch_hash = ""
        if name == "apply_patch" and result.get("ok"):
            patch_hash = hashlib.sha256(json.dumps(update.get("changed_files") or [], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        record(
            session_id, state.get("fingerprint") or "", kind="tool", tool=name,
            call_id=call.get("call_id") or "",
            summary=str(summary),
            details={"ok": bool(result.get("ok")), "error_code": result.get("error_code") or "",
                     "passed": data.get("passed"), "tool_count": int(state.get("agent_tool_count") or 0) + 1,
                     "patch_hash": patch_hash},
        )
    assistant = call.get("assistant") or {}
    observation = {"role": "tool", "tool_call_id": call.get("call_id") or "", "content": json.dumps(result, ensure_ascii=False)}
    messages = [*(state.get("agent_messages") or [])]
    if assistant:
        messages.append(assistant)
    messages.append(observation)
    # Keep the recent dialogue bounded; older observations remain in checkpoints.
    messages = messages[-12:]
    while messages and messages[0].get("role") == "tool":
        messages.pop(0)
    pending = [] if name == "report_blocker" else (state.get("agent_pending_calls") or [])
    action_hash = hashlib.sha256(json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    repeated = int(state.get("agent_repeat_count") or 0) + 1 if action_hash == state.get("agent_last_action_hash") else 1
    return {
        **update,
        "agent_messages": messages,
        "agent_call": pending[0] if pending else {},
        "agent_pending_calls": pending[1:],
        "agent_research_count": (
            0 if name == "apply_patch" else
            int(state.get("agent_research_count") or 0) + 1
            if name in {"get_issue_context", "search_repo", "find_references", "read_file", "get_diff"}
            else int(state.get("agent_research_count") or 0)
        ),
        "agent_tool_count": int(state.get("agent_tool_count") or 0) + 1,
        "agent_patch_count": patch_count + (1 if name == "apply_patch" and result.get("ok") else 0),
        "agent_full_count": full_count + (
            1 if name == "run_checks" and args.get("level") == "full" and result.get("ok")
            and (result.get("data") or {}).get("phase") in {"sonar", "full", "workspace_changed"}
            else 0
        ),
        "agent_infra_count": (
            int(state.get("agent_infra_count") or 0) + 1
            if (result.get("data") or {}).get("phase") == "infrastructure" else 0
        ),
        "agent_last_action_hash": action_hash,
        "agent_repeat_count": repeated,
        "history": [f"agent_tool:{name}"],
    }


def route_after_agent_tool(state: IssueState) -> str:
    if state.get("model_error"):
        return "decide"
    if state.get("agent_call"):
        return "agent_tool"
    return "decide" if state.get("agent_verified") else "agent_model"


def build_graph(checkpointer, *, rescan_node: Callable | None = None, test_node: Callable | None = None, interrupt_before: list[str] | None = None):
    builder = StateGraph(IssueState)
    builder.add_node("triage", triage)
    builder.add_node("fix", fix)
    builder.add_node("retry_fix", retry_fix)
    builder.add_node("agent_model", agent_model)
    builder.add_node("agent_tool", lambda state: agent_tool(state, scan=rescan_node or rescan, tests=test_node or run_tests))
    builder.add_node("anti_cheat", anti_cheat)
    builder.add_node("rescan", rescan_node or rescan)
    builder.add_node("test", test_node or run_tests)
    builder.add_node("decide", decide)
    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", route_after_triage, {"fix": "fix", "decide": "decide"})
    builder.add_conditional_edges(
        "fix",
        route_after_fix,
        {"decide": "decide", "anti_cheat": "anti_cheat", "retry_fix": "retry_fix", "agent_model": "agent_model"},
    )
    builder.add_conditional_edges("agent_model", route_after_agent_model, {"agent_tool": "agent_tool", "decide": "decide"})
    builder.add_conditional_edges("agent_tool", route_after_agent_tool, {"agent_tool": "agent_tool", "agent_model": "agent_model", "decide": "decide"})
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
