"""Scan a bound project's default branch into its real Sonar project.

Used by "list issues": Sonar only marks an issue resolved after a fresh
main-branch analysis, so merged fix requests stay OPEN until someone
rescans. Scanning the baseline key replaces its last analysis, which is
exactly what we want here (the temp-project rescan path must never touch
it, but this module exists for that purpose).
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from cleardebt.scan_progress import clear as clear_progress
from cleardebt.scan_progress import report as report_progress

ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOT = ROOT / "var" / "scan"

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def scan_baseline(repo: str, *, timeout: int = 600) -> dict:
    """Clone the default branch and scan it as the real Sonar project key.

    Every click rescans: the caller asked for fresh data, so no freshness
    window is applied here.
    """
    from cleardebt.checkout import checkout_default
    from cleardebt.controls import gitlab_credentials
    from cleardebt.issue_graph import sonar_base_url
    from cleardebt.languages import sonar_sources_value
    from list_issues import load_token

    name = (repo or "").strip()
    if not name:
        raise ValueError("没有写项目，重扫不起来。")
    with _guard:
        lock = _locks.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ValueError("上一次重扫还在跑，稍后再点列出告警。")
    try:
        saved = gitlab_credentials(name)
        if not saved or not saved.get("remote"):
            raise ValueError("这个项目还没绑定代码仓库地址，重扫不起来。")
        host = sonar_base_url()
        token = load_token(None)
        dest = _SCAN_ROOT / re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        report_progress(name, "正在拉取主分支代码…")
        checkout_default(dest, saved)
        report_progress(name, "正在跑 Sonar 扫描器（推代码给 Sonar）…")
        _run_scanner(dest, name, token, sonar_sources_value(dest))
        report_progress(name, "等 Sonar 处理分析结果…")
        _wait_processed(host, token, name, timeout=timeout)
        report_progress(name, "正在读最新告警列表…")
        return {"repo": name, "analysis_date": _analysis_date(host, token, name)}
    except ValueError:
        raise
    except SystemExit as error:
        raise ValueError(str(error.code) if isinstance(error.code, str) else "重扫时拉代码失败。") from error
    except Exception as error:
        raise ValueError(f"扫描时出错：{error}") from error
    finally:
        clear_progress(name)
        lock.release()


def _scanner_limits() -> list[str]:
    import os

    cpus = os.environ.get("CLEARDEBT_SCANNER_CPUS", "1.0").strip() or "1.0"
    memory = os.environ.get("CLEARDEBT_SCANNER_MEMORY", "2g").strip() or "2g"
    return [f"--cpus={cpus}", f"--memory={memory}"]


def _run_scanner(sources: Path, project_key: str, token: str, sonar_sources: str) -> None:
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            *_scanner_limits(),
            "-e",
            "SONAR_HOST_URL=http://host.docker.internal:9000",
            "-e",
            f"SONAR_TOKEN={token}",
            "-v",
            f"{sources}:/usr/src",
            "sonarsource/sonar-scanner-cli",
            f"-Dsonar.projectKey={project_key}",
            f"-Dsonar.projectName={project_key}",
            f"-Dsonar.sources={sonar_sources}",
            "-Dsonar.sourceEncoding=UTF-8",
            "-Dsonar.scm.disabled=true",
            "-Dsonar.exclusions=**/.git/**,**/node_modules/**,**/coverage/**",
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=540,
    )
    if completed.returncode != 0:
        detail = (completed.stdout or "") + "\n" + (completed.stderr or "")
        raise ValueError(f"扫描器没跑完：{detail.strip()[-500:]}")


def _wait_processed(host: str, token: str, project_key: str, *, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = _api_json(host, token, "/api/ce/component", {"component": project_key})
        if payload.get("queue"):
            time.sleep(3)
            continue
        current = payload.get("current") or {}
        status = current.get("status")
        if status == "SUCCESS":
            return
        if status in {"FAILED", "CANCELED"}:
            raise ValueError(f"Sonar 处理分析失败：{status}。")
        time.sleep(3)
    raise ValueError("等 Sonar 处理分析超时了，稍后再点列出告警。")


def _is_fresh(analysis_date: str, fresh_minutes: int) -> bool:
    from datetime import datetime, timedelta, timezone

    if not analysis_date or fresh_minutes <= 0:
        return False
    try:
        stamp = datetime.strptime(analysis_date, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return False
    return datetime.now(timezone.utc) - stamp.astimezone(timezone.utc) < timedelta(minutes=fresh_minutes)


def _analysis_date(host: str, token: str, project_key: str) -> str:
    import urllib.error

    try:
        payload = _api_json(host, token, "/api/components/show", {"component": project_key})
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ""
        raise
    return (payload.get("component") or {}).get("analysisDate") or ""


def _api_json(host: str, token: str, path: str, params: dict) -> dict:
    import json

    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{host.rstrip('/')}{path}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
