"""Evidence for one LLM edit. The model does not see the whole repository."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tree_sitter import Node

from cleardebt.grammar import parser_for
from cleardebt.languages import language_of
from cleardebt.triage import rule_number

ROOT = Path(__file__).resolve().parents[1]
TYPESCRIPT = ROOT / "deploy" / "typescript" / "node_modules" / "typescript"
TYPE_AT = ROOT / "cleardebt" / "type_at.mjs"
NEARBY_RADIUS = 8


def collect(
    rule: str,
    source: str,
    path: str = "",
    *,
    message: str = "",
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Default pre-model evidence: rule context, nearby lines, related symbols.

    S6679 (JS/TS) still uses the richer collector with the TypeScript language service.
    """
    number = rule_number(rule)
    lang = language_of(rule)
    if number == "S6679" and lang in {"javascript", "typescript"}:
        try:
            return collect_s6679(source, path)
        except (ValueError, RuntimeError):
            # Fall back to the generic window so one missing type service does not block the call.
            pass

    start = int(start_line) if start_line else None
    end = int(end_line) if end_line else start
    nearby = _nearby_window(source, start, end)
    evidence: dict = {
        "start_line": start,
        "end_line": end,
        "nearby": nearby,
    }
    name = _guess_name(message, nearby)
    if name:
        evidence["name"] = name
        evidence["occurrences"] = _occurrences(source, name)
    return evidence


def collect_s6679(source: str, path: str = "") -> dict:
    tree = parser_for(path or "snippet.js").parse(source.encode("utf-8"))
    match = _nan_comparison(tree.root_node)
    if match is None:
        raise ValueError("文件里没有自己和自己比较的表达式")
    expression, name, line, column = match
    function = _enclosing_function(expression)
    return {
        "expression": _text(expression),
        "name": name,
        "line": line,
        "column": column,
        "function_source": _text(function) if function is not None else _text(expression),
        "occurrences": _occurrences(source, name),
        "type": _lookup_type(source, line, column, path),
        "nearby": _nearby_window(source, line, line),
    }


def _nearby_window(source: str, start: int | None, end: int | None, radius: int = NEARBY_RADIUS) -> str:
    lines = source.splitlines()
    if not lines or not start:
        return ""
    lo = max(1, start - radius)
    hi = min(len(lines), (end or start) + radius)
    return "\n".join(f"{index}|{lines[index - 1]}" for index in range(lo, hi + 1))


def _guess_name(message: str, nearby: str) -> str | None:
    quoted = re.findall(r"['\"`]([^'\"`]{1,64})['\"`]", message or "")
    for item in quoted:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", item):
            return item
    for line in (nearby or "").splitlines():
        text = line.split("|", 1)[-1] if "|" in line else line
        match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", text)
        if match:
            return match.group(1)
    return None


def _nan_comparison(root: Node) -> tuple[Node, str, int, int] | None:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "binary_expression":
            operator = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if (
                operator is not None
                and _text(operator) == "=="
                and left is not None
                and right is not None
                and left.type == "identifier"
                and right.type == "identifier"
                and _text(left) == _text(right)
            ):
                return node, _text(left), left.start_point[0] + 1, left.start_point[1] + 1
        stack.extend(node.children)
    return None


def _enclosing_function(node: Node) -> Node | None:
    current = node
    while current is not None and current.type != "function_declaration":
        current = current.parent
    return current


def _occurrences(source: str, name: str) -> list[dict]:
    found = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if name in line:
            found.append({"line": line_number, "text": line.strip()})
    return found


def _lookup_type(source: str, line: int, column: int, path: str) -> str | None:
    if not TYPESCRIPT.exists():
        raise RuntimeError("TypeScript 语言服务还没装")
    suffix = Path(path).suffix.lower()
    if suffix not in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
        suffix = ".js"
    snippet = Path(f"/tmp/cleardebt-s6679{suffix}")
    snippet.write_text(source, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(TYPE_AT), str(TYPESCRIPT), str(snippet), str(line), str(column)],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "类型服务没有返回结果")
    payload = json.loads(completed.stdout)
    return payload.get("display")


def _text(node: Node) -> str:
    return node.text.decode("utf-8")
