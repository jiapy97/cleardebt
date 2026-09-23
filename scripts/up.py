#!/usr/bin/env python3
"""Start Postgres, Redis, the review page, and the morning worker.

Safe to run again: pieces that are already up are left alone.
Sonar and code hosting are not started here. Fill those in on the review page.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
PAGE = "http://127.0.0.1:8000/"


def main() -> int:
    os.chdir(ROOT)
    if shutil.which("docker") is None:
        print("先安装并启动 Docker。")
        return 1
    _compose("deploy/postgres/docker-compose.yml")
    _compose("deploy/redis/docker-compose.yml")
    _wait_postgres()
    _venv()
    _typescript()
    if not _page_up():
        _daemon("var/uvicorn.log", [str(PYTHON), "-m", "uvicorn", "cleardebt.api:app", "--host", "127.0.0.1", "--port", "8000"])
    if not _worker_up():
        _daemon(
            "var/arq-worker.log",
            [str(PYTHON), "-m", "arq", "cleardebt.batch_worker.WorkerSettings"],
            marker="Starting worker",
        )
    if not _page_up():
        print("网页没有起来。看 var/uvicorn.log")
        return 1
    print(f"审核页：{PAGE}")
    print("下一步：打开这个页面，填你自己的 Sonar 与代码托管，勾上空跑，再执行 python scripts/run_batch.py")
    return 0


def _compose(path: str) -> None:
    subprocess.run(["docker", "compose", "-f", path, "up", "-d"], cwd=ROOT, check=True)


def _wait_postgres() -> None:
    for _ in range(40):
        probe = subprocess.run(
            ["docker", "exec", "cleardebt-postgres", "pg_isready", "-U", "cleardebt"],
            capture_output=True,
        )
        if probe.returncode == 0:
            return
        time.sleep(0.5)
    raise SystemExit("Postgres 没有就绪。")


def _venv() -> None:
    if not PYTHON.exists():
        python = shutil.which("python3.12") or sys.executable
        subprocess.run([python, "-m", "venv", str(ROOT / ".venv")], check=True)
    stamp = ROOT / "var" / "requirements.stamp"
    requirements = ROOT / "requirements.txt"
    if stamp.is_file() and stamp.stat().st_mtime >= requirements.stat().st_mtime:
        return
    subprocess.run([str(ROOT / ".venv" / "bin" / "pip"), "install", "-r", str(requirements)], check=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("ok\n", encoding="utf-8")


def _typescript() -> None:
    if shutil.which("node") is None or shutil.which("npm") is None:
        print("没有 Node。要看上下文的规则取不了类型。装好 Node 后再执行一次。")
        return
    root = ROOT / "deploy" / "typescript"
    installed = root / "node_modules" / "typescript" / "package.json"
    lock = root / "package-lock.json"
    stamp = ROOT / "var" / "typescript.stamp"
    if installed.is_file() and lock.is_file() and stamp.is_file() and stamp.stat().st_mtime >= lock.stat().st_mtime:
        return
    subprocess.run(["npm", "ci", "--prefix", str(root)], cwd=ROOT, check=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("ok\n", encoding="utf-8")


def _page_up() -> bool:
    try:
        with urllib.request.urlopen(PAGE, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _worker_up() -> bool:
    probe = subprocess.run(["pgrep", "-f", "python -m arq cleardebt.batch_worker"], capture_output=True, text=True)
    return bool(probe.stdout.strip())


def _daemon(log_name: str, command: list[str], marker: str = "Uvicorn running") -> None:
    log_path = ROOT / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "a", encoding="utf-8")
    log.write(f"\n--- up {command[-1]} ---\n")
    log.flush()
    first = os.fork()
    if first == 0:
        os.setsid()
        second = os.fork()
        if second == 0:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            os.chdir(ROOT)
            os.environ["PYTHONUNBUFFERED"] = "1"
            os.execv(command[0], command)
        os._exit(0)
    os.waitpid(first, 0)
    log.close()
    for _ in range(50):
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if marker in text.split(f"--- up {command[-1]} ---")[-1]:
            return
        if marker == "Uvicorn running" and _page_up():
            return
        time.sleep(0.2)
    raise SystemExit(f"没有启动成功，看 {log_name}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"启动失败：{error}")
        raise SystemExit(1) from error
