"""OpenAI-compatible native tool calling for one autonomous repair turn."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cleardebt.b_fix import llm_credentials, _completions_url


class AgentModelError(RuntimeError):
    pass


def choose_tool(messages: list[dict], tools: list[dict], *, model: str | None = None) -> dict:
    """Return the model's tool calls in order and the matching assistant message.

    A response without a tool call cannot advance a repair. Each call is then
    executed in its own graph step so its result is checkpointed.
    """
    credentials = llm_credentials()
    chosen = model or credentials["model"]
    tool_choice = os.environ.get("CLEARDEBT_AGENT_TOOL_CHOICE", "required").strip().lower()
    if tool_choice not in {"required", "auto"}:
        raise AgentModelError("CLEARDEBT_AGENT_TOOL_CHOICE 只能是 required 或 auto")
    body = {
        "model": chosen,
        "temperature": 0,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    # DeepSeek Chat Completions defaults to thinking mode, which rejects
    # tool_choice=required. Its non-thinking mode supports required tool calls.
    if urlsplit(credentials["base_url"]).hostname == "api.deepseek.com":
        body["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        _completions_url(credentials["base_url"]),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {credentials['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        raise AgentModelError(f"工具调用模型请求失败：{error}") from error
    try:
        choice = payload["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if not calls or len(calls) > 8:
            raise AgentModelError(
                f"模型每轮需选择 1–8 个工具；{chosen} 返回 {len(calls)} 个原生 tool_call"
                f"（finish_reason={choice.get('finish_reason') or '未知'}）"
            )
        parsed = []
        seen_ids = set()
        for call in calls:
            if call.get("type") != "function" or not call.get("id") or call["id"] in seen_ids:
                raise AgentModelError("模型返回了无效或重复的工具调用 ID")
            seen_ids.add(call["id"])
            function = call["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise AgentModelError("工具参数必须是 JSON 对象")
            parsed.append({"call_id": call["id"], "name": function["name"], "arguments": arguments})
        assistant = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        }
        if message.get("reasoning_content") is not None:
            assistant["reasoning_content"] = message["reasoning_content"]
        return {
            "assistant": assistant,
            **parsed[0],
            "pending_calls": parsed[1:],
            "model": chosen,
            "usage": payload.get("usage") or {},
        }
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise AgentModelError("模型返回的工具调用无法解析") from error
