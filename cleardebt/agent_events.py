"""Small audit trail for autonomous tool calls; never store raw prompts or source."""

from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Json
from cleardebt.time_display import format_beijing

DB_URI = os.environ.get(
    "CLEARDEBT_DATABASE_URL",
    "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt",
)


def _ensure(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_events (
            id BIGSERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            kind TEXT NOT NULL,
            tool TEXT NOT NULL DEFAULT '',
            call_id TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    conn.execute("ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS call_id TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS agent_events_session_idx ON agent_events(session_id, id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS agent_events_tool_call_idx "
        "ON agent_events(session_id, fingerprint, call_id) WHERE call_id != ''"
    )


def record(session_id: int, fingerprint: str, *, kind: str, tool: str = "", call_id: str = "",
           summary: str = "", details: dict | None = None) -> None:
    if not session_id:
        return
    with psycopg.connect(DB_URI) as conn:
        _ensure(conn)
        conn.execute(
            "INSERT INTO agent_events(session_id, fingerprint, kind, tool, call_id, summary, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (int(session_id), fingerprint, kind[:40], tool[:80], call_id[:160], summary[:500], Json(details or {})),
        )


def list_events(session_id: int, limit: int = 200) -> list[dict]:
    with psycopg.connect(DB_URI) as conn:
        _ensure(conn)
        rows = conn.execute(
            "SELECT id, created_at, fingerprint, kind, tool, summary, details FROM agent_events WHERE session_id = %s ORDER BY id LIMIT %s",
            (int(session_id), _limit(limit)),
        ).fetchall()
    return [_public(row) for row in rows]


def events_for_session(session_id: int, fingerprints: list[str] | None = None, limit: int = 200) -> dict:
    """Events for this session, or the earlier run this session reused.

    A finished checkpoint is not executed again, so a later assignment has a
    decision but no tool rows of its own. Show the rows already stored for
    the same fingerprint instead of an empty trace.
    """
    own = list_events(session_id, limit)
    wanted = [item.strip() for item in (fingerprints or []) if item and item.strip()]
    if own or not wanted:
        return {"events": own, "source_session_ids": []}
    with psycopg.connect(DB_URI) as conn:
        _ensure(conn)
        rows = conn.execute(
            """
            SELECT id, created_at, fingerprint, kind, tool, summary, details, session_id
            FROM agent_events
            WHERE fingerprint = ANY(%s)
            ORDER BY id
            LIMIT %s
            """,
            (wanted, _limit(limit)),
        ).fetchall()
    sources = sorted({int(row[7]) for row in rows if int(row[7]) != int(session_id)})
    return {"events": [_public(row) for row in rows], "source_session_ids": sources}


def _limit(limit: int) -> int:
    return min(max(int(limit), 1), 500)


def _public(row) -> dict:
    return {
        "id": row[0], "created_at": format_beijing(row[1]), "fingerprint": row[2],
        "kind": row[3], "tool": row[4], "summary": row[5], "details": row[6] or {},
    }
