#!/usr/bin/env python3
"""Rescan fixed code under a temporary Sonar project, then delete that project.

Never submits a report to the baseline project. A second scan of the same
project key would replace its last main-branch analysis.
"""

from __future__ import annotations

import argparse
import json
import os
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

TEMP_PREFIX = "cleardebt-rescan-"
FIXED_RULE = "javascript:S1128"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="要对照的正式 Sonar 项目；不传不会跑。")
    parser.add_argument("--sources", type=Path, required=True, help="改完后的源码目录。")
    parser.add_argument("--rule", default=FIXED_RULE)
    parser.add_argument("--host", default="http://localhost:9000")
    args = parser.parse_args()
    host = args.host
    token = load_token(None)
    baseline = args.project.strip()
    if not baseline:
        raise SystemExit("没有写项目，不会重扫。")
    baseline_stamp = analysis_date(host, token, baseline)
    temp_key = TEMP_PREFIX + uuid.uuid4().hex[:12]
    if temp_key == baseline or not temp_key.startswith(TEMP_PREFIX):
        raise SystemExit(f"refusing unsafe project key {temp_key}")

    try:
        scan_temp_project(temp_key, token, sources=args.sources, baseline=baseline)
        wait_until_processed(host, token, temp_key)
        before = issue_rows(host, token, baseline)
        after = issue_rows(host, token, temp_key)
        result = verdict(before, after, args.rule)
    finally:
        delete_temp_project(host, token, temp_key)

    if analysis_date(host, token, baseline) != baseline_stamp:
        raise SystemExit(f"{baseline} analysis changed; the baseline scan was overwritten")
    if project_exists(host, token, temp_key):
        print(
            f"warning: temporary project {temp_key} is still in Sonar; "
            "delete it by hand when Sonar is healthy again.",
            file=sys.stderr,
        )

    print(
        json.dumps(
            {
                "ok": result["ok"],
                "baseline": baseline,
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
    sonar_sources: str = "src",
    sonar_url: str = "http://host.docker.internal:9000",
    baseline: str | None = None,
) -> None:
    if not sources:
        raise SystemExit("没有源码目录，不会重扫。")
    if baseline and project_key == baseline:
        raise SystemExit(f"refusing to scan the baseline project {project_key}")
    if not project_key.startswith(TEMP_PREFIX):
        raise SystemExit(f"refusing to scan non-temporary project {project_key}")
    origin = sources
    sources_value = (sonar_sources or "src").strip() or "src"
    with tempfile.TemporaryDirectory(prefix="cleardebt-rescan-") as directory:
        target = Path(directory)
        shutil.copytree(
            origin,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "node_modules",
                "coverage",
                ".scannerwork",
                ".git",
                "target",
                "bin",
                "obj",
                ".venv",
                "venv",
            ),
        )
        properties = [
            f"sonar.projectKey={project_key}",
            f"sonar.projectName={project_key}",
            f"sonar.sources={sources_value}",
            "sonar.sourceEncoding=UTF-8",
            "sonar.scm.disabled=true",
        ]
        if exclusions:
            properties.append(f"sonar.exclusions={exclusions}")
        (target / "sonar-project.properties").write_text("\n".join(properties) + "\n", encoding="utf-8")
        cpus = os.environ.get("CLEARDEBT_SCANNER_CPUS", "1.0").strip() or "1.0"
        memory = os.environ.get("CLEARDEBT_SCANNER_MEMORY", "2g").strip() or "2g"
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                f"--cpus={cpus}",
                f"--memory={memory}",
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
    if not project_key.startswith(TEMP_PREFIX):
        raise SystemExit(f"refusing to delete {project_key}")
    last_error = ""
    for attempt in range(3):
        try:
            api_post(host, token, "/api/projects/delete", {"project": project_key})
            return
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return
            detail = error.read().decode("utf-8", errors="replace")
            last_error = f"{error.code} {detail}"
        except OSError as error:
            last_error = str(error)
        time.sleep(2 * (attempt + 1))
    print(
        f"warning: failed to delete {project_key} after 3 tries ({last_error}); "
        "leaving it in Sonar, the verdict above still stands.",
        file=sys.stderr,
    )


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
