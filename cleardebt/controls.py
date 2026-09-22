"""Operator switches. Stored in Postgres so a restart does not forget them."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)
DEFAULT_WHITELIST = ()


def unbound_reason(repo: str) -> str:
    return f"{repo} 没有对应的 GitLab 项目，这一轮跳过，不去改别的仓库。"


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


def credentials_for(bindings: list[dict], token: str, sonar_key: str | None) -> dict | None:
    if not token:
        return None
    usable = [item for item in bindings if item.get("project_id") and item.get("gitlab_url")]
    if sonar_key:
        chosen = next((item for item in usable if item.get("sonar_key") == sonar_key), None)
    elif len(usable) == 1:
        chosen = usable[0]
    else:
        chosen = None
    if not chosen:
        return None
    url = str(chosen["gitlab_url"]).rstrip("/")
    return {
        "url": url,
        "token": token,
        "project_id": int(chosen["project_id"]),
        "project_path": _project_path(url),
        "remote": url + ".git",
        "sonar_key": chosen.get("sonar_key") or "",
    }


def binding_lines(bindings: list[dict]) -> str:
    lines = []
    for item in bindings:
        key = item.get("sonar_key") or ""
        if not key:
            continue
        url = item.get("gitlab_url") or ""
        lines.append(f"{key} {url}".rstrip())
    return "\n".join(lines)


def gate(settings: dict, repo: str) -> str | None:
    if not settings.get("configured"):
        return "还没填写接入信息，服务碰不到任何仓库。"
    if not settings["enabled"]:
        return "总开关关掉了，这一轮不开始。"
    if repo not in settings["whitelist"]:
        return f"{repo} 不在白名单里，碰不到。"
    return None


def form_values() -> dict:
    row = _row()
    sonar_url = row[4] or "http://localhost:9000"
    gitlab_url = row[5] or ""
    sonar_token = row[6] or _file_token(ROOT / "deploy" / "sonarqube" / ".token")
    gitlab_token = row[7] or _file_token(ROOT / "deploy" / "gitlab" / ".token")
    bindings = _bindings_from_row(row)
    return {
        "configured": row[3],
        "sonar_url": sonar_url,
        "gitlab_url": gitlab_url,
        "sonar_token": sonar_token,
        "gitlab_token": gitlab_token,
        "whitelist": list(row[2]),
        "bindings": [
            {"sonar_key": item.get("sonar_key") or "", "gitlab_url": item.get("gitlab_url") or ""}
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
    return {
        "enabled": row[0],
        "dry_run": row[1],
        "whitelist": list(row[2]),
        "configured": row[3],
        "sonar_url": row[4] or "",
        "gitlab_url": row[5] or "",
        "sonar_token_set": bool(row[6]),
        "gitlab_token_set": bool(row[7]),
        "retrieve": bool(row[9]),
        "bindings": [
            {"sonar_key": item.get("sonar_key") or "", "gitlab_url": item.get("gitlab_url") or ""}
            for item in _bindings_from_row(row)
        ],
    }


def sonar_credentials() -> dict | None:
    row = _row()
    if not row[3] or not row[4] or not row[6]:
        return None
    return {"url": row[4].rstrip("/"), "token": row[6]}


def gitlab_credentials(sonar_key: str | None = None) -> dict | None:
    row = _row()
    if not row[3] or not row[7]:
        return None
    return credentials_for(_bindings_from_row(row), row[7], sonar_key)


def save_controls(
    *,
    enabled: bool | None = None,
    dry_run: bool | None = None,
    retrieve: bool | None = None,
) -> dict:
    current = load_controls()
    if enabled is not None:
        current["enabled"] = enabled
    if dry_run is not None:
        current["dry_run"] = dry_run
    if retrieve is not None:
        current["retrieve"] = retrieve
    with psycopg.connect(DB_URI) as conn:
        conn.execute(
            "UPDATE controls SET enabled = %s, dry_run = %s, retrieve = %s WHERE id = 1",
            (current["enabled"], current["dry_run"], current["retrieve"]),
        )
    return current


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
    created = row[2].astimezone().strftime("%Y-%m-%d %H:%M") if row[2] is not None else ""
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
) -> dict:
    current = _row()
    if not sonar_token:
        sonar_token = current[6] or ""
    if not gitlab_token:
        gitlab_token = current[7] or ""
    if not sonar_url or not sonar_token or not gitlab_token:
        raise ValueError("地址和令牌都要填")
    if not whitelist:
        raise ValueError("白名单至少要有一个仓库")
    _check_sonar(sonar_url, sonar_token)
    urls = {item["sonar_key"]: (item.get("gitlab_url") or "").strip() for item in bindings}
    stored = []
    for key in whitelist:
        url = urls.get(key, "")
        if not url:
            stored.append({"sonar_key": key, "gitlab_url": "", "project_id": None})
            continue
        stored.append(
            {
                "sonar_key": key,
                "gitlab_url": url.rstrip("/"),
                "project_id": _check_gitlab(url, gitlab_token),
            }
        )
    return save_integration(
        sonar_url=sonar_url,
        sonar_token=sonar_token,
        gitlab_token=gitlab_token,
        whitelist=whitelist,
        bindings=stored,
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
) -> dict:
    _ensure()
    if not whitelist:
        raise ValueError("白名单至少要有一个仓库")
    bound = [item for item in bindings if item.get("project_id") and item.get("gitlab_url")]
    legacy_url = bound[0]["gitlab_url"] if bound else None
    legacy_id = bound[0]["project_id"] if bound else None
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
                repo_bindings = %s
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
            ),
        )
    return load_controls()


def _row() -> tuple:
    _ensure()
    with psycopg.connect(DB_URI) as conn:
        row = conn.execute(
            """
            SELECT enabled, dry_run, whitelist, configured, sonar_url, gitlab_url,
                   sonar_token, gitlab_token, gitlab_project_id, retrieve, repo_bindings
            FROM controls WHERE id = 1
            """
        ).fetchone()
    return row


def _bindings_from_row(row) -> list[dict]:
    stored = row[10] if len(row) > 10 else []
    return legacy_bindings(list(row[2] or []), row[5] or "", row[8], stored)


def _project_path(gitlab_url: str) -> str:
    from urllib.parse import urlparse

    parts = [part for part in urlparse(gitlab_url).path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitLab 地址要写成 https://gitlab.com/组/项目")
    return "/".join(parts[:2])


def _json(decisions: list[dict]):
    from psycopg.types.json import Json

    cleaned = []
    for item in decisions:
        copy = dict(item)
        copy.pop("issues", None)
        cleaned.append(copy)
    return Json(cleaned)
