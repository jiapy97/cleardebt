"""Previous same-rule snippets for the context-sensitive tier."""

from __future__ import annotations

import psycopg

from cleardebt.controls import DB_URI
from cleardebt.triage import rule_number


def same_rule_examples(rule: str, limit: int = 3) -> list[dict]:
    number = rule_number(rule)
    with psycopg.connect(DB_URI) as conn:
        if conn.execute("SELECT to_regclass('public.issue_suggestions')").fetchone()[0] is None:
            return []
        rows = conn.execute(
            """
            SELECT rule, path, old_string, new_string
            FROM issue_suggestions
            ORDER BY rule, path
            """
        ).fetchall()
    found = []
    for stored_rule, path, old, new in rows:
        if rule_number(stored_rule) != number or not old or not new or old == new:
            continue
        found.append({"path": path, "old_string": old, "new_string": new})
        if len(found) >= limit:
            break
    return found
