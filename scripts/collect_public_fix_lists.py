"""Build attributed snapshots of publicly documented fix eligibility.

Input files are saved official HTML pages. Pass --download to refresh them.
Each vendor's identifier namespace stays separate from Sonar.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CODEQL_LANGUAGES = (
    "actions", "c-cpp", "csharp", "go", "java-kotlin", "javascript-typescript",
    "python", "ruby", "rust", "swift",
)
BIOME_LANGUAGES = ("js", "css", "json", "graphql")
CODEQL_BASE = "https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-queries/"


def download_pages(input_dir: Path) -> None:
    """Fetch only the official pages licensed and listed in this snapshot."""
    urls = {f"cleardebt-codeql-{language}.html": CODEQL_BASE + language + "-built-in-queries"
            for language in CODEQL_LANGUAGES}
    urls.update({
        "cleardebt-gitlab-duo.html": "https://docs.gitlab.com/user/application_security/remediate/duo/",
        "cleardebt-ruff.html": "https://docs.astral.sh/ruff/rules/",
        "cleardebt-eslint.html": "https://eslint.org/docs/latest/rules/",
    })
    urls.update({f"cleardebt-biome-{language}.html": f"https://biomejs.dev/linter/{'javascript' if language == 'js' else language}/rules/"
                 for language in BIOME_LANGUAGES})
    input_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in urls.items():
        request = Request(url, headers={"User-Agent": "ClearDebt-public-rule-research/1.0"})
        with urlopen(request, timeout=45) as response:
            (input_dir / filename).write_bytes(response.read())


def _plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def codeql_rows(page: str, language: str) -> list[dict]:
    table = re.search(r"<table>.*?</table>", page, re.S)
    if not table or "Copilot Autofix" not in table.group(0):
        raise ValueError(f"CodeQL {language} 页面缺少 Copilot Autofix 表格")
    result = []
    for row in re.findall(r"<tr><th scope=\"row\">.*?</tr>", table.group(0), re.S):
        cells = re.findall(r"<td>(.*?)</td>", row, re.S)
        link = re.search(r'<a href="([^"]+)">(.+?)</a>', row, re.S)
        if len(cells) != 4 or not link:
            raise ValueError(f"CodeQL {language} 表格有无法识别的行")
        if 'aria-label="Included"' not in cells[3]:
            continue
        url = html.unescape(link.group(1))
        slug = urlparse(url).path.strip("/").removeprefix("codeql-query-help/")
        if not slug or "/" not in slug:
            raise ValueError(f"CodeQL {language} 规则链接无效：{url}")
        result.append({"key": slug, "name": _plain(link.group(2)), "url": url})
    return result


def gitlab_cwes(page: str) -> list[dict]:
    section = re.search(
        r"<h2 id=supported-vulnerabilities-for-vulnerability-resolution>.*?</h2>.*?<details>.*?<ul>(.*?)</ul>",
        page, re.S,
    )
    if not section:
        raise ValueError("GitLab 页面缺少 Vulnerability Resolution CWE 清单")
    keys = re.findall(r"<li>(CWE-[0-9]+):", section.group(1))
    if len(keys) != len(set(keys)) or len(keys) < 20:
        raise ValueError("GitLab CWE 清单不完整或存在重复")
    return [{"key": key} for key in keys]


def ruff_rows(page: str) -> list[dict]:
    result = []
    for row in re.findall(r"<tr>\s*<td class=\"rule-code\".*?</tr>", page, re.S):
        if "Automatic fix available" not in row:
            continue
        code = re.search(r'class="rule-code" id="([A-Z0-9]+)"', row)
        link = re.search(r'<a href="([^\"]+)/"><code>(.*?)</code></a>', row, re.S)
        if not code or not link:
            raise ValueError("Ruff 规则表有无法识别的可修行")
        result.append({"key": code.group(1), "name": _plain(link.group(2)),
                       "url": "https://docs.astral.sh/ruff/rules/" + link.group(1) + "/"})
    if len(result) < 100:
        raise ValueError("Ruff 可修规则数量异常")
    return result


def biome_rows(page: str, language: str) -> list[dict]:
    result = []
    for row in re.findall(r"<tr><td><a href=\"/linter/rules/.*?</tr>", page, re.S):
        link = re.search(r'<a href="(/linter/rules/[^"]+)">([^<]+)</a>', row)
        if not link:
            continue
        safe = "The rule has a safe fix" in row
        unsafe = "The rule has an unsafe fix" in row
        if safe or unsafe:
            result.append({"key": f"{language}/{link.group(2)}", "fix_safety": "safe" if safe else "unsafe",
                           "url": "https://biomejs.dev" + link.group(1)})
    if language == "js" and len(result) < 100:
        raise ValueError("Biome JavaScript 可修规则数量异常")
    return result


def eslint_rows(page: str) -> list[dict]:
    result = []
    for article in re.findall(r"<article class=\"rule[^\"]*\".*?</article>", page, re.S):
        link = re.search(r'<a href="(/docs/latest/rules/[^"]+)" class="rule__name">([^<]+)</a>', article)
        if not link:
            continue
        fix = re.search(r'<p class="rule__categories__type"([^>]*)>\s*🔧', article)
        if fix and 'aria-hidden="true"' not in fix.group(1):
            result.append({"key": link.group(2), "url": "https://eslint.org" + link.group(1)})
    if len(result) < 20:
        raise ValueError("ESLint 可修规则数量异常")
    return result


def collect(input_dir: Path, retrieved_on: str) -> dict:
    catalogs = []
    github_rules = []
    for language in CODEQL_LANGUAGES:
        github_rules.extend(codeql_rows((input_dir / f"cleardebt-codeql-{language}.html").read_text(encoding="utf-8"), language))
    if len(github_rules) != len({row["key"] for row in github_rules}):
        raise ValueError("CodeQL 查询帮助链接重复")
    catalogs.append({"source": "github_copilot_autofix", "fix_kind": "llm_eligibility",
                     "key_kind": "codeql_query_help_slug", "license": "CC-BY-4.0",
                     "source_url": CODEQL_BASE + "built-in-queries", "rules": sorted(github_rules, key=lambda row: row["key"])})
    catalogs.append({"source": "gitlab_duo_vulnerability_resolution", "fix_kind": "llm_eligibility",
                     "key_kind": "cwe", "license": "CC-BY-SA-4.0",
                     "source_url": "https://docs.gitlab.com/user/application_security/remediate/duo/",
                     "rules": gitlab_cwes((input_dir / "cleardebt-gitlab-duo.html").read_text(encoding="utf-8"))})
    catalogs.append({"source": "ruff", "fix_kind": "deterministic_autofix", "key_kind": "ruff_rule_code",
                     "license": "MIT", "source_url": "https://docs.astral.sh/ruff/rules/",
                     "rules": ruff_rows((input_dir / "cleardebt-ruff.html").read_text(encoding="utf-8"))})
    biome = []
    for language in BIOME_LANGUAGES:
        biome.extend(biome_rows((input_dir / f"cleardebt-biome-{language}.html").read_text(encoding="utf-8"), language))
    catalogs.append({"source": "biome", "fix_kind": "deterministic_autofix", "key_kind": "biome_language_rule",
                     "license": "MIT OR Apache-2.0", "source_url": "https://biomejs.dev/linter/",
                     "rules": sorted(biome, key=lambda row: row["key"])})
    catalogs.append({"source": "eslint_core", "fix_kind": "deterministic_autofix", "key_kind": "eslint_rule_name",
                     "license": "MIT", "source_url": "https://eslint.org/docs/latest/rules/",
                     "rules": eslint_rows((input_dir / "cleardebt-eslint.html").read_text(encoding="utf-8"))})
    return {"retrieved_on": retrieved_on, "note": "Vendor eligibility is not Sonar rule eligibility or a repair guarantee.",
            "catalogs": catalogs}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--download", action="store_true", help="refresh official HTML pages first")
    args = parser.parse_args()
    if args.download:
        download_pages(args.input_dir)
    data = collect(args.input_dir, args.date)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for catalog in data["catalogs"]:
        filename = f"{catalog['source']}-{args.date}.json"
        payload = {"retrieved_on": args.date, "note": data["note"], **catalog}
        (args.output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{catalog['source']}: {len(catalog['rules'])}")


if __name__ == "__main__":
    main()
