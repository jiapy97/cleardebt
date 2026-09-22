#!/usr/bin/env python3
"""Rescan fixed code under a temporary Sonar project, then delete that project.

Never submits a report to the baseline project. A second scan of the same
project key would replace its last main-branch analysis.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.rescan import verdict
from list_issues import fetch_issues, fingerprint, issue_path, line_span, load_token

BASELINE_KEY = "toy-js"
PROTECTED_KEYS = {"toy-js", "toy-ts"}
TEMP_PREFIX = "toy-js-rescan-"
FIXED_RULE = "javascript:S1128"
SOURCES = ROOT / "fixtures" / "toy-js"


def main() -> int:
    host = "http://localhost:9000"
    token = load_token(None)
    baseline_stamp = analysis_date(host, token, BASELINE_KEY)
    temp_key = TEMP_PREFIX + uuid.uuid4().hex[:12]
    if temp_key == BASELINE_KEY or not temp_key.startswith(TEMP_PREFIX):
        raise SystemExit(f"refusing unsafe project key {temp_key}")

    try:
        scan_temp_project(temp_key, token)
        wait_until_processed(host, token, temp_key)
        before = issue_rows(host, token, BASELINE_KEY)
        after = issue_rows(host, token, temp_key)
        result = verdict(before, after, FIXED_RULE)
    finally:
        delete_temp_project(host, token, temp_key)

    if analysis_date(host, token, BASELINE_KEY) != baseline_stamp:
        raise SystemExit(f"{BASELINE_KEY} analysis changed; the baseline scan was overwritten")
    if project_exists(host, token, temp_key):
        raise SystemExit(f"temporary project {temp_key} was not deleted")

    print(
        json.dumps(
            {
                "ok": result["ok"],
                "baseline": BASELINE_KEY,
                "baseline_unchanged": True,
                "temp_project_deleted": temp_key,
                "removed": [_public(row) for row in result["removed"]],
                "added": [_public(row) for row in result["added"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


def scan_temp_project(
    project_key: str,
    token: str,
    sources: Path | None = None,
    exclusions: str = "",
    sonar_url: str = "http://host.docker.internal:9000",
) -> None:
    if project_key in PROTECTED_KEYS:
        raise SystemExit(f"refusing to scan the baseline project {project_key}")
    origin = sources or SOURCES
    with tempfile.TemporaryDirectory(prefix="cleardebt-rescan-") as directory:
        target = Path(directory)
        shutil.copytree(
            origin,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("node_modules", "coverage", ".scannerwork", ".git"),
        )
        properties = [
            f"sonar.projectKey={project_key}",
            f"sonar.projectName={project_key}",
            "sonar.sources=src",
            "sonar.sourceEncoding=UTF-8",
            "sonar.scm.disabled=true",
        ]
        if exclusions:
            properties.append(f"sonar.exclusions={exclusions}")
        (target / "sonar-project.properties").write_text("\n".join(properties) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-e",
                f"SONAR_HOST_URL={sonar_url}",
                "-e",
                f"SONAR_TOKEN={token}",
                "-v",
                f"{target}:/usr/src",
                "sonarsource/sonar-scanner-cli",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
    if completed.returncode != 0:
        raise SystemExit(completed.stdout + "\n" + completed.stderr)
    if project_key not in completed.stdout:
        raise SystemExit("scanner output did not mention the temporary project key")


def wait_until_processed(host: str, token: str, project_key: str) -> None:
    deadline = time.time() + 90
    while time.time() < deadline:
        payload = api_json(host, token, "/api/ce/component", {"component": project_key})
        if payload.get("queue"):
            time.sleep(2)
            continue
        current = payload.get("current") or {}
        status = current.get("status")
        if status == "SUCCESS" and current.get("componentKey") == project_key:
            return
        if status in {"FAILED", "CANCELED"}:
            raise SystemExit(f"temporary analysis {status}: {current}")
        time.sleep(2)
    raise SystemExit(f"timed out waiting for {project_key}")


def issue_rows(host: str, token: str, project_key: str) -> list[dict]:
    sources: dict[str, str] = {}
    rows = []
    for issue in fetch_issues(host, token, project_key):
        path = issue_path(issue.get("component", ""), project_key)
        text_range = issue.get("textRange") or {}
        start = int(text_range.get("startLine") or 1)
        end = int(text_range.get("endLine") or start)
        component = issue["component"]
        if component not in sources:
            sources[component] = api_text(host, token, "/api/sources/raw", {"key": component})
        text = line_span(sources[component], start, end)
        rows.append(
            {
                "fingerprint": fingerprint(issue["rule"], path, text),
                "rule": issue["rule"],
                "path": path,
                "line": start,
                "message": issue.get("message", ""),
            }
        )
    return rows


def delete_temp_project(host: str, token: str, project_key: str) -> None:
    if project_key in PROTECTED_KEYS or not project_key.startswith(TEMP_PREFIX):
        raise SystemExit(f"refusing to delete {project_key}")
    try:
        api_post(host, token, "/api/projects/delete", {"project": project_key})
    except urllib.error.HTTPError as error:
        if error.code != 404:
            detail = error.read().decode("utf-8", errors="replace")
            raise SystemExit(f"failed to delete {project_key}: {error.code} {detail}") from error


def analysis_date(host: str, token: str, project_key: str) -> str:
    payload = api_json(host, token, "/api/components/show", {"component": project_key})
    return payload["component"].get("analysisDate") or ""


def project_exists(host: str, token: str, project_key: str) -> bool:
    try:
        api_json(host, token, "/api/components/show", {"component": project_key})
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def api_json(host: str, token: str, path: str, params: dict) -> dict:
    body = api_request(host, token, path, params)
    return json.loads(body.decode("utf-8"))


def api_text(host: str, token: str, path: str, params: dict) -> str:
    return api_request(host, token, path, params).decode("utf-8")


def api_post(host: str, token: str, path: str, params: dict) -> None:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        f"{host.rstrip('/')}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        return


def api_request(host: str, token: str, path: str, params: dict) -> bytes:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{host.rstrip('/')}{path}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _public(row: dict) -> dict:
    return {
        "rule": row["rule"],
        "path": row["path"],
        "line": row["line"],
        "message": row["message"],
        "fingerprint": row["fingerprint"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
