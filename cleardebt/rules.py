"""Live rule metadata from Sonar, cached briefly.

Source of truth is the Sonar server itself (`/api/rules/search`): thousands
of rules with severity/type/tags. This module fetches them, caches for
CLEARDEBT_RULES_TTL seconds (default 60), and answers metadata lookups.
Chinese labels live in the rule_pins table (manual edits + machine
translations). Rule metadata is not an AI CodeFix eligibility signal;
cleardebt.triage requires an exact-key list separately. If Sonar is
unreachable, the disk cache backs metadata lookups.
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
CACHE_PATH = Path(
    os.environ.get("CLEARDEBT_RULES_CACHE", "").strip() or (ROOT / "var" / "rules_cache.json")
)


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
        params = {"ps": 500, "p": page, "f": "name,severity,cleanCodeAttribute,sysTags,lang,langName,htmlDesc"}
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


def pins() -> dict[str, dict]:
    """Chinese labels for rules: manual edits and machine translations.

    This table is a translation memory ONLY. It used to carry curated tiers
    ('seed' rows); those are deprecated. No row in this table can change a
    tier anymore.
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
            conn.execute(
                "UPDATE rule_pins SET tier = '', zh = '', zh_source = 'deprecated' "
                "WHERE zh_source IN ('seed', 'deprecated') OR tier <> ''"
            )
            rows = conn.execute(
                "SELECT rule, tier, zh, zh_source FROM rule_pins WHERE zh <> ''"
            ).fetchall()
            _pins = {row[0]: {"tier": "", "zh": row[2], "zh_source": row[3]} for row in rows}
    except Exception:
        _pins = {}
    return _pins


def forget_pins() -> None:
    """Drop the in-memory copy so the next pins() re-reads the table."""
    global _pins
    _pins = None


def save_pin(number: str, *, zh: str = "", zh_source: str = "manual") -> dict:
    """Save a Chinese label for a rule; this table is not a tier list."""
    number = (number or "").strip()
    if not number:
        raise ValueError("规则号不能为空。")
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
            VALUES (%s, '', %s, %s, now())
            ON CONFLICT (rule) DO UPDATE SET
                tier = '', zh = EXCLUDED.zh,
                zh_source = EXCLUDED.zh_source, updated_at = now()
            RETURNING rule, tier, zh, zh_source
            """,
            (
                number,
                zh if zh else current.get("zh") or "",
                zh_source if zh else current.get("zh_source") or "",
            ),
        ).fetchone()
    forget_pins()
    return {"rule": row[0], "tier": row[1], "zh": row[2], "zh_source": row[3]}


def _write_cache(rules: dict[str, dict]) -> None:
    # Never persist a near-empty pull (e.g. Sonar mid-restart answers 200
    # with zero rules): a poisoned file would blind every tier decision.
    if len(rules) < 100:
        return
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(rules), encoding="utf-8")
    except OSError:
        pass


def _read_cache() -> dict[str, dict]:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def refresh(*, languages: str = "") -> dict[str, dict]:
    """Force a live pull; falls back to the previous cache on failure."""
    global _fetched_at, _rules
    fresh = fetch_all(languages=languages)
    with _lock:
        _rules = fresh
        _fetched_at = time.time()
    _write_cache(fresh)
    return fresh


def catalog() -> dict[str, dict]:
    """Cached metadata; refreshes from Sonar when the TTL expired."""
    global _fetched_at, _rules
    with _lock:
        if not _rules:
            _rules = _read_cache()
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
