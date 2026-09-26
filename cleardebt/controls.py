"""Operator switches. Stored in Postgres so a restart does not forget them."""

from __future__ import annotations

import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
from cleardebt.time_display import format_beijing

_ensure_lock = threading.Lock()
_ensured = False

ROOT = Path(__file__).resolve().parents[1]

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)
DEFAULT_WHITELIST = ()


def automation_for(settings: dict, repo: str | None = None) -> dict:
    from cleardebt.schedule import normalize_automation

    base = normalize_automation(settings.get("backlog_automation") or {})
    if not repo:
        return base
    for item in settings.get("bindings") or []:
        if item.get("sonar_key") != repo:
            continue
        override = item.get("automation")
        if isinstance(override, dict) and override:
            merged = dict(base)
            merged.update(override)
            return normalize_automation(merged)
    return base


def project_switches(settings: dict, repo: str) -> dict:
    """Per-project backlog / request-fix flags (default on; global request_fix can force off)."""
    backlog = True
    request = True
    for item in settings.get("bindings") or []:
        if item.get("sonar_key") != repo:
            continue
        if "backlog_fix" in item:
            backlog = bool(item.get("backlog_fix"))
        if "request_fix" in item:
            request = bool(item.get("request_fix"))
        break
    if not settings.get("request_fix", True):
        request = False
    return {"backlog_fix": backlog, "request_fix": request}


def backlog_gate(settings: dict, repo: str) -> str | None:
    refused = gate(settings, repo)
    if refused:
        return refused
    if project_read_only(settings, repo):
        return f"{repo} 是无令牌只读仓库，只能扫描和查看问题。"
    if not project_switches(settings, repo)["backlog_fix"]:
        return f"{repo} 的 backlog 修复关掉了。"
    return None


def project_read_only(settings: dict, repo: str) -> bool:
    return any(
        item.get("sonar_key") == repo and bool(item.get("read_only"))
        for item in settings.get("bindings") or []
    )


def binding_read_only(item: dict, tokens: dict[str, str]) -> bool:
    from cleardebt.hosting import detect_provider

    provider = item.get("provider") or detect_provider(item.get("gitlab_url") or "")
    return bool(item.get("read_only")) or not bool(tokens.get(provider))


def _hosting_tokens(row: tuple) -> dict[str, str]:
    return {
        "gitlab": row[7] or "",
        "github": (row[13] if len(row) > 13 else None) or "",
        "azure_devops": (row[14] if len(row) > 14 else None) or "",
    }


def unbound_reason(repo: str) -> str:
    return f"{repo} 没有对应的代码仓库绑定，这一轮跳过，不去改别的仓库。"


def parse_binding_lines(text: str) -> list[dict]:
    found = []
    seen = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key_side = line.split("=", 1)[0]
        if "=" in line and " " not in key_side and "://" not in key_side:
            key, url = line.split("=", 1)
        else:
            parts = line.split(None, 1)
            key = parts[0]
            url = parts[1] if len(parts) > 1 else ""
        key = key.strip()
        url = url.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append({"sonar_key": key, "gitlab_url": url})
    return found


def merge_bindings(selected: list[str], text: str) -> list[dict]:
    parsed = parse_binding_lines(text)
    urls = {item["sonar_key"]: item["gitlab_url"] for item in parsed}
    names = []
    for key in [*selected, *[item["sonar_key"] for item in parsed]]:
        if key and key not in names:
            names.append(key)
    return [{"sonar_key": key, "gitlab_url": urls.get(key, "")} for key in names]


def legacy_bindings(
    whitelist: list[str],
    gitlab_url: str,
    project_id: int | None,
    stored,
) -> list[dict]:
    if isinstance(stored, str):
        import json

        stored = json.loads(stored)
    if stored:
        return [dict(item) for item in stored]
    if len(whitelist) == 1 and gitlab_url and project_id:
        return [
            {
                "sonar_key": whitelist[0],
                "gitlab_url": gitlab_url.rstrip("/"),
                "project_id": int(project_id),
            }
        ]
    return [{"sonar_key": name, "gitlab_url": "", "project_id": None} for name in whitelist]


