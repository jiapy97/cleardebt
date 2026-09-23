"""Reject patches that hide a Sonar issue instead of fixing it.

Three checks: a new suppression comment, any edit to a test file, and a
function body that was emptied.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from tree_sitter import Node

from cleardebt.grammar import parser_for
from cleardebt.languages import is_js_ts_path, is_test_path

_SUPPRESSION = re.compile(
    r"NOSONAR|eslint-disable|pragma:\s*no cover|#\s*noqa|@SuppressWarnings",
    re.IGNORECASE,
)


def review_patch(files: list[tuple[str, str, str]]) -> list[dict]:
    """Each file is (path, before, after). Unchanged files are ignored."""
    rejections = []
    for path, before, after in files:
        if before == after:
            continue
        if _added_suppression(before, after):
            rejections.append(
                {
                    "kind": "suppression",
                    "path": path,
                    "reason": "加了抑制注释（NOSONAR 或 eslint-disable），告警被藏起来了，不是修好。",
                }
            )
        if _is_test_path(path):
            rejections.append(
                {
                    "kind": "test_file",
                    "path": path,
                    "reason": "改了测试文件。不能靠改测试来算通过。",
                }
            )
        for name in _emptied_functions(before, after, path):
            rejections.append(
                {
                    "kind": "emptied_function",
                    "path": path,
                    "function": name,
                    "reason": f"把函数 {name} 掏空了。告警是跟着代码一起删掉的，不是修好。",
                }
            )
    return rejections


def _added_suppression(before: str, after: str) -> bool:
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag not in {"replace", "insert"}:
            continue
        for line in after.splitlines()[j1:j2]:
            if _SUPPRESSION.search(line):
                return True
    return False


def _is_test_path(path: str) -> bool:
    return is_test_path(path)


def _emptied_functions(before: str, after: str, path: str) -> list[str]:
    if not is_js_ts_path(path):
        return []
    before_bodies = _function_emptiness(before, path)
    after_bodies = _function_emptiness(after, path)
    emptied = []
    for name, was_empty in before_bodies.items():
        if not was_empty and after_bodies.get(name) is True:
            emptied.append(name)
    return emptied


def _function_emptiness(source: str, path: str) -> dict[str, bool]:
    tree = parser_for(path).parse(source.encode("utf-8"))
    if tree.root_node.has_error:
        return {}
    found: dict[str, bool] = {}
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        name = _function_name(node)
        if name is not None:
            found[name] = _empty_body(node)
        stack.extend(node.children)
    return found


def _function_name(node: Node) -> str | None:
    if node.type == "function_declaration":
        name = node.child_by_field_name("name")
        if name is not None:
            return name.text.decode("utf-8")
    if node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is not None and value is not None and value.type in {"arrow_function", "function"}:
            return name.text.decode("utf-8")
    if node.type == "method_definition":
        name = node.child_by_field_name("name")
        if name is not None and name.type == "property_identifier":
            return name.text.decode("utf-8")
    return None


def _empty_body(node: Node) -> bool:
    body = node.child_by_field_name("body")
    if body is None or body.type != "statement_block":
        return False
    statements = [child for child in body.children if child.type not in {"{", "}", "comment"}]
    if not statements:
        return True
    if len(statements) == 1 and statements[0].type == "return_statement":
        text = "".join(statements[0].text.decode("utf-8").split())
        return text in {"return;", "returnundefined;"}
    return False
