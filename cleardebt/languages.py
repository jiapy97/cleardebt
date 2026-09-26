"""Supported Sonar languages and repo layout helpers.

Rule numbers stay shared across languages (python:S1128 == javascript:S1128).
LLM patches are language-agnostic; this module gates which prefixes we accept
and how test/rescan behave outside the Node stack.
"""

from __future__ import annotations

from pathlib import Path

# Sonar rule key prefixes we will attempt to repair.
SUPPORTED_LANGUAGES = frozenset(
    {"javascript", "typescript", "python", "java", "csharp", "csharpsquid", "secrets", "sca"}
)

_JS_TS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")

_TEST_SUFFIXES = (
    ".test.js",
    ".test.jsx",
    ".test.ts",
    ".test.tsx",
    ".spec.js",
    ".spec.jsx",
    ".spec.ts",
    ".spec.tsx",
)

# Broad exclusions for temporary Sonar rescans (all four languages).
TEST_EXCLUSIONS = ",".join(
    [
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.test.jsx",
        "**/*.test.tsx",
        "**/*.spec.js",
        "**/*.spec.ts",
        "**/*.spec.jsx",
        "**/*.spec.tsx",
        "**/__tests__/**",
        "**/node_modules/**",
        "**/coverage/**",
        "**/test_*.py",
        "**/*_test.py",
        "**/tests/**",
        "**/*Test.java",
        "**/*Tests.java",
        "**/src/test/**",
        "**/*Test.cs",
        "**/*Tests.cs",
        "**/bin/**",
        "**/obj/**",
        "**/target/**",
        "**/.venv/**",
        "**/venv/**",
    ]
)


def language_of(rule: str) -> str:
    text = (rule or "").strip()
    if ":" not in text:
        return ""
    return text.split(":", 1)[0].lower()


def language_supported(rule: str) -> bool:
    lang = language_of(rule)
    if not lang:
        return False
    return lang in SUPPORTED_LANGUAGES


def is_js_ts_path(path: str) -> bool:
    name = Path(path or "").name.lower()
    return name.endswith(_JS_TS_SUFFIXES)


def is_test_path(path: str) -> bool:
    text = (path or "").replace("\\", "/")
    parts = Path(text).parts
    name = Path(text).name
    lower = name.lower()
    if name.endswith(_TEST_SUFFIXES):
        return True
    if "__tests__" in parts:
        return True
    if lower.startswith("test_") and lower.endswith(".py"):
        return True
    if lower.endswith("_test.py"):
        return True
    if lower.endswith("test.java") or lower.endswith("tests.java"):
        return True
    if lower.endswith("test.cs") or lower.endswith("tests.cs"):
        return True
    normalized = "/" + text.lower().strip("/") + "/"
    if "/src/test/" in normalized or "/tests/" in normalized:
        return True
    return False


def has_node_test_stack(work: Path) -> bool:
    """Vitest/npm coverage gate only applies when the repo already has a Node lockfile."""
    root = Path(work)
    return (root / "package-lock.json").is_file() and (root / "package.json").is_file()


def sources_covering(value: str, path: str) -> str:
    """Add the issue's own file when the chosen sources would miss it.

    A rescan that never reads the file reports its issue as gone, which is a
    false fix (hard-coded secrets often sit in root config files).
    """
    target = (path or "").strip()
    while target.startswith("./"):
        target = target[2:]
    if not target:
        return value
    for source in value.split(","):
        source = source.strip().rstrip("/")
        if source in {"", "."} or target == source or target.startswith(source + "/"):
            return value
    return f"{value},{target}"


def sonar_sources_value(work: Path) -> str:
    """Pick a sonar.sources value that works for JS/TS, Python, Java, and C# layouts."""
    root = Path(work)
    props = root / "sonar-project.properties"
    if props.is_file():
        for line in props.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("sonar.sources="):
                value = stripped.split("=", 1)[1].strip()
                if value:
                    return value
    for candidate in ("src", "lib", "app", "Source", "Sources"):
        if (root / candidate).is_dir():
            return candidate
    return "."
