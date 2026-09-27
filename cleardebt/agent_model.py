"""OpenAI-compatible native tool calling for one autonomous repair turn."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cleardebt.b_fix import llm_credentials, _completions_url


class AgentModelError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, usage_tokens: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.usage_tokens = usage_tokens


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
    used_tokens = 0
    for attempt in range(2):
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
            raise AgentModelError(f"工具调用模型请求失败：{error}", usage_tokens=used_tokens) from error
        try:
            result = _parse_tool_response(payload, chosen)
        except AgentModelError as error:
            used_tokens += error.usage_tokens
            if attempt == 0 and error.retryable:
                body["messages"] = [*messages, {"role": "user", "content": (
                    "上一条回复没有可执行的原生工具调用。请只选择已提供的工具，"
                    "把参数写成完整的 JSON 对象，并尽量缩短替换片段。"
                )}]
                continue
            raise AgentModelError(str(error), usage_tokens=used_tokens) from error
        usage = result.get("usage") or {}
        result["usage"] = {**usage, "total_tokens": used_tokens + int(usage.get("total_tokens") or 0)}
        return result
    raise AgentModelError("模型连续两次未返回有效工具调用", usage_tokens=used_tokens)


def _parse_tool_response(payload: dict, chosen: str) -> dict:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    tokens = int((usage or {}).get("total_tokens") or 0) if isinstance(usage, dict) else 0
    try:
        choice = payload["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError("message")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
            raise AgentModelError(
                f"模型未返回有效工具列表（finish_reason={choice.get('finish_reason') or '未知'}）",
                retryable=True, usage_tokens=tokens,
            )
        parsed = []
        seen_ids = set()
        for call in calls:
            if not isinstance(call, dict) or call.get("type") != "function" or not call.get("id") or call["id"] in seen_ids:
                raise AgentModelError("模型返回了无效或重复的工具调用 ID", retryable=True, usage_tokens=tokens)
            seen_ids.add(call["id"])
            function = call.get("function")
            if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"]:
                raise AgentModelError("模型返回的工具名称缺失", retryable=True, usage_tokens=tokens)
            raw_arguments = function.get("arguments")
            if not isinstance(raw_arguments, str):
                raise AgentModelError("模型返回的工具参数不是 JSON 字符串", retryable=True, usage_tokens=tokens)
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as error:
                raise AgentModelError("模型返回的工具参数不是完整 JSON", retryable=True, usage_tokens=tokens) from error
            if not isinstance(arguments, dict):
                raise AgentModelError("工具参数必须是 JSON 对象", retryable=True, usage_tokens=tokens)
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
    except (KeyError, IndexError, TypeError) as error:
        raise AgentModelError(
            f"模型响应缺少工具调用字段（{type(error).__name__}）",
            retryable=True, usage_tokens=tokens,
        ) from error
