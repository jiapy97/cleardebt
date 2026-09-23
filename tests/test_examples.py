import unittest
from unittest.mock import MagicMock, patch

from cleardebt.examples import same_rule_examples


class SameRuleExamplesTest(unittest.TestCase):
    def test_only_l1_rows_are_returned(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=("issue_suggestions",))),
            MagicMock(
                fetchall=MagicMock(
                    return_value=[
                        ("javascript:S1128", "a.js", "old-l2", "new-l2", "L2"),
                        ("javascript:S1128", "b.js", "old-l1", "new-l1", "L1"),
                        ("java:S1128", "c.java", "old-java", "new-java", "L1"),
                        ("javascript:S1135", "d.js", "todo", "done", "L1"),
                    ]
                )
            ),
        ]
        with patch("cleardebt.examples.psycopg.connect", return_value=conn):
            found = same_rule_examples("typescript:S1128", limit=5)
        self.assertEqual(
            found,
            [
                {"path": "b.js", "old_string": "old-l1", "new_string": "new-l1"},
                {"path": "c.java", "old_string": "old-java", "new_string": "new-java"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
