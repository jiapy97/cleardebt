import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cleardebt.api import app
from cleardebt.review import render_page


READY = {"configured": True, "enabled": True, "whitelist": ["toy-js"], "dry_run": False}


class AssignApiTest(unittest.TestCase):
    def test_list_issues_requires_repo(self):
        client = TestClient(app)
        response = client.get("/issues")
        self.assertEqual(response.status_code, 400)

    def test_list_issues_marks_eligibility(self):
        client = TestClient(app)
        rows = [
            {"rule": "javascript:S1128", "component": "toy-js:src/a.js", "message": "unused", "key": "1",
             "type": "CODE_SMELL", "severity": "MINOR",
             "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "LOW"}]},
            {"rule": "javascript:S2077", "component": "toy-js:src/b.js", "message": "sql", "key": "2",
             "type": "VULNERABILITY", "severity": "MAJOR",
             "impacts": [{"softwareQuality": "SECURITY", "severity": "MEDIUM"}]},
        ]
        with (
            patch("cleardebt.assign.load_token", return_value="token"),
            patch("cleardebt.assign.sonar_base_url", return_value="http://sonar"),
            patch("cleardebt.assign.fetch_issues", return_value=rows),
            patch("cleardebt.assign.fetch_dependency_risks", return_value=[]),
            patch(
                "cleardebt.assign.issue_path",
                side_effect=lambda component, project: component.split(":", 1)[-1],
            ),
        ):
            response = client.get("/issues", params={"repo": "toy-js"})
        self.assertEqual(response.status_code, 200)
        issues = response.json()["issues"]
        by_rule = {item["rule"]: item for item in issues}
        self.assertTrue(by_rule["javascript:S1128"]["eligible"])
        self.assertFalse(by_rule["javascript:S2077"]["eligible"])
        self.assertEqual(by_rule["javascript:S1128"]["path"], "src/a.js")

    def test_assign_endpoint_starts_session_in_background(self):
        client = TestClient(app)
        import threading as _threading

        started = _threading.Event()

        def _fake_assign(repo, selections, session_id=None):
            started.set()
            return {"started": True, "session_id": session_id}

        with (
            patch("cleardebt.assign.create_session", return_value=7),
            patch("cleardebt.assign.assign_to_agent", side_effect=_fake_assign),
        ):
            response = client.post(
                "/issues/assign",
                json={"repo": "toy-js", "issues": [{"rule": "javascript:S1128", "path": "src/a.js"}]},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["started"])
        self.assertEqual(body["session_id"], 7)
        self.assertTrue(started.wait(timeout=10))

    def test_assign_worker_runs_path_aware_and_skips_ineligible(self):
        from cleardebt.assign import assign_to_agent
        with (
            patch("cleardebt.assign.load_controls", return_value=READY),
            patch("cleardebt.assign.gate", return_value=None),
            patch("cleardebt.assign.create_session", return_value=7),
            patch("cleardebt.assign.finish_session") as finish,
            patch("cleardebt.assign.save_report") as report,
            patch(
                "cleardebt.assign.run_issue.execute",
                return_value={
                    "level": "L1",
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "fingerprint": "fp",
                    "reason": "ok",
                },
            ) as execute,
            patch(
                "cleardebt.assign.open_merge_request.execute",
                return_value={"action": "opened", "web_url": "https://gitlab.example/1"},
            ) as open_mr,
        ):
            body = assign_to_agent(
                "toy-js",
                [
                    {"rule": "javascript:S1128", "path": "src/a.js"},
                    {"rule": "javascript:S2077", "path": "src/b.js"},
                ],
                session_id=7,
            )
        self.assertTrue(body["started"])
        self.assertEqual(body["session_id"], 7)

    def test_assign_respects_dry_run(self):
        client = TestClient(app)
        dry = dict(READY, dry_run=True)
        with (
            patch("cleardebt.assign.load_controls", return_value=dry),
            patch("cleardebt.assign.gate", return_value=None),
            patch("cleardebt.assign.create_session", return_value=1),
            patch("cleardebt.assign.finish_session"),
            patch("cleardebt.assign.save_report"),
            patch(
                "cleardebt.assign.run_issue.execute",
                return_value={
                    "level": "L1",
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "fingerprint": "fp",
                },
            ),
            patch("cleardebt.assign.open_merge_request.execute") as open_mr,
        ):
            from cleardebt.assign import assign_to_agent

            body = assign_to_agent(
                "toy-js", [{"rule": "javascript:S1128", "path": "src/a.js"}], session_id=1
            )
        self.assertEqual(body["decisions"][0]["action"], "dry_run")
        open_mr.assert_not_called()

    def test_page_shows_assign_and_activity(self):
        html = render_page(
            None,
            {
                "configured": True,
                "enabled": True,
                "dry_run": False,
                "repo_choices": [{"key": "toy-js", "selected": True}],
            },
            issues=[
                {
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "message": "unused import",
                    "eligible": True,
                },
                {
                    "rule": "javascript:S2077",
                    "path": "src/b.js",
                    "message": "sql",
                    "eligible": False,
                },
            ],
            sessions=[
                {
                    "id": 1,
                    "created_at": "2026-09-22 10:00",
                    "source": "manual",
                    "status": "completed",
                    "repo": "toy-js",
                    "issue_count": 1,
                    "details": {},
                    "finished_at": "2026-09-22 10:01",
                },
                {
                    "id": 2,
                    "created_at": "2026-09-22 08:00",
                    "source": "scheduled",
                    "status": "running",
                    "repo": "toy-js",
                    "issue_count": 3,
                    "details": {},
                    "finished_at": "",
                },
            ],
            assign_repo="toy-js",
        )
        self.assertIn("指派给 Agent", html)
        self.assertIn("Agent 活动", html)
        self.assertIn("列出告警", html)
        self.assertIn("javascript:S1128", html)
        self.assertIn("跳过", html)
        self.assertIn("手动指派", html)
        self.assertIn("定时", html)
        self.assertIn("完成", html)
        self.assertIn("运行", html)


if __name__ == "__main__":
    unittest.main()
