"""Remove unused JavaScript or TypeScript imports (Sonar S1128).

tree-sitter finds the import bindings. A name counts as used only when it
appears as a real reference, not as a property like obj.readFile. Side-effect
imports (import "mod") are kept. The path picks the TypeScript grammar.
"""

from __future__ import annotations

from tree_sitter import Node

from cleardebt.grammar import parser_for

_USE_TYPES = {
    "identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
}


def remove_unused_imports(source: str, path: str = "") -> str:
    data = source.encode("utf-8")
    tree = parser_for(path).parse(data)
    if tree.root_node.has_error:
        raise ValueError("refusing to edit a file tree-sitter could not parse")

    imports = [node for node in tree.root_node.children if node.type == "import_statement"]
    spans = [(node.start_byte, node.end_byte) for node in imports]
    used = _used_names(tree.root_node, data, spans)

    ranges: list[tuple[int, int]] = []
    for statement in imports:
        bindings = _bindings(statement)
        if not bindings:
            continue
        unused = [item for item in bindings if item[0] not in used]
        if not unused:
            continue
        if len(unused) == len(bindings):
            ranges.append(_statement_span(data, statement.start_byte, statement.end_byte))
            continue
        ranges.extend(_partial_spans(data, statement, unused))

    return _apply(data, ranges).decode("utf-8")


def _bindings(statement: Node) -> list[tuple[str, Node, str]]:
    clause = next((child for child in statement.children if child.type == "import_clause"), None)
    if clause is None:
        return []
    found: list[tuple[str, Node, str]] = []
    for child in clause.children:
        if child.type == "identifier":
            found.append((_text(child), child, "default"))
        elif child.type == "namespace_import":
            local = [node for node in child.children if node.type == "identifier"][-1]
            found.append((_text(local), child, "namespace"))
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type != "import_specifier":
                    continue
                locals_ = [node for node in spec.children if node.type == "identifier"]
                found.append((_text(locals_[-1]), spec, "named"))
    return found


def _used_names(root: Node, source: bytes, import_spans: list[tuple[int, int]]) -> set[str]:
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if any(start <= node.start_byte and node.end_byte <= end for start, end in import_spans):
            continue
        if node.type in _USE_TYPES:
            names.add(source[node.start_byte : node.end_byte].decode("utf-8"))
        else:
            stack.extend(node.children)
    return names


def _partial_spans(source: bytes, statement: Node, unused: list[tuple[str, Node, str]]) -> list[tuple[int, int]]:
    named = [node for node in _named_imports(statement).children if node.type == "import_specifier"] if _named_imports(statement) else []
    unused_named = [node for _name, node, kind in unused if kind == "named"]
    ranges: list[tuple[int, int]] = []
    if named and len(unused_named) == len(named):
        group = _named_imports(statement)
        ranges.append((_comma_before(source, group.start_byte), group.end_byte))
    else:
        for _name, node, kind in unused:
            if kind == "named":
                ranges.append(_specifier_span(source, node))
    for _name, node, kind in unused:
        if kind == "default":
            ranges.append(_specifier_span(source, node))
        elif kind == "namespace":
            ranges.append((_comma_before(source, node.start_byte), node.end_byte))
    return ranges


def _named_imports(statement: Node) -> Node | None:
    clause = next((child for child in statement.children if child.type == "import_clause"), None)
    if clause is None:
        return None
    return next((child for child in clause.children if child.type == "named_imports"), None)


def _specifier_span(source: bytes, node: Node) -> tuple[int, int]:
    start, end = node.start_byte, node.end_byte
    index = end
    while index < len(source) and source[index] in b" \t":
        index += 1
    if index < len(source) and source[index] == ord(","):
        index += 1
        while index < len(source) and source[index] in b" \t":
            index += 1
        return start, index
    index = start
    while index > 0 and source[index - 1] in b" \t":
        index -= 1
    if index > 0 and source[index - 1] == ord(","):
        index -= 1
        while index > 0 and source[index - 1] in b" \t":
            index -= 1
        return index, end
    return start, end


def _comma_before(source: bytes, start: int) -> int:
    index = start
    while index > 0 and source[index - 1] in b" \t\n":
        index -= 1
    if index > 0 and source[index - 1] == ord(","):
        return index - 1
    return start


def _statement_span(source: bytes, start: int, end: int) -> tuple[int, int]:
    line_start = source.rfind(b"\n", 0, start) + 1
    newline = source.find(b"\n", end)
    line_limit = len(source) if newline == -1 else newline
    if source[line_start:start].strip() == b"" and source[end:line_limit].strip() == b"":
        start = line_start
        end = len(source) if newline == -1 else newline + 1
        if start == 0 and source[end : end + 1] == b"\n":
            end += 1
    return start, end


def _apply(source: bytes, ranges: list[tuple[int, int]]) -> bytes:
    for start, end in sorted(ranges, reverse=True):
        source = source[:start] + source[end:]
    return source


def _text(node: Node) -> str:
    return node.text.decode("utf-8")
