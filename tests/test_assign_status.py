import unittest
from unittest.mock import MagicMock, patch

from cleardebt.assign import issue_status_map
from cleardebt.review import render_page


def _fake_conn(suggestions, mrs, direct=()):
    conn = MagicMock()
    cursor = MagicMock()
    state = {}

    def _execute(sql, *args):
        state["sql"] = sql
        return cursor

    def _fetchall():
        sql = state.get("sql") or ""
        if "FROM issue_suggestions" in sql:
            return suggestions
        if "fingerprint = ANY" in sql:
            return mrs
        return list(direct)

    cursor.execute.side_effect = _execute
    cursor.fetchall.side_effect = _fetchall
    conn.__enter__.return_value = cursor
    conn.__exit__.return_value = False
    return conn


class IssueStatusMapTest(unittest.TestCase):
    def test_joins_suggestion_with_mr_link(self):
        suggestions = [("fp1", "javascript:S1128", "src/a.js", "L1", "ok")]
        mrs = [("fp1", "http://git/mr/1")]
        with patch("cleardebt.assign.psycopg.connect", return_value=_fake_conn(suggestions, mrs)):
            out = issue_status_map([("javascript:S1128", "src/a.js")])
        self.assertEqual(out[("javascript:S1128", "src/a.js")]["level"], "L1")
        self.assertEqual(out[("javascript:S1128", "src/a.js")]["mr_url"], "http://git/mr/1")

    def test_direct_mr_match_without_suggestion(self):
        direct = [("javascript:S1128", "src/a.js", "http://git/mr/1")]
        with patch("cleardebt.assign.psycopg.connect", return_value=_fake_conn([], [], direct)):
            out = issue_status_map([("javascript:S1128", "src/a.js")])
        self.assertEqual(out[("javascript:S1128", "src/a.js")]["mr_url"], "http://git/mr/1")

    def test_db_failure_returns_empty_not_raise(self):
        with patch("cleardebt.assign.psycopg.connect", side_effect=RuntimeError("down")):
            self.assertEqual(issue_status_map([("javascript:S1128", "src/a.js")]), {})

    def test_render_shows_status_column(self):
        html = render_page(
            None,
            {},
            issues=[
                {
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "message": "unused",
                    "eligible": True,
                    "status": {"level": "L1", "reason": "ok", "mr_url": "http://git/mr/1"},
                },
                {
                    "rule": "javascript:S3649",
                    "path": "src/b.js",
                    "message": "sql",
                    "eligible": False,
                    "status": None,
                },
            ],
            assign_repo="toy-js",
        )
        self.assertIn("最新状态", html)
        self.assertIn("已开请求", html)
        self.assertIn("http://git/mr/1", html)
        self.assertIn("待处理", html)

    def test_render_shows_assign_notice(self):
        html = render_page(None, {}, issues=[], assign_repo="toy-js", assign_notice="已指派 2 条。")
        self.assertIn("已指派 2 条", html)


if __name__ == "__main__":
    unittest.main()
