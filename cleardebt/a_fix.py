"""Deterministic edits for mechanical rules. These do not call a model."""

from __future__ import annotations

from tree_sitter import Node

from cleardebt.grammar import parser_for
from cleardebt.triage import rule_number
from cleardebt.unused_import import remove_unused_imports

_USE_TYPES = {
    "identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
}
_LITERALS = {"number", "string", "true", "false", "null", "undefined"}
_EFFECT_TYPES = {
    "call_expression",
    "assignment_expression",
    "update_expression",
    "await_expression",
    "new_expression",
    "yield_expression",
}


def apply_mechanical(rule: str, source: str, path: str = "") -> str | None:
    fixer = {
        "S1128": remove_unused_imports,
        "S1481": remove_unused_locals,
        "S1854": collapse_overwritten_declarations,
        "S1656": remove_self_assignments,
        "S905": remove_useless_expressions,
        "S3923": collapse_identical_branches,
        "S1862": remove_duplicate_conditions,
        "S1871": remove_duplicate_conditions,
    }.get(rule_number(rule))
    if fixer is None:
        return None
    return fixer(source, path)


def remove_unused_locals(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = _parse(data, path)
    spans = []
    for node in _walk(tree.root_node):
        if node.type != "lexical_declaration":
            continue
        declarators = [child for child in node.children if child.type == "variable_declarator"]
        if len(declarators) != 1:
            continue
        declarator = declarators[0]
        name = declarator.child_by_field_name("name")
        value = declarator.child_by_field_name("value")
        if name is None or name.type != "identifier" or value is None or value.type not in _LITERALS:
            continue
        if _name_used(tree.root_node, data, _text(name), (node.start_byte, node.end_byte)):
            continue
        spans.append(_line_span(data, node.start_byte, node.end_byte))
    return _delete(data, spans).decode("utf-8")


def collapse_overwritten_declarations(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = _parse(data, path)
    inserts: list[tuple[int, bytes]] = []
    deletes: list[tuple[int, int]] = []
    for node in _walk(tree.root_node):
        if node.type != "statement_block":
            continue
        statements = [child for child in node.children if child.type not in {"{", "}", "comment"}]
        for current, nxt in zip(statements, statements[1:]):
            name = _let_binding(current)
            if name is None or not _is_plain_assignment(nxt, name):
                continue
            deletes.append(_line_span(data, current.start_byte, current.end_byte))
            left = _assignment(nxt).child_by_field_name("left")
            inserts.append((left.start_byte, b"let "))
    for start, text in sorted(inserts, reverse=True):
        data = data[:start] + text + data[start:]
        deletes = [(a + (len(text) if a >= start else 0), b + (len(text) if b >= start else 0)) for a, b in deletes]
    return _delete(data, deletes).decode("utf-8")


def remove_self_assignments(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = _parse(data, path)
    spans = []
    for node in _walk(tree.root_node):
        if node.type != "expression_statement":
            continue
        assignment = _assignment(node)
        if assignment is None:
            continue
        left = assignment.child_by_field_name("left")
        right = assignment.child_by_field_name("right")
        if left is None or right is None or left.type != "identifier" or right.type != "identifier":
            continue
        if _text(left) != _text(right):
            continue
        spans.append(_line_span(data, node.start_byte, node.end_byte))
    return _delete(data, spans).decode("utf-8")


def remove_useless_expressions(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = _parse(data, path)
    spans = []
    for node in _walk(tree.root_node):
        if node.type != "expression_statement":
            continue
        expression = next((child for child in node.children if child.type not in {";", "comment"}), None)
        if expression is None or expression.type == "string" or _has_effect(expression):
            continue
        spans.append(_line_span(data, node.start_byte, node.end_byte))
    return _delete(data, spans).decode("utf-8")


def collapse_identical_branches(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = _parse(data, path)
    replacements: list[tuple[int, int, bytes]] = []
    for node in _walk(tree.root_node):
        if node.type != "if_statement":
            continue
        alternative = node.child_by_field_name("alternative")
        consequence = node.child_by_field_name("consequence")
        condition = node.child_by_field_name("condition")
        if alternative is None or consequence is None or condition is None:
            continue
        else_body = _final_else_body(alternative)
        if else_body is None or else_body.text != consequence.text or _has_effect(condition):
            continue
        body = _body_text(consequence, b" " * node.start_point[1])
        if not body.strip():
            continue
        replacements.append((node.start_byte, node.end_byte, body))
    for start, end, text in _outermost(replacements):
        data = data[:start] + text + data[end:]
    return data.decode("utf-8")


def remove_duplicate_conditions(source: str, path: str = "") -> str:
    """Drop an else-if whose condition repeats the if above it.

    That branch is unreachable. A repeated body with a different condition is
    still live, so it is left alone.
    """
    data = source.encode("utf-8")
    tree = _parse(data, path)
    spans: list[tuple[int, int]] = []
    for node in _walk(tree.root_node):
        if node.type != "if_statement":
            continue
        alternative = node.child_by_field_name("alternative")
        if alternative is None:
            continue
        inner = next((child for child in alternative.children if child.type == "if_statement"), None)
        if inner is None or inner.child_by_field_name("alternative") is not None:
            continue
        if _condition_text(node) != _condition_text(inner):
            continue
        start = alternative.start_byte
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            while start > consequence.end_byte and data[start - 1] in b" \t":
                start -= 1
        spans.append((start, alternative.end_byte))
    return _delete(data, spans).decode("utf-8")


def _parse(data: bytes, path: str):
    tree = parser_for(path).parse(data)
    if tree.root_node.has_error:
        raise ValueError("refusing to edit a file tree-sitter could not parse")
    return tree


def _final_else_body(alternative: Node) -> Node | None:
    if alternative.type != "else_clause":
        return None
    body = next((child for child in alternative.children if child.type not in {"else", "comment"}), None)
    if body is None or body.type == "if_statement":
        return None
    return body


def _body_text(body: Node, indent: bytes) -> bytes:
    """Statements that replace an if. The if line already has `indent` in front of the keyword."""
    statements = [child for child in body.children if child.type not in {"{", "}"}] if body.type == "statement_block" else [body]
    chunks = []
    for index, statement in enumerate(statements):
        if index == 0:
            chunks.append(statement.text)
        else:
            chunks.append(b"\n" + indent + statement.text)
    return b"".join(chunks)


def _condition_text(node: Node) -> str | None:
    condition = node.child_by_field_name("condition")
    if condition is None:
        return None
    inner = [child for child in condition.children if child.type not in {"(", ")"}]
    target = inner[0] if len(inner) == 1 else condition
    return _text(target)


def _has_effect(node: Node) -> bool:
    for current in _walk(node):
        if current.type in _EFFECT_TYPES:
            return True
        if current.type == "unary_expression" and any(child.type == "delete" or _text(child) == "delete" for child in current.children):
            return True
    return False


def _outermost(spans: list[tuple[int, int, bytes]]) -> list[tuple[int, int, bytes]]:
    kept = []
    for start, end, text in spans:
        covered = any(
            other_start <= start and end <= other_end and (start, end) != (other_start, other_end)
            for other_start, other_end, _body in spans
        )
        if not covered:
            kept.append((start, end, text))
    kept.sort(key=lambda item: item[0], reverse=True)
    return kept


def _let_binding(node: Node) -> str | None:
    if node.type != "lexical_declaration":
        return None
    if not any(child.type == "let" for child in node.children):
        return None
    declarators = [child for child in node.children if child.type == "variable_declarator"]
    if len(declarators) != 1:
        return None
    name = declarators[0].child_by_field_name("name")
    if name is None or name.type != "identifier":
        return None
    return _text(name)


def _is_plain_assignment(node: Node, name: str) -> bool:
    assignment = _assignment(node)
    if assignment is None:
        return False
    left = assignment.child_by_field_name("left")
    equals = any(child.type == "=" or _text(child) == "=" for child in assignment.children)
    return left is not None and left.type == "identifier" and _text(left) == name and equals


def _assignment(node: Node) -> Node | None:
    if node.type == "assignment_expression":
        return node
    if node.type == "expression_statement":
        for child in node.children:
            if child.type == "assignment_expression":
                return child
    return None


def _name_used(root: Node, source: bytes, name: str, skip: tuple[int, int]) -> bool:
    start, end = skip
    for node in _walk(root):
        if node.type not in _USE_TYPES:
            continue
        if start <= node.start_byte and node.end_byte <= end:
            continue
        if source[node.start_byte : node.end_byte].decode("utf-8") == name:
            return True
    return False


def _line_span(source: bytes, start: int, end: int) -> tuple[int, int]:
    line_start = source.rfind(b"\n", 0, start) + 1
    newline = source.find(b"\n", end)
    line_limit = len(source) if newline == -1 else newline
    if source[line_start:start].strip() == b"" and source[end:line_limit].strip() == b"":
        start = line_start
        end = len(source) if newline == -1 else newline + 1
    return start, end


def _delete(source: bytes, spans: list[tuple[int, int]]) -> bytes:
    for start, end in sorted(spans, reverse=True):
        source = source[:start] + source[end:]
    return source


def _walk(node: Node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _text(node: Node) -> str:
    return node.text.decode("utf-8")
