"""Code hosting adapters: GitLab, GitHub, Azure DevOps.

Bindings still store the clone URL in `gitlab_url` for backward compatibility;
`provider` is detected from the URL (or set explicitly).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class HostingError(RuntimeError):
    pass


def detect_provider(url: str, explicit: str | None = None) -> str:
    if explicit in {"gitlab", "github", "azure_devops"}:
        return explicit
    text = (url or "").lower()
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if "github.com" in host or host.endswith("github"):
        return "github"
    if "dev.azure.com" in host or "visualstudio.com" in host:
        return "azure_devops"
    if "gitlab" in host or text:
        return "gitlab"
    return "gitlab"


def askpass_username(provider: str) -> str:
    if provider == "github":
        return "x-access-token"
    if provider == "azure_devops":
        return "pat"
    return "oauth2"


def resolve_repository(url: str, token: str, provider: str | None = None) -> dict:
    """Validate access and return provider-specific ids for the binding."""
    kind = detect_provider(url, provider)
    if not token:
        return resolve_public_repository(url, kind)
    if kind == "github":
        return _resolve_github(url, token)
    if kind == "azure_devops":
        return _resolve_azure(url, token)
    return _resolve_gitlab(url, token)


def resolve_public_repository(url: str, provider: str | None = None) -> dict:
    """Accept only an anonymously readable HTTPS repository for scan-only use."""
    kind = detect_provider(url, provider)
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HostingError("无令牌仓库请填写公开的 HTTPS 仓库地址。")
    if kind == "github":
        path = _github_project_path(url)
    elif kind == "azure_devops":
        path = "/".join(_azure_parts(url))
    else:
        path = _gitlab_project_path(url)
    remote = url if url.endswith(".git") else url.rstrip("/") + ".git"
    if not _ls_remote_default(remote, anonymous=True):
        raise HostingError("无法匿名读取仓库默认分支；请确认仓库公开且地址正确。")
    return {"provider": kind, "project_id": None, "project_path": path, "url": url.rstrip("/")}


_DEFAULT_BRANCH_CACHE: dict[str, tuple[str, float]] = {}
_DEFAULT_BRANCH_TTL = 3600.0


def _ls_remote_default(remote: str, *, anonymous: bool = False) -> str:
    """Read the default branch via git protocol; zero API quota.

    `git ls-remote --symref <remote> HEAD` answers `ref: refs/heads/<name>`
    for public repos without any token. Returns "" on any trouble so the
    caller falls back to the hosting API.
    """
    import subprocess

    if not (remote or "").strip():
        return ""
    try:
        env = None
        command = ["git"]
        if anonymous:
            env = os.environ.copy()
            env.update({
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": os.devnull,
            })
            command += ["-c", "credential.helper=", "-c", f"core.askPass={os.devnull}"]
        completed = subprocess.run(
            [*command, "ls-remote", "--symref", remote.strip(), "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception:
        return ""
    for line in (completed.stdout or "").splitlines():
        if line.startswith("ref:"):
            ref = line.split()[1] if len(line.split()) > 1 else ""
            if ref.startswith("refs/heads/"):
                return ref[len("refs/heads/"):]
    return ""


def default_branch(saved: dict) -> str:
    import time

    kind = saved.get("provider") or detect_provider(saved.get("url") or "")
    cache_key = f"{kind}:{(saved.get('project_path') or saved.get('url') or '').strip()}"
    hit = _DEFAULT_BRANCH_CACHE.get(cache_key)
    if hit and time.time() - hit[1] < _DEFAULT_BRANCH_TTL:
        return hit[0]
    branch = _ls_remote_default(saved.get("remote") or "")
    if branch:
        _DEFAULT_BRANCH_CACHE[cache_key] = (branch, time.time())
        return branch
    if kind == "github":
        payload = _github_json("GET", f"/repos/{saved['project_path']}", saved["token"])
        branch = payload.get("default_branch")
    elif kind == "azure_devops":
        org, project, repo = _azure_parts(saved["url"])
        payload = _azure_json(
            "GET",
            f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/{urllib.parse.quote(repo)}",
            saved["token"],
            api_version="7.1",
        )
        branch = (payload.get("defaultBranch") or "").replace("refs/heads/", "")
    else:
        payload = _gitlab_json("GET", f"/projects/{saved['project_id']}", saved["token"], saved["url"])
        branch = payload.get("default_branch")
    if not branch:
        raise HostingError("这个仓库没有默认分支。")
    import time as _time

    _DEFAULT_BRANCH_CACHE[cache_key] = (branch, _time.time())
    return branch


def ensure_push_access(saved: dict) -> None:
    kind = saved.get("provider") or detect_provider(saved.get("url") or "")
    if kind == "github":
        payload = _github_json("GET", f"/repos/{saved['project_path']}", saved["token"])
        perms = payload.get("permissions") or {}
        if not (perms.get("push") or perms.get("admin")):
            raise HostingError("这个 GitHub 令牌不能推送代码，也不能开拉取请求。需要 push 权限。")
        return
    if kind == "azure_devops":
        # Creating a draft PR later will fail loudly if the PAT lacks Code (Read & Write).
        org, project, repo = _azure_parts(saved["url"])
        _azure_json(
            "GET",
            f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/{urllib.parse.quote(repo)}",
            saved["token"],
            api_version="7.1",
        )
        return
    from cleardebt.gitlab_mr import ensure_access

    payload = _gitlab_json("GET", f"/projects/{saved['project_id']}", saved["token"], saved["url"])
    access = (payload.get("permissions") or {}).get("project_access") or {}
    ensure_access(int(access.get("access_level") or 0))


def create_request(
    saved: dict,
    *,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
) -> dict:
    """Open an MR/PR. Returns {iid, web_url, provider}."""
    kind = saved.get("provider") or detect_provider(saved.get("url") or "")
    if kind == "github":
        payload = _github_json(
            "POST",
            f"/repos/{saved['project_path']}/pulls",
            saved["token"],
            {
                "title": title,
                "head": source_branch,
                "base": target_branch,
                "body": description,
            },
        )
        return {
            "iid": int(payload["number"]),
            "web_url": payload.get("html_url") or "",
            "provider": "github",
        }
    if kind == "azure_devops":
        org, project, repo = _azure_parts(saved["url"])
        payload = _azure_json(
            "POST",
            f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/{urllib.parse.quote(repo)}/pullrequests",
            saved["token"],
            {
                "sourceRefName": f"refs/heads/{source_branch}",
                "targetRefName": f"refs/heads/{target_branch}",
                "title": title,
                "description": description,
            },
            api_version="7.1",
        )
        pr_id = int(payload["pullRequestId"])
        web = payload.get("url") or ""
        # Prefer human UI URL when we can build it.
        web_ui = (
            f"https://dev.azure.com/{org}/{urllib.parse.quote(project)}/_git/{urllib.parse.quote(repo)}"
            f"/pullrequest/{pr_id}"
        )
        return {"iid": pr_id, "web_url": web_ui or web, "provider": "azure_devops"}
    # GitLab form API uses application/x-www-form-urlencoded.
    if not saved.get("project_id"):
        raise HostingError("GitLab 项目 id 缺失：去接入页重新保存这条绑定（会自动解析 id）。")
    parsed = urllib.parse.urlparse(saved["url"])
    data = urllib.parse.urlencode(
        {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{parsed.scheme}://{parsed.netloc}/api/v4/projects/{int(saved['project_id'])}/merge_requests",
        data=data,
        headers={"PRIVATE-TOKEN": saved["token"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HostingError(f"托管平台 {error.code}: {detail[:300]}") from error
    return {
        "iid": int(payload["iid"]),
        "web_url": payload.get("web_url") or "",
        "provider": "gitlab",
    }


def load_pull_request(saved: dict, iid: int) -> dict:
    """Load an open MR/PR. Returns source/target branches and web URL."""
    kind = saved.get("provider") or detect_provider(saved.get("url") or "")
    if kind == "github":
        payload = _github_json(
            "GET",
            f"/repos/{saved['project_path']}/pulls/{int(iid)}",
            saved["token"],
        )
        source = (payload.get("head") or {}).get("ref") or ""
        target = (payload.get("base") or {}).get("ref") or ""
        state = payload.get("state") or ""
        return {
            "iid": int(payload.get("number") or iid),
            "title": payload.get("title") or "",
            "web_url": payload.get("html_url") or "",
            "source_branch": source,
            "target_branch": target,
            "state": state,
            "provider": "github",
        }
    if kind == "azure_devops":
        org, project, repo = _azure_parts(saved["url"])
        payload = _azure_json(
            "GET",
            f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/"
            f"{urllib.parse.quote(repo)}/pullrequests/{int(iid)}",
            saved["token"],
            api_version="7.1",
        )
        source = (payload.get("sourceRefName") or "").replace("refs/heads/", "")
        target = (payload.get("targetRefName") or "").replace("refs/heads/", "")
        status = (payload.get("status") or "").lower()
        pr_id = int(payload.get("pullRequestId") or iid)
        web_url = (
            f"https://dev.azure.com/{org}/{urllib.parse.quote(project)}/_git/{urllib.parse.quote(repo)}"
            f"/pullrequest/{pr_id}"
        )
        return {
            "iid": pr_id,
            "title": payload.get("title") or "",
            "web_url": web_url,
            "source_branch": source,
            "target_branch": target,
            "state": status,
            "provider": "azure_devops",
        }
    payload = _gitlab_json(
        "GET",
        f"/projects/{saved['project_id']}/merge_requests/{int(iid)}",
        saved["token"],
        saved["url"],
    )
    return {
        "iid": int(payload.get("iid") or iid),
        "title": payload.get("title") or "",
        "web_url": payload.get("web_url") or "",
        "source_branch": payload.get("source_branch") or "",
        "target_branch": payload.get("target_branch") or "",
        "state": payload.get("state") or "",
        "provider": "gitlab",
    }


def post_comment(saved: dict, iid: int, body: str) -> dict:
    """Post a comment/note on an MR/PR. Returns {id, provider}."""
    kind = saved.get("provider") or detect_provider(saved.get("url") or "")
    if kind == "github":
        payload = _github_json(
            "POST",
            f"/repos/{saved['project_path']}/issues/{int(iid)}/comments",
            saved["token"],
            {"body": body},
        )
        return {"id": payload.get("id"), "provider": "github"}
    if kind == "azure_devops":
        org, project, repo = _azure_parts(saved["url"])
        # Threads API: create a comment thread on the PR.
        payload = _azure_json(
            "POST",
            f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/"
            f"{urllib.parse.quote(repo)}/pullRequests/{int(iid)}/threads",
            saved["token"],
            {
                "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
                "status": 1,
            },
            api_version="7.1",
        )
        comments = payload.get("comments") or []
        note_id = (comments[0] or {}).get("id") if comments else payload.get("id")
        return {"id": note_id, "provider": "azure_devops"}
    payload = _gitlab_json(
        "POST",
        f"/projects/{saved['project_id']}/merge_requests/{int(iid)}/notes",
        saved["token"],
        saved["url"],
        body={"body": body},
    )
    return {"id": payload.get("id"), "provider": "gitlab"}


def credentials_bundle(
    *,
    url: str,
    token: str,
    project_id: Any,
    project_path: str,
    provider: str,
    sonar_key: str,
) -> dict:
    remote = url if url.endswith(".git") else url + ".git"
    # Azure remotes usually omit .git
    if provider == "azure_devops":
        remote = url.rstrip("/")
    return {
        "url": url.rstrip("/"),
        "token": token,
        "project_id": project_id,
        "project_path": project_path,
        "remote": remote,
        "provider": provider,
        "sonar_key": sonar_key,
    }


def _resolve_gitlab(url: str, token: str) -> dict:
    path = _gitlab_project_path(url)
    encoded = urllib.parse.quote(path, safe="")
    parsed = urllib.parse.urlparse(url)
    payload = _request_json(
        f"{parsed.scheme}://{parsed.netloc}/api/v4/projects/{encoded}",
        headers={"PRIVATE-TOKEN": token},
    )
    return {
        "provider": "gitlab",
        "project_id": int(payload["id"]),
        "project_path": path,
        "url": url.rstrip("/"),
    }


def _resolve_github(url: str, token: str) -> dict:
    path = _github_project_path(url)
    payload = _github_json("GET", f"/repos/{path}", token)
    full = payload.get("full_name") or path
    return {
        "provider": "github",
        "project_id": full,
        "project_path": full,
        "url": (payload.get("html_url") or url).rstrip("/"),
    }


def _resolve_azure(url: str, token: str) -> dict:
    org, project, repo = _azure_parts(url)
    payload = _azure_json(
        "GET",
        f"/{org}/{urllib.parse.quote(project)}/_apis/git/repositories/{urllib.parse.quote(repo)}",
        token,
        api_version="7.1",
    )
    return {
        "provider": "azure_devops",
        "project_id": payload.get("id") or f"{org}/{project}/{repo}",
        "project_path": f"{org}/{project}/{repo}",
        "url": url.rstrip("/"),
    }


def _gitlab_project_path(url: str) -> str:
    parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
    if len(parts) < 2:
        raise HostingError("GitLab 地址要写成 https://gitlab.com/组/项目")
    return "/".join(parts[:2]).removesuffix(".git")


def _github_project_path(url: str) -> str:
    parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
    if len(parts) < 2:
        raise HostingError("GitHub 地址要写成 https://github.com/组织/仓库")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def _azure_parts(url: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    if "dev.azure.com" in host:
        # /org/project/_git/repo
        if len(parts) < 4 or parts[2] != "_git":
            raise HostingError(
                "Azure DevOps 地址要写成 https://dev.azure.com/组织/项目/_git/仓库"
            )
        return parts[0], parts[1], parts[3].removesuffix(".git")
    if host.endswith("visualstudio.com"):
        org = host.split(".")[0]
        # /project/_git/repo
        if len(parts) < 3 or parts[1] != "_git":
            raise HostingError(
                "Azure DevOps 地址要写成 https://组织.visualstudio.com/项目/_git/仓库"
            )
        return org, parts[0], parts[2].removesuffix(".git")
    raise HostingError("无法识别的 Azure DevOps 地址。")


def _gitlab_json(
    method: str,
    path: str,
    token: str,
    gitlab_url: str,
    body: dict | None = None,
) -> dict:
    parsed = urllib.parse.urlparse(gitlab_url)
    headers = {"PRIVATE-TOKEN": token}
    if body is not None:
        # Notes and similar endpoints accept JSON.
        headers["Content-Type"] = "application/json"
    return _request_json(
        f"{parsed.scheme}://{parsed.netloc}/api/v4{path}",
        method=method,
        headers=headers,
        body=body,
    )


def _github_json(method: str, path: str, token: str, body: dict | None = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if (token or "").strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        return _request_json(f"https://api.github.com{path}", method=method, headers=headers, body=body)
    except HostingError as error:
        if " 401" not in str(error) or "Authorization" not in headers:
            raise
        fallback = {key: value for key, value in headers.items() if key != "Authorization"}
        return _request_json(f"https://api.github.com{path}", method=method, headers=fallback, body=body)


def _azure_json(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    *,
    api_version: str,
) -> dict:
    import base64

    auth = base64.b64encode((":" + token).encode("utf-8")).decode("ascii")
    sep = "&" if "?" in path else "?"
    url = f"https://dev.azure.com{path}{sep}api-version={api_version}"
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    return _request_json(url, method=method, headers=headers, body=body)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HostingError(f"托管平台 {error.code}: {detail[:300]}") from error
    except urllib.error.URLError as error:
        raise HostingError("连不上代码托管平台") from error


def _platform_tokens() -> dict:
    from cleardebt.controls import form_values

    values = form_values()
    return {
        "gitlab": values.get("gitlab_token") or "",
        "github": values.get("github_token") or "",
        "azure_devops": values.get("azure_token") or "",
        "gitlab_url": values.get("gitlab_url") or "https://gitlab.com",
    }


def list_owned_projects(provider: str) -> list[dict]:
    """List repos the stored token can see. Used by the import picker."""
    kind = (provider or "").strip().lower() or "gitlab"
    tokens = _platform_tokens()
    out: list[dict] = []
    if kind == "github":
        token = tokens["github"]
        if not token:
            raise HostingError("还没填 GitHub 令牌，列不出仓库。")
        page = 1
        while True:
            items = _github_paged(f"/user/repos?per_page=100&page={page}", token)
            for item in items:
                if not item.get("archived"):
                    out.append(
                        {"name": item.get("full_name") or "", "url": item.get("html_url") or "", "private": bool(item.get("private"))}
                    )
            if len(items) < 100 or len(out) >= 500:
                break
            page += 1
    else:
        token = tokens["gitlab"]
        base = tokens["gitlab_url"]
        if not token:
            raise HostingError("还没填 GitLab 令牌，列不出仓库。")
        page = 1
        while True:
            items = _gitlab_paged(f"/projects?membership=true&simple=true&per_page=100&page={page}", token, base)
            for item in items:
                out.append(
                    {"name": item.get("path_with_namespace") or "", "url": item.get("web_url") or "", "private": item.get("visibility") != "public"}
                )
            if len(items) < 100 or len(out) >= 500:
                break
            page += 1
    return out


def _github_paged(path: str, token: str) -> list:
    import urllib.request as _request

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = _request.Request("https://api.github.com" + path, headers=headers)
    with _request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _gitlab_paged(path: str, token: str, base: str) -> list:
    import urllib.request as _request

    parsed = urllib.parse.urlparse(base)
    request = _request.Request(
        f"{parsed.scheme}://{parsed.netloc}/api/v4{path}", headers={"PRIVATE-TOKEN": token}
    )
    with _request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def create_project(provider: str, name: str) -> dict:
    """Create an empty repo on the platform. Returns {"url", "name"}."""
    kind = (provider or "").strip().lower() or "gitlab"
    clean = (name or "").strip().strip("/")
    import re as _re

    if not clean or not _re.fullmatch(r"[A-Za-z0-9_.\-]+", clean):
        raise HostingError("仓库名只能是字母、数字、中划线、下划线、点。")
    tokens = _platform_tokens()
    if kind == "github":
        token = tokens["github"]
        if not token:
            raise HostingError("还没填 GitHub 令牌，建不了仓库。")
        try:
            created = _github_json("POST", "/user/repos", token, {"name": clean, "private": True, "auto_init": True})
        except HostingError as error:
            raise HostingError(f"GitHub 建仓失败：{error}") from error
        url = created.get("html_url") or ""
        if not url:
            raise HostingError("GitHub 建仓返回里没有地址。")
        return {"url": url, "name": created.get("full_name") or clean}
    token = tokens["gitlab"]
    base = tokens["gitlab_url"]
    if not token:
        raise HostingError("还没填 GitLab 令牌，建不了仓库。")
    try:
        created = _gitlab_json(
            "POST", "/projects", token, base,
            {"name": clean, "visibility": "private", "initialize_with_readme": "true"},
        )
    except HostingError as error:
        raise HostingError(f"GitLab 建仓失败：{error}") from error
    url = created.get("web_url") or ""
    if not url:
        raise HostingError("GitLab 建仓返回里没有地址。")
    return {"url": url, "name": created.get("path_with_namespace") or clean}