def credentials_for(bindings: list[dict], token: str, sonar_key: str | None, tokens: dict | None = None) -> dict | None:
    """Pick credentials for a Sonar project. `token` is the GitLab token (legacy)."""
    from cleardebt.hosting import credentials_bundle, detect_provider

    tokens = tokens or {}
    usable = [item for item in bindings if item.get("gitlab_url")]
    if sonar_key:
        chosen = next((item for item in usable if item.get("sonar_key") == sonar_key), None)
    elif len(usable) == 1:
        chosen = usable[0]
    else:
        chosen = None
    if not chosen:
        return None
    url = str(chosen["gitlab_url"]).rstrip("/")
    provider = chosen.get("provider") or detect_provider(url)
    chosen_token = tokens.get(provider) or (token if provider == "gitlab" else "") or ""
    path = chosen.get("project_path") or ""
    if not path:
        try:
            from cleardebt.hosting import _azure_parts, _github_project_path, _gitlab_project_path

            if provider == "github":
                path = _github_project_path(url)
            elif provider == "azure_devops":
                path = "/".join(_azure_parts(url))
            else:
                path = _gitlab_project_path(url)
        except Exception:
            path = url
    saved = credentials_bundle(
        url=url,
        token=chosen_token,
        project_id=chosen.get("project_id"),
        project_path=path,
        provider=provider,
        sonar_key=chosen.get("sonar_key") or "",
    )
    saved["read_only"] = bool(chosen.get("read_only")) or not bool(chosen_token)
    return saved


def binding_lines(bindings: list[dict]) -> str:
    lines = []
    for item in bindings:
        key = item.get("sonar_key") or ""
        if not key:
            continue
        url = item.get("gitlab_url") or ""
        lines.append(f"{key} {url}".rstrip())
    return "\n".join(lines)


def list_bindings() -> list[dict]:
    """Enriched binding rows for the setup table."""
    row = _row()
    tokens = _hosting_tokens(row)
    out = []
    for item in _bindings_from_row(row):
        out.append(
            {
                "sonar_key": item.get("sonar_key") or "",
                "gitlab_url": item.get("gitlab_url") or "",
                "provider": item.get("provider") or "",
                "project_id": item.get("project_id"),
                "project_path": item.get("project_path") or "",
                "backlog_fix": item.get("backlog_fix", True),
                "request_fix": item.get("request_fix", True),
                "agent_mode": bool(item.get("agent_mode", False)),
                "read_only": binding_read_only(item, tokens),
            }
        )
    return out


def upsert_binding(sonar_key: str, gitlab_url: str) -> dict:
    """Add or update one binding; resolves provider/path/id eagerly."""
    from cleardebt.hosting import (
        _github_project_path,
        _gitlab_project_path,
        detect_provider,
        resolve_repository,
    )

    key = (sonar_key or "").strip()
    url = (gitlab_url or "").strip().rstrip("/")
    if not key:
        raise ValueError("Sonar 项目 key 不能为空。")
    if not url:
        raise ValueError("仓库地址不能为空。")
    provider = detect_provider(url)
    try:
        if provider == "github":
            path = _github_project_path(url)
        elif provider == "azure_devops":
            from cleardebt.hosting import _azure_parts

            org, project, repo = _azure_parts(url)
            path = f"{org}/{project}/{repo}"
        else:
            path = _gitlab_project_path(url)
    except Exception as error:
        raise ValueError(str(error)) from error
    row = _row()
    tokens = _hosting_tokens(row)
    token = tokens.get(provider) or ""
    if token:
        project_id = _resolve_project_id(provider, url, path)
    else:
        from cleardebt.hosting import HostingError

        try:
            resolved = resolve_repository(url, "", provider)
        except HostingError as error:
            raise ValueError(str(error)) from error
        project_id = resolved["project_id"]
        url = resolved["url"]
    stored = [dict(item) for item in _bindings_from_row(row)]
    current = next((item for item in stored if item.get("sonar_key") == key), {})
    entry = {
        "sonar_key": key,
        "gitlab_url": url,
        "provider": provider,
        "project_id": project_id,
        "project_path": path,
        "backlog_fix": current.get("backlog_fix", True),
        "request_fix": current.get("request_fix", True),
        "agent_mode": bool(current.get("agent_mode", False)),
        "read_only": not bool(token),
        "automation": current.get("automation") or {},
    }
    stored = [item for item in stored if item.get("sonar_key") != key] + [entry]
    whitelist = list(row[2] or [])
    if key not in whitelist:
        whitelist.append(key)
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "UPDATE controls SET repo_bindings = %s, whitelist = %s WHERE id = 1",
            (_json(stored), whitelist),
        )
    return {k: entry.get(k) for k in ("sonar_key", "gitlab_url", "provider", "project_id", "project_path", "read_only")}


