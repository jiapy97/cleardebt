"""Live rule metadata from Sonar, cached briefly.

Source of truth is the Sonar server itself (`/api/rules/search`): thousands
of rules with severity/type/tags. This module fetches them, caches for
CLEARDEBT_RULES_TTL seconds (default 60), and answers metadata lookups.
Curated pins (tier + Chinese label) live in rules/overrides.json and always
win over the automatic policy. If Sonar is unreachable, pins still work and
everything else reports unknown (fail closed).
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = ROOT / "rules" / "overrides.json"


def _db_uri() -> str:
    from cleardebt.controls import DB_URI

    return DB_URI

_lock = threading.Lock()
_fetched_at = 0.0
_rules: dict[str, dict] = {}
_pins: dict[str, dict] | None = None


def _ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("CLEARDEBT_RULES_TTL", "60")))
    except ValueError:
        return 60.0


def _sonar() -> tuple[str, str]:
    from cleardebt.controls import form_values
    from cleardebt.issue_graph import sonar_base_url

    values = form_values()
    return sonar_base_url(), values.get("sonar_token") or ""


def _api_json(host: str, token: str, path: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        host.rstrip("/") + path + "?" + query,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all(*, languages: str = "") -> dict[str, dict]:
    """Pull every rule from Sonar (paged). Raises on connection trouble."""
    host, token = _sonar()
    out: dict[str, dict] = {}
    page = 1
    while True:
        params = {"ps": 500, "p": page, "f": "name,severity,lang,langName,htmlDesc"}
        if languages:
            params["languages"] = languages
        payload = _api_json(host, token, "/api/rules/search", params)
        for item in payload.get("rules", []):
            key = item.get("key") or ""
            if key:
                out[key] = item
        if page * 500 >= int(payload.get("total", 0)):
            break
        page += 1
    return out


def translate_missing(limit: int = 20) -> int:
    """Machine-translate English labels for unpinned rules; cached in rule_pins.

    Only fills rules with no Chinese label yet and marks them zh_source='mt'
    so a human can spot and correct them in the console. Returns translated
    count. Raises on LLM trouble (caller turns it into a 502).
    """
    from cleardebt.rules import catalog as live_catalog

    live = live_catalog()
    todo: list[tuple[str, str]] = []
    known = pins()
    for key in sorted(live):
        number = key.split(":")[-1]
        if number in known and known[number].get("zh"):
            continue
        name = (live[key].get("name") or "").strip()
        if not name:
            continue
        todo.append((number, name))
        if len(todo) >= limit:
            break
    if not todo:
        return 0
    lines = "\n".join(f"{number} ||| {name}" for number, name in todo)
    prompt = (
        "把下面每一行 Sonar 规则英文名翻译成简短中文（10 个字以内，术语保留原文如 import/NaN/MR）。"
        "只输出 JSON 对象，键是规则号，值是中文。不要解释。\n" + lines
    )
    data = _complete_json(prompt)
    done = 0
    for number, _name in todo:
        zh = (data.get(number) or "").strip()
        if zh:
            save_pin(number, zh=zh, zh_source="mt")
            done += 1
    return done


def _complete_json(prompt: str) -> dict:
    import urllib.request as _request

    from cleardebt.b_fix import _completions_url, llm_credentials

    creds = llm_credentials()
    request = _request.Request(
        _completions_url(creds["base_url"]),
        data=json.dumps(
            {
                "model": creds["model"],
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "只输出一个 JSON 对象，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8"),
        headers={"Authorization": f"Bearer {creds['token']}", "Content-Type": "application/json"},
        method="POST",
    )
    with _request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    data = json.loads(content)
    return data if isinstance(data, dict) else {}


def pins() -> dict[str, dict]:
    """Curated pins: tier + Chinese label, always beat the automatic policy.

    Stored in Postgres (rule_pins) so they are data, not code. On first use
    an empty table is seeded from rules/overrides.json, which is then only
    a historical backup.
    """
    global _pins
    if _pins is not None:
        return _pins
    try:
        with psycopg.connect(_db_uri()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_pins (
                    rule TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT '',
                    zh TEXT NOT NULL DEFAULT '',
                    zh_source TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            rows = conn.execute("SELECT rule, tier, zh, zh_source FROM rule_pins").fetchall()
            if not rows:
                seed = _seed_from_file()
                for number, pin in seed.items():
                    if not isinstance(pin, dict):
                        continue
                    conn.execute(
                        "INSERT INTO rule_pins (rule, tier, zh, zh_source) VALUES (%s, %s, %s, 'seed') "
                        "ON CONFLICT (rule) DO NOTHING",
                        (number, pin.get("tier") or "", pin.get("zh") or ""),
                    )
                rows = conn.execute("SELECT rule, tier, zh, zh_source FROM rule_pins").fetchall()
            _pins = {row[0]: {"tier": row[1], "zh": row[2], "zh_source": row[3]} for row in rows}
    except Exception:
        _pins = _seed_from_file()
    return _pins


def _seed_from_file() -> dict[str, dict]:
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def forget_pins() -> None:
    """Drop the in-memory copy so the next pins() re-reads the table."""
    global _pins
    _pins = None


def save_pin(number: str, *, tier: str = "", zh: str = "", zh_source: str = "manual") -> dict:
    number = (number or "").strip()
    if not number:
        raise ValueError("规则号不能为空。")
    tier = (tier or "").strip().upper()
    if tier and tier not in {"A", "B", "C", ""}:
        raise ValueError("档位只能是 A / B / C / 空（跟随自动策略）。")
    with psycopg.connect(_db_uri()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rule_pins (
                rule TEXT PRIMARY KEY,
                tier TEXT NOT NULL DEFAULT '',
                zh TEXT NOT NULL DEFAULT '',
                zh_source TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        current = pins().get(number, {})
        row = conn.execute(
            """
            INSERT INTO rule_pins (rule, tier, zh, zh_source, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (rule) DO UPDATE SET
                tier = EXCLUDED.tier, zh = EXCLUDED.zh,
                zh_source = EXCLUDED.zh_source, updated_at = now()
            RETURNING rule, tier, zh, zh_source
            """,
            (
                number,
                tier if tier else current.get("tier") or "",
                zh if zh else current.get("zh") or "",
                zh_source if zh else current.get("zh_source") or "",
            ),
        ).fetchone()
    forget_pins()
    return {"rule": row[0], "tier": row[1], "zh": row[2], "zh_source": row[3]}


def refresh(*, languages: str = "") -> dict[str, dict]:
    """Force a live pull; falls back to the previous cache on failure."""
    global _fetched_at, _rules
    fresh = fetch_all(languages=languages)
    with _lock:
        _rules = fresh
        _fetched_at = time.time()
    return fresh


def catalog() -> dict[str, dict]:
    """Cached metadata; refreshes from Sonar when the TTL expired."""
    global _fetched_at, _rules
    with _lock:
        fresh_enough = _rules and (time.time() - _fetched_at) < _ttl()
        cached = _rules
    if fresh_enough:
        return cached
    try:
        return refresh()
    except Exception:
        return cached


def lookup(rule: str) -> dict | None:
    """Metadata for a full key like 'javascript:S107'; None when unknown."""
    key = (rule or "").strip()
    if not key or ":" not in key:
        return None
    return catalog().get(key)


def policy_tier(meta: dict | None) -> str:
    """Automatic tier from Sonar type/severity. Pins are applied by triage."""
    if not meta:
        return "unknown"
    rule_type = (meta.get("type") or "").upper()
    severity = (meta.get("severity") or "").upper()
    if rule_type == "VULNERABILITY" or rule_type == "SECURITY_HOTSPOT":
        return "C"
    if rule_type == "BUG":
        return "C" if severity in {"BLOCKER", "CRITICAL"} else "B"
    if rule_type == "CODE_SMELL":
        return "B"
    return "unknown"
