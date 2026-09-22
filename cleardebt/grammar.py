"""Tree-sitter parsers for JavaScript and TypeScript files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript


@lru_cache(maxsize=4)
def parser_for(path: str = "") -> Parser:
    suffix = Path(path).suffix.lower()
    if suffix == ".tsx":
        language = tstypescript.language_tsx()
    elif suffix == ".ts":
        language = tstypescript.language_typescript()
    else:
        language = tsjavascript.language()
    return Parser(Language(language))