def delete_binding(sonar_key: str) -> None:
    key = (sonar_key or "").strip()
    if not key:
        return
    row = _row()
    stored = [dict(item) for item in _bindings_from_row(row) if item.get("sonar_key") != key]
    whitelist = [name for name in (row[2] or []) if name != key]
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "UPDATE controls SET repo_bindings = %s, whitelist = %s WHERE id = 1",
            (_json(stored), whitelist),
        )


def _resolve_project_id(provider: str, url: str, path: str):
    """Best-effort hosted id; GitHub/Azure don't need one (stored as None)."""
    if provider != "gitlab":
        return None
    row = _row()
    token = row[7] or ""
    host = urllib.parse.urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    if not token or not base:
        return None
    import json

    encoded = urllib.parse.quote(path, safe="")
    request = urllib.request.Request(
        f"{base}/api/v4/projects/{encoded}", headers={"PRIVATE-TOKEN": token}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8")).get("id")
    except Exception:
        return None


def test_binding(sonar_key: str, gitlab_url: str) -> dict:
    """Probe Sonar project + git reachability without saving anything."""
    from cleardebt.hosting import _ls_remote_default, detect_provider

    key = (sonar_key or "").strip()
    url = (gitlab_url or "").strip()
    detail: dict = {"sonar_key": key, "gitlab_url": url, "sonar_ok": False, "git_ok": False}
    row = _row()
    sonar_url = row[4] or ""
    token = row[6] or ""
    if key and sonar_url and token:
        try:
            detail["sonar_ok"] = key in sonar_projects(sonar_url, token)
        except Exception:
            detail["sonar_ok"] = False
    else:
        detail["sonar_hint"] = "先填 Sonar 地址与令牌才能验证项目。"
    if url:
        try:
            branch = _ls_remote_default(url if url.endswith(".git") else url + ".git")
            detail["git_ok"] = bool(branch)
            detail["default_branch"] = branch
            detail["provider"] = detect_provider(url)
        except Exception as error:
            detail["git_hint"] = str(error)[:120]
    detail["ok"] = bool(detail["sonar_ok"] and detail["git_ok"])
    return detail


def binding_health() -> list[dict]:
    """One status row per binding for the health lights."""
    rows = []
    for item in list_bindings():
        try:
            probe = test_binding(item["sonar_key"], item["gitlab_url"])
        except Exception as error:
            probe = {"sonar_ok": False, "git_ok": False, "git_hint": str(error)[:120]}
        rows.append(
            {
                "sonar_key": item["sonar_key"],
                "gitlab_url": item["gitlab_url"],
                "provider": item["provider"],
                "sonar_ok": probe.get("sonar_ok", False),
                "git_ok": probe.get("git_ok", False),
                "ok": bool(probe.get("sonar_ok") and probe.get("git_ok")),
                "hint": probe.get("git_hint") or probe.get("sonar_hint") or "",
            }
        )
    return rows


def gate(settings: dict, repo: str) -> str | None:
    if not settings.get("configured"):
        return "还没填写接入信息，服务碰不到任何仓库。"
    if not settings["enabled"]:
        return "总开关关掉了，这一轮不开始。"
    if repo not in settings["whitelist"]:
        return f"{repo} 不在白名单里，碰不到。"
    return None


def save_project_switches(updates: list[dict]) -> dict:
    """Update per-project repair switches on existing bindings."""
    _ensure()
    current = load_controls()
    # Prefer full stored bindings (with project_id) from DB.
    stored = _bindings_from_row(_row())
    by_stored = {item.get("sonar_key"): dict(item) for item in stored if item.get("sonar_key")}
    for item in updates or []:
        key = (item.get("sonar_key") or "").strip()
        if not key or key not in by_stored:
            continue
        row = by_stored[key]
        if "backlog_fix" in item:
            row["backlog_fix"] = bool(item.get("backlog_fix"))
        if "request_fix" in item:
            row["request_fix"] = bool(item.get("request_fix"))
        if "agent_mode" in item:
            row["agent_mode"] = bool(item.get("agent_mode"))
        if "automation" in item:
            auto = item.get("automation")
            row["automation"] = auto if isinstance(auto, dict) else {}
        by_stored[key] = row
    ordered = []
    for name in current.get("whitelist") or []:
        if name in by_stored:
            ordered.append(by_stored[name])
    for key, row in by_stored.items():
        if key not in {item.get("sonar_key") for item in ordered}:
            ordered.append(row)
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "UPDATE controls SET repo_bindings = %s WHERE id = 1",
            (_json(ordered),),
        )
    return load_controls()


