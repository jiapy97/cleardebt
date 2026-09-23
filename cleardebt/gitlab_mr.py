"""Open one GitLab merge request for an L1 issue, and only one."""

from __future__ import annotations

DEVELOPER = 30


class NotEligible(RuntimeError):
    pass


def ensure_eligible(level: str) -> None:
    if level != "L1":
        raise NotEligible(f"级别是 {level or '空'}，只有 L1 才开合并请求。")


def ensure_access(access_level: int) -> None:
    if access_level < DEVELOPER:
        raise NotEligible(
            "这个令牌在项目里是 Guest，不能推送代码，也不能开合并请求。需要 Developer 或 Maintainer。"
        )


def render_description(state: dict) -> str:
    from cleardebt.triage import is_secret_rule, problem_surface

    removed = state.get("rescan_removed") or []
    added = state.get("rescan_added") or []
    removed_text = "、".join(f"{row['rule']} {row['path']}" for row in removed) or "无"
    added_text = "、".join(f"{row['rule']} {row['path']}" for row in added) or "没有新告警"
    if state.get("tests_passed"):
        tests = "通过"
    else:
        tests = "没通过"
    uncovered = state.get("uncovered_lines") or []
    if uncovered:
        coverage = "未覆盖的行：" + ", ".join(str(line) for line in uncovered)
    else:
        coverage = "没有新增需要覆盖的代码行"
    rule = state.get("rule") or ""
    surface = problem_surface(rule)
    lines = [
        "ClearDebt 自动修复，待审。",
        "",
        "合入须人工在代码托管平台审核；Agent 不会自动合并。",
        "",
        f"- 规则：{rule}",
        f"- 问题面：{surface}",
        f"- 文件：{state.get('path')}",
        f"- 指纹：{state.get('fingerprint')}",
        f"- 重扫：去掉了 {removed_text}。{added_text}。",
        f"- 测试：{tests}",
        f"- 覆盖率：{coverage}",
        "",
    ]
    if is_secret_rule(rule):
        lines.extend(
            [
                "这是密钥类修复：代码里的硬编码已去掉，**请人工轮换已泄露的密钥**（Agent 不会替你轮换）。",
                "",
            ]
        )
    lines.append("同一条指纹再跑不会开第二个合并请求。")
    return "\n".join(lines)
