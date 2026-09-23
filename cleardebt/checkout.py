"""Clone a bound project's branch. Supports GitLab, GitHub, and Azure DevOps."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def checkout_default(dest: Path, saved: dict | None = None) -> str:
    if saved is None:
        saved = _credentials()
    if not saved or not saved.get("remote"):
        raise SystemExit("还没填写代码仓库地址，服务碰不到任何仓库。")
    from cleardebt.hosting import default_branch

    branch = default_branch(saved)
    return checkout_branch(dest, saved, branch)


def checkout_branch(dest: Path, saved: dict, branch: str) -> str:
    """Clone a specific branch. Never pushes onto that branch."""
    name = (branch or "").strip()
    if not name:
        raise SystemExit("没有写分支，拉不下来。")
    if not saved or not saved.get("remote"):
        raise SystemExit("还没填写代码仓库地址，服务碰不到任何仓库。")
    _refuse_fixtures(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(
        dest.parent,
        ["clone", "--depth", "1", "--branch", name, saved["remote"], dest.name],
        saved["token"],
        provider=saved.get("provider") or "gitlab",
    )
    return name


def _credentials() -> dict:
    from cleardebt.controls import gitlab_credentials

    saved = gitlab_credentials()
    if not saved:
        raise SystemExit("还没填写代码仓库地址，服务碰不到任何仓库。")
    return saved


def _refuse_fixtures(dest: Path) -> None:
    resolved = dest.resolve()
    fixtures = FIXTURES.resolve()
    if resolved == fixtures or fixtures in resolved.parents:
        raise SystemExit("不会改玩具文件。")


def _git(repo: Path, args: list[str], token: str, *, provider: str = "gitlab") -> None:
    from cleardebt.hosting import askpass_username

    user = askpass_username(provider)
    askpass = Path(tempfile.mkdtemp(prefix="cleardebt-askpass-")) / "askpass"
    askpass.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  *[Uu]sername*) echo {user} ;;\n"
        '  *) echo "$CLEARDEBT_GIT_TOKEN" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    askpass.chmod(askpass.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["CLEARDEBT_GIT_TOKEN"] = token
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
        raise SystemExit(f"拉不下来分支：{detail[-500:]}")