def llm_token() -> str:
    """Token from DB (management page), if any."""
    row = _row()
    if len(row) > 15 and row[15]:
        return str(row[15]).strip()
    return ""


def form_values() -> dict:
    row = _row()
    sonar_url = row[4] or "http://localhost:9000"
    gitlab_url = row[5] or ""
    sonar_token = row[6] or _file_token(ROOT / "deploy" / "sonarqube" / ".token")
    gitlab_token = row[7] or _file_token(ROOT / "deploy" / "gitlab" / ".token")
    github_token = (row[13] if len(row) > 13 and row[13] else "") or _file_token(
        ROOT / "deploy" / "github" / ".token"
    )
    azure_token = (row[14] if len(row) > 14 and row[14] else "") or _file_token(
        ROOT / "deploy" / "azure" / ".token"
    )
    llm = (row[15] if len(row) > 15 and row[15] else "") or _file_token(
        ROOT / "deploy" / "llm" / ".token"
    ) or _file_token(ROOT / "deploy" / "deepseek" / ".token")
    bindings = _bindings_from_row(row)
    hosting_tokens = {"gitlab": gitlab_token, "github": github_token, "azure_devops": azure_token}
    return {
        "configured": row[3],
        "sonar_url": sonar_url,
        "gitlab_url": gitlab_url,
        "sonar_token": sonar_token,
        "gitlab_token": gitlab_token,
        "github_token": github_token,
        "azure_token": azure_token,
        "llm_token": llm,
        "whitelist": list(row[2]),
        "bindings": [
            {
                "sonar_key": item.get("sonar_key") or "",
                "gitlab_url": item.get("gitlab_url") or "",
                "provider": item.get("provider") or "",
                "backlog_fix": item.get("backlog_fix", True),
                "request_fix": item.get("request_fix", True),
                "agent_mode": bool(item.get("agent_mode", False)),
                "read_only": binding_read_only(item, hosting_tokens),
                "automation": item.get("automation") or {},
            }
            for item in bindings
        ],
        "binding_lines": binding_lines(bindings),
    }


