"""LLM proposes one replacement. It does not decide that the issue is fixed."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from cleardebt.triage import describe

ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK_TOKEN_FILE = ROOT / "deploy" / "deepseek" / ".token"
LLM_TOKEN_FILE = ROOT / "deploy" / "llm" / ".token"


class ModelOutputError(ValueError):
    pass


def mechanical_fix_enabled() -> bool:
    return os.environ.get("CLEARDEBT_MECHANICAL_FIX", "").strip().lower() in {"1", "true", "yes"}


def llm_credentials() -> dict:
    token = (
        os.environ.get("CLEARDEBT_LLM_API_KEY", "").strip()
        or os.environ.get("LLM_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        or _file_token(LLM_TOKEN_FILE)
        or _file_token(DEEPSEEK_TOKEN_FILE)
        or _db_llm_token()
    )
    if not token:
        raise ModelOutputError(
            "还没配置大模型密钥：在审核页接入里填写，或设置 CLEARDEBT_LLM_API_KEY / deploy/llm/.token"
        )
    base = (
        os.environ.get("CLEARDEBT_LLM_BASE_URL", "").strip()
        or os.environ.get("DEEPSEEK_BASE_URL", "").strip()
        or "https://api.deepseek.com"
    )
    model = model_ladder()[0]
    return {"token": token, "base_url": base.rstrip("/"), "model": model}


def _db_llm_token() -> str:
    from cleardebt.controls import llm_token

    return llm_token()


def model_ladder() -> list[str]:
    """Cheaper model first; optional upgrades via CLEARDEBT_LLM_MODELS or _UPGRADE_MODEL."""
    raw = os.environ.get("CLEARDEBT_LLM_MODELS", "").strip()
    if raw:
        found = [item.strip() for item in raw.split(",") if item.strip()]
        if found:
            return found
    base = os.environ.get("CLEARDEBT_LLM_MODEL", "").strip() or "deepseek-flash"
    upgrade = os.environ.get("CLEARDEBT_LLM_UPGRADE_MODEL", "").strip()
    if upgrade and upgrade != base:
        return [base, upgrade]
    return [base]

def parse_replacement(text: str) -> tuple[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ModelOutputError("模型没有交出替换片段") from error
    if not isinstance(data, dict):
        raise ModelOutputError("模型没有交出替换片段")
    extra = set(data) - {"old_string", "new_string", "type"}
    if extra or "old_string" not in data or "new_string" not in data:
        raise ModelOutputError("模型交了替换片段以外的内容")
    old, new = data["old_string"], data["new_string"]
    if not isinstance(old, str) or not isinstance(new, str) or not old or old == new:
        raise ModelOutputError("替换片段不能用")
    return old, new


def apply_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ModelOutputError(f"要替换的原文出现了 {count} 次，不能改")
    return source.replace(old, new, 1)


def propose_patch(
    *,
    rule: str,
    source: str,
    path: str = "",
    message: str = "",
    evidence: dict | None = None,
    examples: list[dict] | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    """Ask the model for one old/new replacement. Gates still decide L1/L2/L3."""
    creds = llm_credentials()
    chosen_model = (model or "").strip() or creds["model"]
    chosen = examples or []
    prompt = build_patch_prompt(
        rule=rule,
        description=describe(rule),
        source=source,
        path=path,
        message=message,
        evidence=evidence,
        examples=chosen,
    )
    _remember(prompt, bool(chosen), rule)
    request = urllib.request.Request(
        _completions_url(creds["base_url"]),
        data=json.dumps(
            {
                "model": chosen_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你只输出一个 JSON 对象，键只能是 old_string 和 new_string。"
                            "不要解释，不要说已经修好，不要自评是否过关。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8"),
        headers={"Authorization": f"Bearer {creds['token']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return parse_replacement(content)

def propose_s6679(evidence: dict, examples: list[dict] | None = None) -> tuple[str, str]:
    return propose_patch(
        rule="javascript:S6679",
        source=evidence.get("function_source") or "",
        path="",
        message="自己和自己用 == 比较",
        evidence=evidence,
        examples=examples,
    )


def build_patch_prompt(
    *,
    rule: str,
    description: str,
    source: str,
    path: str = "",
    message: str = "",
    evidence: dict | None = None,
    examples: list[dict] | None = None,
) -> str:
    lines = [
        f"规则：{description}（{rule}）",
        f"文件：{path or '（未指定）'}",
        f"告警：{message or '（无）'}",
        "任务：给出一处最小替换，消除这条告警。",
        "你不能声称已经修好；过不过由后续扫描和测试决定。",
    ]
    from cleardebt.triage import is_secret_rule, problem_surface, rule_number

    number = rule_number(rule)
    if is_secret_rule(rule):
        lines.extend(
            [
                "这是密钥类告警：把硬编码的口令/令牌/密钥改成从环境变量或密钥管理读取。",
                "不要编造新的真实密钥；不要加 NOSONAR；不要把密钥写进注释。",
                "示例形态：process.env.NAME / os.environ[\"NAME\"] / Environment.GetEnvironmentVariable。",
            ]
        )
    elif number == "S1313":
        lines.append("把硬编码 IP 改成配置或环境变量读取，不要编造业务地址。")
    elif problem_surface(rule) == "reliability":
        lines.append("这是可靠性类告警：只做局部、语义等价的改写。")
    if evidence:
        if evidence.get("nearby"):
            lines.append("告警附近代码：")
            lines.append(evidence["nearby"])
        if evidence.get("expression"):
            lines.append(f"表达式：{evidence['expression']}")
        if evidence.get("name"):
            lines.append(f"名字：{evidence['name']}")
        if evidence.get("type"):
            lines.append(f"类型服务：{evidence['type']}")
        occurrences = evidence.get("occurrences") or []
        if occurrences:
            lines.append("相关行：")
            for item in occurrences[:12]:
                lines.append(f"第 {item.get('line')} 行：{item.get('text')}")
        if evidence.get("function_source") and evidence["function_source"] != source:
            lines.append("相关函数：")
            lines.append(evidence["function_source"])
    lines.append("完整源码：")
    lines.append(source)
    if examples:
        lines.append("以前同一条规则改过的片段：")
        for item in examples[:3]:
            lines.append(f"原来：{item['old_string']}")
            lines.append(f"改成：{item['new_string']}")
    lines.append("old_string 必须是上面源码里连续的原文，并且只出现一次。")
    lines.append("只输出 JSON：{\"old_string\":\"...\",\"new_string\":\"...\"}")
    return "\n".join(lines)


def build_prompt(evidence: dict, examples: list[dict] | None = None) -> str:
    """Kept for older S6679 tests."""
    return build_patch_prompt(
        rule="javascript:S6679",
        description=describe("javascript:S6679"),
        source=evidence.get("function_source") or "",
        path="",
        message="自己和自己用 == 比较",
        evidence=evidence,
        examples=examples,
    )


def _completions_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _file_token(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _remember(prompt: str, retrieve: bool, rule: str) -> None:
    path = ROOT / "var" / "b-prompt.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n--- rule={rule} retrieve={str(retrieve).lower()} ---\n")
        handle.write(prompt)
        handle.write("\n")
