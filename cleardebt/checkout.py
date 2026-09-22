"""Clone the connected GitLab project's default branch. Never touches fixtures."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def checkout_default(dest: Path, saved: dict | None = None) -> str:
    if saved is None:
        saved = _credentials()
    if not saved or not saved.get("remote"):
        raise SystemExit("还没填写 GitLab 地址，服务碰不到任何仓库。")
    branch = _default_branch(saved)
    _refuse_fixtures(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(
        dest.parent,
        ["clone", "--depth", "1", "--branch", branch, saved["remote"], dest.name],
        saved["token"],
    )
    return branch


def _credentials() -> dict:
    from cleardebt.controls import gitlab_credentials

    saved = gitlab_credentials()
    if not saved:
        raise SystemExit("还没填写 GitLab 地址，服务碰不到任何仓库。")
    return saved


def _default_branch(saved: dict) -> str:
    parsed = urllib.parse.urlparse(saved["url"])
    request = urllib.request.Request(
        f"{parsed.scheme}://{parsed.netloc}/api/v4/projects/{saved['project_id']}",
        headers={"PRIVATE-TOKEN": saved["token"]},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    branch = payload.get("default_branch")
    if not branch:
        raise SystemExit("这个仓库没有默认分支。")
    return branch


def _refuse_fixtures(dest: Path) -> None:
    resolved = dest.resolve()
    fixtures = FIXTURES.resolve()
    if resolved == fixtures or fixtures in resolved.parents:
        raise SystemExit("不会改玩具文件。")


def _git(repo: Path, args: list[str], token: str) -> None:
    askpass = Path(tempfile.mkdtemp(prefix="cleardebt-askpass-")) / "askpass"
    askpass.write_text(
        '#!/bin/sh\ncase "$1" in\n  *[Uu]sername*) echo oauth2 ;;\n  *) echo "$GITLAB_TOKEN" ;;\nesac\n',
        encoding="utf-8",
    )
    askpass.chmod(askpass.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["GITLAB_TOKEN"] = token
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").replace(token, "***")
        raise SystemExit(f"拉不下来默认分支：{detail[-500:]}")