def sonar_projects(url: str, token: str) -> list[str]:
    import json
    import urllib.error
    import urllib.request

    if not url or not token:
        return []
    request = urllib.request.Request(
        url.rstrip("/") + "/api/projects/search?ps=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return []
    return [item["key"] for item in payload.get("components", []) if item.get("key")]


def _file_token(path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def load_controls() -> dict:
    row = _row()
    hosting_tokens = _hosting_tokens(row)
    return {
        "enabled": row[0],
        "dry_run": row[1],
        "whitelist": list(row[2]),
        "configured": row[3],
        "sonar_url": row[4] or "",
        "gitlab_url": row[5] or "",
        "sonar_token_set": bool(row[6]),
        "gitlab_token_set": bool(row[7]),
        "github_token_set": bool(row[13]) if len(row) > 13 else False,
        "azure_token_set": bool(row[14]) if len(row) > 14 else False,
        "llm_token_set": bool(row[15]) if len(row) > 15 else False,
        "retrieve": bool(row[9]),
        "bindings": [
            {
                "sonar_key": item.get("sonar_key") or "",
                "gitlab_url": item.get("gitlab_url") or "",
                "provider": item.get("provider") or "",
                "backlog_fix": item.get("backlog_fix", True),
                "request_fix": item.get("request_fix", True),
                "agent_mode": bool(item.get("agent_mode", False)),
                "read_only": binding_read_only(item, hosting_tokens),
                "automation": item.get("automation") or {},
            }
            for item in _bindings_from_row(row)
        ],
        "backlog_automation": _automation_from_row(row),
        "request_fix": bool(row[12]) if len(row) > 12 else True,
    }


def sonar_credentials() -> dict | None:
    row = _row()
    if not row[3] or not row[4] or not row[6]:
        return None
    return {"url": row[4].rstrip("/"), "token": row[6]}


def gitlab_credentials(sonar_key: str | None = None) -> dict | None:
    row = _row()
    if not row[3]:
        return None
    tokens = _hosting_tokens(row)
    if not any(tokens.values()):
        tokens = {key: "" for key in tokens}
    return credentials_for(_bindings_from_row(row), tokens.get("gitlab") or "", sonar_key, tokens=tokens)


def save_controls(
    *,
    enabled: bool | None = None,
    dry_run: bool | None = None,
    retrieve: bool | None = None,
    backlog_automation: dict | None = None,
    request_fix: bool | None = None,
) -> dict:
    from cleardebt.schedule import normalize_automation

    current = load_controls()
    if enabled is not None:
        current["enabled"] = enabled
    if dry_run is not None:
        current["dry_run"] = dry_run
    if retrieve is not None:
        current["retrieve"] = retrieve
    if backlog_automation is not None:
        current["backlog_automation"] = normalize_automation(backlog_automation)
    if request_fix is not None:
        current["request_fix"] = request_fix
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            UPDATE controls
            SET enabled = %s, dry_run = %s, retrieve = %s, backlog_automation = %s, request_fix = %s
            WHERE id = 1
            """,
            (
                current["enabled"],
                current["dry_run"],
                current["retrieve"],
                _json(current["backlog_automation"]),
                current["request_fix"],
            ),
        )
    return load_controls()


def save_report(repo: str, dry_run: bool, decisions: list[dict]) -> None:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "INSERT INTO batch_reports (repo, dry_run, decisions) VALUES (%s, %s, %s)",
            (repo, dry_run, _json(decisions)),
        )


def latest_unopened() -> list[dict]:
    sheet = latest_sheet()
    if sheet is None:
        return []
    return [item for item in sheet["decisions"] if item.get("action") in {"no_mr", "held", "dry_run"}]


def latest_sheet() -> dict | None:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        row = conn.execute(
            """
            SELECT repo, dry_run, created_at, decisions
            FROM batch_reports ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    created = format_beijing(row[2])
    return {
        "repo": row[0],
        "dry_run": row[1],
        "created_at": created,
        "decisions": with_suggestions(row[3], _snippets()),
    }


def with_suggestions(decisions: list[dict], snippets: dict[tuple[str, str], dict]) -> list[dict]:
    attached = []
    for item in decisions:
        copy = dict(item)
        found = snippets.get((copy.get("rule"), copy.get("path")))
        if found:
            copy["suggestion"] = found
        attached.append(copy)
    return attached


def _snippets() -> dict[tuple[str, str], dict]:
    with psycopg.connect(DB_URI) as conn:
        if conn.execute("SELECT to_regclass('public.issue_suggestions')").fetchone()[0] is None:
            return {}
        rows = conn.execute("SELECT rule, path, old_string, new_string FROM issue_suggestions").fetchall()
    return {
        (rule, path): {"old_string": old, "new_string": new}
        for rule, path, old, new in rows
    }


def _ensure() -> None:
    global _ensured
    if _ensured:
        return
    with _ensure_lock:
        if _ensured:
            return
        _ensure_once()
        _ensured = True


def _ensure_once() -> None:
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS controls (
                id INTEGER PRIMARY KEY,
                enabled BOOLEAN NOT NULL,
                dry_run BOOLEAN NOT NULL,
                whitelist TEXT[] NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO controls (id, enabled, dry_run, whitelist)
            VALUES (1, TRUE, FALSE, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (list(DEFAULT_WHITELIST),),
        )
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS configured BOOLEAN NOT NULL DEFAULT FALSE")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS sonar_url TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS gitlab_url TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS sonar_token TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS gitlab_token TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS gitlab_project_id INTEGER")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS retrieve BOOLEAN NOT NULL DEFAULT FALSE")
        conn.execute(
            "ALTER TABLE controls ADD COLUMN IF NOT EXISTS repo_bindings JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.execute(
            "ALTER TABLE controls ADD COLUMN IF NOT EXISTS backlog_automation JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
        conn.execute(
            "ALTER TABLE controls ADD COLUMN IF NOT EXISTS request_fix BOOLEAN NOT NULL DEFAULT TRUE"
        )
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS github_token TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS azure_token TEXT")
        conn.execute("ALTER TABLE controls ADD COLUMN IF NOT EXISTS llm_token TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_reports (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                repo TEXT NOT NULL,
                dry_run BOOLEAN NOT NULL,
                decisions JSONB NOT NULL
            )
            """
        )


def connect_integration(
    *,
    sonar_url: str,
    sonar_token: str,
    gitlab_token: str,
    whitelist: list[str],
    bindings: list[dict],
    github_token: str = "",
    azure_token: str = "",
    llm_token: str = "",
) -> dict:
    from cleardebt.hosting import HostingError, detect_provider, resolve_repository

    current = _row()
    if not sonar_token:
        sonar_token = current[6] or ""
    if not gitlab_token:
        gitlab_token = current[7] or ""
    if not github_token:
        github_token = (current[13] if len(current) > 13 else None) or ""
    if not azure_token:
        azure_token = (current[14] if len(current) > 14 else None) or ""
    if not llm_token:
        llm_token = (current[15] if len(current) > 15 else None) or ""
    if not sonar_url or not sonar_token:
        raise ValueError("Sonar 地址和令牌都要填")
    if not whitelist:
        raise ValueError("白名单至少要有一个仓库")
    _check_sonar(sonar_url, sonar_token)
    tokens = {"gitlab": gitlab_token, "github": github_token, "azure_devops": azure_token}
    urls = {item["sonar_key"]: (item.get("gitlab_url") or "").strip() for item in bindings}
    previous = {item.get("sonar_key"): item for item in _bindings_from_row(current) if item.get("sonar_key")}
    stored = []
    for key in whitelist:
        url = urls.get(key, "")
        old = previous.get(key) or {}
        if not url:
            stored.append(
                {
                    "sonar_key": key,
                    "gitlab_url": "",
                    "project_id": None,
                    "provider": "",
                    "backlog_fix": old.get("backlog_fix", True),
                    "request_fix": old.get("request_fix", True),
                    "agent_mode": bool(old.get("agent_mode", False)),
                    "read_only": old.get("read_only", False),
                    "automation": old.get("automation") or {},
                }
            )
            continue
        provider = detect_provider(url)
        token = tokens.get(provider) or ""
        try:
            resolved = resolve_repository(url, token, provider)
        except HostingError as error:
            raise ValueError(str(error)) from error
        stored.append(
            {
                "sonar_key": key,
                "gitlab_url": resolved["url"],
                "project_id": resolved["project_id"],
                "project_path": resolved["project_path"],
                "provider": resolved["provider"],
                "backlog_fix": old.get("backlog_fix", True),
                "request_fix": old.get("request_fix", True),
                "agent_mode": bool(old.get("agent_mode", False)),
                "read_only": not bool(token),
                "automation": old.get("automation") or {},
            }
        )
    return save_integration(
        sonar_url=sonar_url,
        sonar_token=sonar_token,
        gitlab_token=gitlab_token,
        whitelist=whitelist,
        bindings=stored,
        github_token=github_token,
        azure_token=azure_token,
        llm_token=llm_token,
    )


def _check_sonar(url: str, token: str) -> None:
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url.rstrip("/") + "/api/system/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise ValueError("连不上 Sonar") from error
    if payload.get("status") != "UP":
        raise ValueError("Sonar 还没就绪")


def _check_gitlab(url: str, token: str) -> int:
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    path = urllib.parse.quote(_project_path(url), safe="")
    parsed = urllib.parse.urlparse(url)
    request = urllib.request.Request(
        f"{parsed.scheme}://{parsed.netloc}/api/v4/projects/{path}",
        headers={"PRIVATE-TOKEN": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ValueError("GitLab 项目打不开，或令牌不够") from error
    except urllib.error.URLError as error:
        raise ValueError("连不上 GitLab") from error
    return int(payload["id"])


def save_integration(
    *,
    sonar_url: str,
    sonar_token: str,
    gitlab_token: str,
    whitelist: list[str],
    bindings: list[dict],
    github_token: str = "",
    azure_token: str = "",
    llm_token: str = "",
) -> dict:
    _ensure()
    if not whitelist:
        raise ValueError("白名单至少要有一个仓库")
    bound = [item for item in bindings if item.get("project_id") and item.get("gitlab_url")]
    legacy_url = bound[0]["gitlab_url"] if bound else None
    raw_id = bound[0]["project_id"] if bound else None
    legacy_id = raw_id if isinstance(raw_id, int) else None
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            """
            UPDATE controls
            SET configured = TRUE,
                sonar_url = %s,
                sonar_token = %s,
                gitlab_url = %s,
                gitlab_token = %s,
                gitlab_project_id = %s,
                whitelist = %s,
                repo_bindings = %s,
                github_token = %s,
                azure_token = %s,
                llm_token = %s
            WHERE id = 1
            """,
            (
                sonar_url.rstrip("/"),
                sonar_token,
                legacy_url,
                gitlab_token,
                legacy_id,
                whitelist,
                _json(bindings),
                github_token or None,
                azure_token or None,
                llm_token or None,
            ),
        )
    return load_controls()


def _row() -> tuple:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        row = conn.execute(
            """
            SELECT enabled, dry_run, whitelist, configured, sonar_url, gitlab_url,
                   sonar_token, gitlab_token, gitlab_project_id, retrieve, repo_bindings,
                   backlog_automation, request_fix, github_token, azure_token, llm_token
            FROM controls WHERE id = 1
            """
        ).fetchone()
    return row


def _bindings_from_row(row) -> list[dict]:
    stored = row[10] if len(row) > 10 else []
    return legacy_bindings(list(row[2] or []), row[5] or "", row[8], stored)


def _automation_from_row(row) -> dict:
    from cleardebt.schedule import normalize_automation

    raw = row[11] if len(row) > 11 else {}
    if isinstance(raw, str):
        import json

        raw = json.loads(raw)
    return normalize_automation(raw or {})


def _project_path(gitlab_url: str) -> str:
    from urllib.parse import urlparse

    parts = [part for part in urlparse(gitlab_url).path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitLab 地址要写成 https://gitlab.com/组/项目")
    return "/".join(parts[:2])


def _json(value: dict | list[dict]):
    from psycopg.types.json import Json

    if isinstance(value, dict):
        return Json(value)
    cleaned = []
    for item in value:
        copy = dict(item)
        copy.pop("issues", None)
        cleaned.append(copy)
    return Json(cleaned)
