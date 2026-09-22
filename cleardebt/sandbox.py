"""Run a project's Vitest suite inside an offline image of that project's dependencies.

Dependencies are installed with npm ci when the image is built. The test
container is started with no network, and the image refuses to run tests if it
can still reach the outside.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_PREFIX = "cleardebt-sandbox"
ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "deploy" / "sandbox"


def image_name(lockfile: Path) -> str:
    digest = hashlib.sha256(lockfile.read_bytes()).hexdigest()[:16]
    return f"{IMAGE_PREFIX}:{digest}"


def docker_command(work: Path, image: str | None = None) -> list[str]:
    resolved = work.resolve()
    tag = image or image_name(_lockfile(resolved))
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{resolved}:/work",
        "-e",
        "CLEARDEBT_WORK=/work",
        "-e",
        f"CLEARDEBT_HOST_WORK={resolved}",
        tag,
    ]


def run_project_tests(work: Path) -> subprocess.CompletedProcess[str]:
    tag = ensure_image(work)
    return subprocess.run(docker_command(work, tag), check=False, text=True, capture_output=True)


def ensure_image(work: Path) -> str:
    tag = image_name(_lockfile(work))
    inspected = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, text=True)
    if inspected.returncode == 0:
        return tag
    build_image(work, tag)
    return tag


def build_image(work: Path, tag: str | None = None) -> str:
    lockfile = _lockfile(work)
    package = work / "package.json"
    if not package.is_file():
        raise SystemExit("这个仓库没有 package.json，没法把依赖装进镜像。")
    tag = tag or image_name(lockfile)
    with tempfile.TemporaryDirectory(prefix="cleardebt-sandbox-") as directory:
        context = Path(directory)
        shutil.copy(package, context / "package.json")
        shutil.copy(lockfile, context / "package-lock.json")
        shutil.copy(DOCKERFILE / "Dockerfile", context / "Dockerfile")
        shutil.copy(DOCKERFILE / "cleardebt-test.mjs", context / "cleardebt-test.mjs")
        completed = subprocess.run(
            ["docker", "build", "-t", tag, str(context)],
            check=False,
            text=True,
            capture_output=True,
        )
    if completed.returncode != 0:
        raise SystemExit((completed.stdout + "\n" + completed.stderr)[-4000:])
    return tag


def _lockfile(work: Path) -> Path:
    lockfile = work / "package-lock.json"
    if not lockfile.is_file():
        raise SystemExit("这个仓库没有 package-lock.json，没法把依赖装进镜像。")
    return lockfile
