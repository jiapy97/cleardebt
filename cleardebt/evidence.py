"""Evidence for one B-tier edit. The model does not see the whole repository."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tree_sitter import Node

from cleardebt.grammar import parser_for

ROOT = Path(__file__).resolve().parents[1]
TYPESCRIPT = ROOT / "deploy" / "typescript" / "node_modules" / "typescript"
TYPE_AT = ROOT / "cleardebt" / "type_at.mjs"


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
    }


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
