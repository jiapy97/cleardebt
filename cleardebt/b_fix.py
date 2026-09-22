"""Ask the model for one replacement. It does not decide that the issue is fixed."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "deploy" / "deepseek" / ".token"


class ModelOutputError(ValueError):
    pass


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


def propose_s6679(evidence: dict, examples: list[dict] | None = None) -> tuple[str, str]:
    token = os.environ.get("DEEPSEEK_API_KEY") or TOKEN_FILE.read_text(encoding="utf-8").strip()
    chosen = examples or []
    prompt = build_prompt(evidence, chosen)
    _remember(prompt, bool(chosen))
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(
            {
                "model": "deepseek-chat",
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你只输出一个 JSON 对象，键只能是 old_string 和 new_string。"
                            "不要解释，不要说已经修好。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return parse_replacement(content)


def build_prompt(evidence: dict, examples: list[dict] | None = None) -> str:
    occurrences = "\n".join(
        f"第 {item['line']} 行：{item['text']}" for item in evidence["occurrences"]
    )
    lines = [
        "规则：自己和自己用 == 比较，是在判断 NaN。应改成 Number.isNaN(那个名字)。",
        f"表达式：{evidence['expression']}",
        f"名字：{evidence['name']}",
        f"类型服务：{evidence['type'] or '没有类型'}",
        "这个名字在函数里出现的位置：",
        occurrences,
        "函数源码：",
        evidence["function_source"],
    ]
    if examples:
        lines.append("以前同一条规则改过的片段：")
        for item in examples[:3]:
            lines.append(f"原来：{item['old_string']}")
            lines.append(f"改成：{item['new_string']}")
    lines.append("old_string 必须是函数源码里连续的原文，并且只出现一次。")
    return "\n".join(lines)


def _remember(prompt: str, retrieve: bool) -> None:
    path = ROOT / "var" / "b-prompt.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n--- retrieve={str(retrieve).lower()} ---\n")
        handle.write(prompt)
        handle.write("\n")
