"""SCA dependency remediation: bump packages per Sonar-suggested versions.

Supports npm/yarn (package.json + lock), pip (requirements*.txt),
Maven (pom.xml), and Gradle (build.gradle / .kts).

Gate: after the bump, the manifest (and lock when present) must show the
suggested version. Classic Sonar issue fingerprint rescan is not used for SCA.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCA_RULE = "sca:UPGRADE"

_ECOSYSTEMS = {
    "npm": ("package.json", "package-lock.json", "yarn.lock"),
    "pip": ("requirements.txt", "requirements.in", "Pipfile"),
    "maven": ("pom.xml",),
    "gradle": ("build.gradle", "build.gradle.kts"),
}

# "Upgrade foo from 1.0.0 to 1.2.3" / "Upgrade dependency bar to version 2.0.0"
_UPGRADE_RE = re.compile(
    r"(?i)upgrade(?:\s+dependency)?\s+[`'\"]?(?P<package>[\w@/.:-]+)[`'\"]?"
    r"(?:\s+from\s+[`'\"]?(?P<from>[\w.~+*-]+)[`'\"]?)?"
    r"\s+to(?:\s+version)?\s+[`'\"]?(?P<to>[\w.~+*-]+)[`'\"]?"
)
_PACKAGE_RE = re.compile(r"(?i)(?:package|dependency)\s+[`'\"]?(?P<package>[\w@/.:-]+)[`'\"]?")
_VERSION_RE = re.compile(r"(?i)(?:to|→|->)\s*(?:version\s+)?[`'\"]?(?P<to>[\w.~+*-]+)[`'\"]?")


def is_sca_rule(rule: str) -> bool:
    return (rule or "").strip().lower().startswith("sca:")


def fingerprint_risk(package: str, path: str, to_version: str, vuln: str = "") -> str:
    raw = f"sca\n{package}\n{path.replace(chr(92), '/')}\n{to_version}\n{vuln}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def detect_ecosystem(path: str) -> str:
    name = Path(path or "").name.lower()
    if name in {"package.json", "package-lock.json", "yarn.lock"}:
        return "npm"
    if name.startswith("requirements") or name in {"pipfile", "pyproject.toml"}:
        return "pip"
    if name == "pom.xml":
        return "maven"
    if name.startswith("build.gradle"):
        return "gradle"
    return ""


def parse_risk(message: str, path: str = "", *, package: str = "", to_version: str = "") -> dict:
    """Extract package + suggested version from a Sonar risk message or explicit fields."""
    text = message or ""
    pkg = (package or "").strip()
    target = (to_version or "").strip()
    current = ""
    match = _UPGRADE_RE.search(text)
    if match:
        pkg = pkg or match.group("package")
        current = match.group("from") or ""
        target = target or match.group("to")
    if not pkg:
        found = _PACKAGE_RE.search(text)
        if found:
            pkg = found.group("package")
    if not target:
        found = _VERSION_RE.search(text)
        if found:
            target = found.group("to")
    ecosystem = detect_ecosystem(path)
    if not ecosystem and path:
        ecosystem = "npm" if path.endswith(".json") else ""
    if not pkg or not target:
        raise ValueError("依赖风险里缺少包名或建议版本，升不了。")
    return {
        "package": pkg,
        "from_version": current,
        "to_version": target,
        "path": path,
        "ecosystem": ecosystem or detect_ecosystem(path) or "npm",
        "message": text,
    }


def apply_bump(work: Path, risk: dict) -> dict:
    """Rewrite manifest (and lock when present). Returns before/after of primary path."""
    ecosystem = risk.get("ecosystem") or detect_ecosystem(risk.get("path") or "")
    package = risk["package"]
    to_version = risk["to_version"]
    primary = _primary_path(work, risk.get("path") or "", ecosystem)
    tracked = [primary]
    if ecosystem == "npm":
        tracked.extend(path for path in (work / "package-lock.json", work / "yarn.lock") if path.is_file())
    before_files = {
        str(path.relative_to(work)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in tracked
        if path.is_file()
    }
    before = primary.read_text(encoding="utf-8") if primary.is_file() else ""
    if ecosystem == "npm":
        after = bump_npm(work, package, to_version, primary)
    elif ecosystem == "pip":
        after = bump_pip(primary, package, to_version)
    elif ecosystem == "maven":
        after = bump_maven(primary, package, to_version)
    elif ecosystem == "gradle":
        after = bump_gradle(primary, package, to_version)
    else:
        raise ValueError(f"还不支持这种依赖清单：{ecosystem or primary.name}")
    changed_files = []
    for path in tracked:
        relative = str(path.relative_to(work)).replace("\\", "/")
        after_text = path.read_text(encoding="utf-8") if path.is_file() else ""
        before_text = before_files.get(relative, "")
        if after_text != before_text:
            changed_files.append({"path": relative, "before": before_text, "after": after_text})
    return {
        "path": str(primary.relative_to(work)).replace("\\", "/"),
        "before": before,
        "after": after,
        "ecosystem": ecosystem,
        "package": package,
        "to_version": to_version,
        "changed_files": changed_files,
    }


def verify_bump(work: Path, risk: dict) -> dict:
    """Gate: suggested version must appear for the package in the dependency file(s)."""
    ecosystem = risk.get("ecosystem") or detect_ecosystem(risk.get("path") or "")
    package = risk["package"]
    to_version = risk["to_version"]
    primary = _primary_path(work, risk.get("path") or "", ecosystem)
    if not primary.is_file():
        return {"ok": False, "reason": f"找不到依赖文件 {primary.name}。"}
    text = primary.read_text(encoding="utf-8")
    if not _version_present(text, package, to_version, ecosystem):
        return {"ok": False, "reason": f"{package} 还没有升到 {to_version}。"}
    if ecosystem == "npm":
        lock = work / "package-lock.json"
        yarn = work / "yarn.lock"
        if lock.is_file() and not _npm_lock_has(lock.read_text(encoding="utf-8"), package, to_version):
            # yarn-only repos may only have yarn.lock
            if not yarn.is_file():
                return {"ok": False, "reason": f"package-lock.json 里 {package} 还不是 {to_version}。"}
        if yarn.is_file() and not _yarn_lock_has(yarn.read_text(encoding="utf-8"), package, to_version):
            if not lock.is_file():
                return {"ok": False, "reason": f"yarn.lock 里 {package} 还不是 {to_version}。"}
    return {"ok": True, "reason": f"{package} → {to_version}", "path": str(primary.relative_to(work))}


def fetch_dependency_risks(host: str, token: str, project_key: str) -> list[dict]:
    """Prefer Sonar SCA API; fall back to vulnerability issues that look like upgrades."""
    rows = _fetch_sca_api(host, token, project_key)
    if rows is not None:
        return rows
    return _fetch_vulnerability_issues(host, token, project_key)


def bump_npm(work: Path, package: str, to_version: str, package_json: Path) -> str:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    changed = False
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        block = data.get(section) or {}
        if package in block:
            block[package] = _npm_range(block[package], to_version)
            data[section] = block
            changed = True
    if not changed:
        # Direct dependency missing: still pin under dependencies for remediation MR.
        data.setdefault("dependencies", {})[package] = to_version
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    package_json.write_text(text, encoding="utf-8")
    lock = work / "package-lock.json"
    if lock.is_file():
        lock.write_text(_bump_npm_lock(lock.read_text(encoding="utf-8"), package, to_version), encoding="utf-8")
    yarn = work / "yarn.lock"
    if yarn.is_file():
        yarn.write_text(_bump_yarn_lock(yarn.read_text(encoding="utf-8"), package, to_version), encoding="utf-8")
    return text


def bump_pip(requirements: Path, package: str, to_version: str) -> str:
    lines = requirements.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"(?i)^\s*{re.escape(package)}\s*([=<>!~].*)?$")
    out = []
    found = False
    for line in lines:
        if pattern.match(line.strip()):
            out.append(f"{package}=={to_version}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{package}=={to_version}")
    text = "\n".join(out) + ("\n" if out else "")
    requirements.write_text(text, encoding="utf-8")
    return text


def bump_maven(pom: Path, package: str, to_version: str) -> str:
    """package is groupId:artifactId or just artifactId."""
    text = pom.read_text(encoding="utf-8")
    group, artifact = _maven_coords(package)
    if group:
        block = re.compile(
            rf"(<dependency>\s*<groupId>\s*{re.escape(group)}\s*</groupId>\s*"
            rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>\s*)"
            rf"<version>[^<]*</version>",
            re.IGNORECASE | re.DOTALL,
        )
        updated, n = block.subn(rf"\1<version>{to_version}</version>", text, count=1)
    else:
        block = re.compile(
            rf"(<artifactId>\s*{re.escape(artifact)}\s*</artifactId>\s*)<version>[^<]*</version>",
            re.IGNORECASE | re.DOTALL,
        )
        updated, n = block.subn(rf"\1<version>{to_version}</version>", text, count=1)
    if n == 0:
        raise ValueError(f"pom.xml 里找不到 {package}。")
    pom.write_text(updated, encoding="utf-8")
    return updated


def bump_gradle(build: Path, package: str, to_version: str) -> str:
    text = build.read_text(encoding="utf-8")
    # "group:name:1.0.0" or "group:name:1.0.+"
    coord = package if ":" in package else None
    if coord and coord.count(":") >= 1:
        parts = coord.split(":")
        group, name = parts[0], parts[1]
        pattern = re.compile(
            rf"(['\"]{re.escape(group)}:{re.escape(name)}:)([^'\"]+)(['\"])"
        )
        updated, n = pattern.subn(rf"\g<1>{to_version}\g<3>", text, count=1)
        if n:
            build.write_text(updated, encoding="utf-8")
            return updated
    # short name in implementation 'foo:1.0.0'
    short = package.split(":")[-1]
    pattern = re.compile(rf"(['\"][^'\"]*{re.escape(short)}:)([^'\"]+)(['\"])")
    updated, n = pattern.subn(rf"\g<1>{to_version}\g<3>", text, count=1)
    if n == 0:
        raise ValueError(f"Gradle 文件里找不到 {package}。")
    build.write_text(updated, encoding="utf-8")
    return updated


def _primary_path(work: Path, path: str, ecosystem: str) -> Path:
    if path:
        candidate = work / path
        if candidate.is_file():
            return candidate
    names = _ECOSYSTEMS.get(ecosystem) or ()
    for name in names:
        candidate = work / name
        if candidate.is_file():
            return candidate
    if path:
        return work / path
    raise ValueError("仓库里没有对应的依赖清单文件。")


def _npm_range(existing: str, to_version: str) -> str:
    text = (existing or "").strip()
    if text.startswith("^"):
        return f"^{to_version}"
    if text.startswith("~"):
        return f"~{to_version}"
    return to_version


def _bump_npm_lock(text: str, package: str, to_version: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    packages = data.get("packages") or {}
    for key, meta in list(packages.items()):
        name = meta.get("name") or key.rsplit("node_modules/", 1)[-1]
        if name == package or key.endswith(f"node_modules/{package}"):
            meta["version"] = to_version
            packages[key] = meta
    deps = data.get("dependencies") or {}
    if package in deps and isinstance(deps[package], dict):
        deps[package]["version"] = to_version
    data["packages"] = packages
    data["dependencies"] = deps
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _bump_yarn_lock(text: str, package: str, to_version: str) -> str:
    # Minimal: rewrite version: lines under blocks that mention the package name.
    lines = text.splitlines()
    out = []
    in_block = False
    for line in lines:
        if not line.startswith(" ") and not line.startswith("#") and line.strip():
            in_block = package in line.split("@")[0] or f"\"{package}@" in line or line.startswith(f"{package}@")
        if in_block and re.match(r"\s+version\s+", line):
            out.append(re.sub(r'(version\s+")([^"]+)(")', rf'\1{to_version}\3', line))
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _version_present(text: str, package: str, to_version: str, ecosystem: str) -> bool:
    if ecosystem == "npm":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return to_version in text and package in text
        for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            block = data.get(section) or {}
            if package in block and to_version in str(block[package]):
                return True
        return False
    if ecosystem == "pip":
        return bool(re.search(rf"(?im)^\s*{re.escape(package)}\s*==\s*{re.escape(to_version)}\s*$", text))
    if ecosystem == "maven":
        artifact = package.split(":")[-1]
        return bool(
            re.search(
                rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>\s*<version>\s*{re.escape(to_version)}\s*</version>",
                text,
                re.IGNORECASE | re.DOTALL,
            )
        )
    if ecosystem == "gradle":
        return to_version in text and package.split(":")[-1] in text
    return to_version in text


def _npm_lock_has(text: str, package: str, to_version: str) -> bool:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    for key, meta in (data.get("packages") or {}).items():
        name = meta.get("name") or key.rsplit("node_modules/", 1)[-1]
        if (name == package or key.endswith(f"node_modules/{package}")) and meta.get("version") == to_version:
            return True
    dep = (data.get("dependencies") or {}).get(package) or {}
    return isinstance(dep, dict) and dep.get("version") == to_version


def _yarn_lock_has(text: str, package: str, to_version: str) -> bool:
    return bool(re.search(rf"(?m)^\"?{re.escape(package)}@.+\n\s+version\s+\"{re.escape(to_version)}\"", text))


def _maven_coords(package: str) -> tuple[str, str]:
    if ":" in package:
        group, artifact = package.split(":", 1)
        return group, artifact.split(":")[0]
    return "", package


def _fetch_sca_api(host: str, token: str, project_key: str) -> list[dict] | None:
    query = urllib.parse.urlencode({"projectKey": project_key, "ps": 500})
    url = f"{host.rstrip('/')}/api/v2/sca/issues-releases?{query}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in {404, 401, 403, 501}:
            return None
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    items = payload.get("issuesReleases") or payload.get("issues") or payload.get("releases") or []
    if not isinstance(items, list):
        return None
    rows = []
    for item in items:
        package = item.get("packageName") or item.get("package") or ""
        to_version = ""
        recommendation = item.get("recommendation") or {}
        versions = recommendation.get("fixVersions") or item.get("fixVersions") or []
        if versions:
            to_version = str(versions[0])
        paths = item.get("dependencyFilePaths") or item.get("paths") or []
        path = paths[0] if paths else _guess_path(package, item.get("packageManager") or "")
        if not package or not to_version:
            continue
        message = f"Upgrade {package} to version {to_version}"
        rows.append(
            {
                "repo": project_key,
                "rule": SCA_RULE,
                "path": path,
                "message": message,
                "message_zh": f"按建议升依赖版本（{package} → {to_version}）",
                "package": package,
                "to_version": to_version,
                "ecosystem": _manager_to_ecosystem(item.get("packageManager") or detect_ecosystem(path)),
                "eligible": True,
                "sonar_key": item.get("key") or "",
                "fingerprint": fingerprint_risk(package, path, to_version, str(item.get("vulnerabilityId") or "")),
            }
        )
    return rows


def _fetch_vulnerability_issues(host: str, token: str, project_key: str) -> list[dict]:
    from list_issues import fetch_issues, issue_path

    rows = []
    for issue in fetch_issues(host, token, project_key):
        message = issue.get("message") or ""
        if not _UPGRADE_RE.search(message) and "upgrade" not in message.lower():
            continue
        path = issue_path(issue.get("component", ""), project_key)
        try:
            risk = parse_risk(message, path)
        except ValueError:
            continue
        rows.append(
            {
                "repo": project_key,
                "rule": SCA_RULE,
                "path": path or _guess_path(risk["package"], risk["ecosystem"]),
                "message": message,
                "message_zh": f"按建议升依赖版本（{risk['package']} → {risk['to_version']}）",
                "package": risk["package"],
                "to_version": risk["to_version"],
                "ecosystem": risk["ecosystem"],
                "eligible": True,
                "sonar_key": issue.get("key") or "",
                "fingerprint": fingerprint_risk(risk["package"], path, risk["to_version"]),
            }
        )
    return rows


def _guess_path(package: str, manager: str) -> str:
    eco = _manager_to_ecosystem(manager)
    if eco == "pip":
        return "requirements.txt"
    if eco == "maven":
        return "pom.xml"
    if eco == "gradle":
        return "build.gradle"
    return "package.json"


def _manager_to_ecosystem(manager: str) -> str:
    text = (manager or "").lower()
    if text in {"npm", "yarn", "pnpm"}:
        return "npm"
    if text in {"pip", "pypi", "poetry"}:
        return "pip"
    if text in {"maven"}:
        return "maven"
    if text in {"gradle"}:
        return "gradle"
    return text if text in _ECOSYSTEMS else ""
