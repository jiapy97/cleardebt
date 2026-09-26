import unittest
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from cleardebt.api import app
from cleardebt.request_fix import list_mr_issues, remediate_merge_request, request_fix_gate


READY = {
    "configured": True,
    "enabled": True,
    "whitelist": ["toy-js"],
    "dry_run": False,
    "request_fix": True,
}


class RequestFixTest(unittest.TestCase):
    def test_mr_issue_list_uses_issue_level_triage(self):
        mr = {"repo": "toy-js", "mr_iid": 42}
        sonar_issue = {
            "rule": "javascript:S1128", "component": "toy-js:src/a.js", "key": "issue-1",
            "type": "CODE_SMELL", "severity": "MAJOR",
            "impacts": [{"softwareQuality": "MAINTAINABILITY", "severity": "HIGH"}],
        }
        with (
            patch("cleardebt.request_fix.load_merge_request", return_value=mr),
            patch("cleardebt.request_fix.load_token", return_value="token"),
            patch("cleardebt.request_fix.sonar_base_url", return_value="http://sonar"),
            patch("cleardebt.request_fix.fetch_issues", return_value=[sonar_issue]),
            patch("cleardebt.request_fix.describe_message", return_value="告警"),
            patch("cleardebt.triage.listed", return_value=False),
        ):
            row = list_mr_issues("toy-js", 42)["issues"][0]
        self.assertEqual(row["tier"], "skip")
        self.assertFalse(row["eligible"])

    def test_remediate_endpoint_returns_before_worker_finishes(self):
        client = TestClient(app)
        entered = Event()
        release = Event()

        def slow_remediate(*args, **kwargs):
            entered.set()
            release.wait(timeout=10)

        with (
            patch("cleardebt.api.load_controls", return_value=READY),
            patch("cleardebt.request_fix.request_fix_gate", return_value=None),
            patch("cleardebt.assign.create_session", return_value=91),
            patch("cleardebt.request_fix.remediate_merge_request", side_effect=slow_remediate) as run,
        ):
            try:
                response = client.post("/mrs/remediate", json={
                    "repo": "toy-js", "mr_iid": 42,
                    "issues": [{"rule": "javascript:S1128", "path": "src/a.js", "sonar_key": "issue-1"}],
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["session_id"], 91)
                self.assertTrue(entered.wait(timeout=2))
                self.assertFalse(release.is_set())
                duplicate = client.post("/mrs/remediate", json={
                    "repo": "toy-js", "mr_iid": 42,
                    "issues": [{"rule": "javascript:S1128", "path": "src/a.js", "sonar_key": "issue-1"}],
                })
                self.assertTrue(duplicate.json()["already_running"])
                run.assert_called_once_with(
                    "toy-js", 42,
                    [{"rule": "javascript:S1128", "path": "src/a.js", "sonar_key": "issue-1"}],
                    session_id=91,
                )
            finally:
                release.set()
                from cleardebt.api import _mr_threads
                _mr_threads[("toy-js", 42)].join(timeout=2)

    def test_gate_requires_request_fix_flag(self):
        self.assertIsNone(request_fix_gate(READY, "toy-js"))
        self.assertIn(
            "请求修复关掉了",
            request_fix_gate(dict(READY, request_fix=False), "toy-js"),
        )

    def test_remediate_opens_mr_against_source_branch(self):
        mr = {
            "repo": "toy-js",
            "mr_iid": 42,
            "title": "feature",
            "web_url": "https://gitlab.example/mr/42",
            "source_branch": "feature/login",
            "target_branch": "main",
            "state": "opened",
            "project_id": 1,
            "gitlab_url": "https://gitlab.example/g/one",
            "token": "t",
        }
        with (
            patch("cleardebt.request_fix.load_controls", return_value=READY),
            patch("cleardebt.request_fix.request_fix_gate", return_value=None),
            patch("cleardebt.request_fix.load_merge_request", return_value=mr),
            patch("cleardebt.request_fix.list_mr_issues", return_value={"issues": [
                {"rule": "javascript:S1128", "path": "src/a.js", "sonar_key": "issue-42", "eligible": True},
            ]}),
            patch("cleardebt.request_fix.create_session", return_value=9),
            patch("cleardebt.request_fix.finish_session") as finish,
            patch("cleardebt.request_fix.save_report"),
            patch(
                "cleardebt.request_fix.run_issue.execute",
                return_value={
                    "level": "L1",
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "fingerprint": "fp-mr",
                },
            ) as execute,
            patch(
                "cleardebt.request_fix.open_merge_request.execute",
                return_value={
                    "action": "opened",
                    "web_url": "https://gitlab.example/mr/99",
                    "source_branch": "cleardebt/s1128-fp",
                    "target_branch": "feature/login",
                },
            ) as open_mr,
        ):
            body = remediate_merge_request(
                "toy-js", 42, [{"rule": "javascript:S1128", "path": "src/a.js", "sonar_key": "issue-42"}]
            )
        self.assertTrue(body["started"])
        self.assertEqual(body["source"], "request_fix")
        self.assertEqual(body["merge_request"]["source_branch"], "feature/login")
        execute.assert_called_once_with(
            "javascript:S1128",
            "toy-js",
            path="src/a.js",
            git_branch="feature/login",
            pull_request="42",
            issue_key="issue-42",
        )
        open_mr.assert_called_once()
        kwargs = open_mr.call_args.kwargs
        self.assertEqual(kwargs["target_branch"], "feature/login")
        self.assertEqual(kwargs["fingerprint"], "fp-mr")
        self.assertEqual(body["decisions"][0]["target_branch"], "feature/login")
        self.assertEqual(body["decisions"][0]["action"], "opened")
        finish.assert_called_once()

    def test_remediate_respects_dry_run(self):
        dry = dict(READY, dry_run=True)
        mr = {
            "repo": "toy-js",
            "mr_iid": 7,
            "source_branch": "feature/x",
            "target_branch": "main",
            "web_url": "",
            "title": "",
            "state": "opened",
            "project_id": 1,
            "gitlab_url": "https://gitlab.example/g/one",
            "token": "t",
        }
        with (
            patch("cleardebt.request_fix.load_controls", return_value=dry),
            patch("cleardebt.request_fix.request_fix_gate", return_value=None),
            patch("cleardebt.request_fix.load_merge_request", return_value=mr),
            patch("cleardebt.request_fix.list_mr_issues", return_value={"issues": [
                {"rule": "javascript:S1128", "path": "src/a.js", "eligible": True},
            ]}),
            patch("cleardebt.request_fix.create_session", return_value=1),
            patch("cleardebt.request_fix.finish_session"),
            patch("cleardebt.request_fix.save_report"),
            patch(
                "cleardebt.request_fix.run_issue.execute",
                return_value={
                    "level": "L1",
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "fingerprint": "fp",
                },
            ),
            patch("cleardebt.request_fix.open_merge_request.execute") as open_mr,
        ):
            body = remediate_merge_request(
                "toy-js", 7, [{"rule": "javascript:S1128", "path": "src/a.js"}]
            )
        self.assertEqual(body["decisions"][0]["action"], "dry_run")
        open_mr.assert_not_called()

    def test_offer_posts_note(self):
        client = TestClient(app)
        listed = {
            "merge_request": {
                "repo": "toy-js",
                "mr_iid": 3,
                "source_branch": "feature/y",
                "title": "t",
                "web_url": "u",
                "target_branch": "main",
                "state": "opened",
                "provider": "gitlab",
            },
            "issues": [
                {
                    "rule": "javascript:S1128",
                    "path": "src/a.js",
                    "message": "unused",
                    "eligible": True,
                }
            ],
        }
        with (
            patch("cleardebt.request_fix.load_controls", return_value=READY),
            patch("cleardebt.request_fix.request_fix_gate", return_value=None),
            patch("cleardebt.request_fix.list_mr_issues", return_value=listed),
            patch(
                "cleardebt.request_fix.gitlab_credentials",
                return_value={
                    "project_id": 1,
                    "token": "t",
                    "url": "https://gitlab.example/g/one",
                    "provider": "gitlab",
                },
            ),
            patch(
                "cleardebt.hosting.post_comment",
                return_value={"id": 88, "provider": "gitlab"},
            ) as note,
        ):
            response = client.post("/mrs/offer", json={"repo": "toy-js", "mr_iid": 3})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["posted"])
        self.assertEqual(response.json()["note_id"], 88)
        self.assertEqual(response.json()["provider"], "gitlab")
        note.assert_called_once()
        self.assertEqual(note.call_args.args[1], 3)

    def test_offer_posts_github_comment(self):
        client = TestClient(app)
        listed = {
            "merge_request": {
                "repo": "toy-js",
                "mr_iid": 15,
                "source_branch": "feature/z",
                "title": "t",
                "web_url": "https://github.com/acme/app/pull/15",
                "target_branch": "main",
                "state": "open",
                "provider": "github",
            },
            "issues": [],
        }
        saved = {
            "provider": "github",
            "token": "t",
            "project_path": "acme/app",
            "project_id": "acme/app",
            "url": "https://github.com/acme/app",
        }
        with (
            patch("cleardebt.request_fix.load_controls", return_value=READY),
            patch("cleardebt.request_fix.request_fix_gate", return_value=None),
            patch("cleardebt.request_fix.list_mr_issues", return_value=listed),
            patch("cleardebt.request_fix.gitlab_credentials", return_value=saved),
            patch(
                "cleardebt.hosting.post_comment",
                return_value={"id": 501, "provider": "github"},
            ) as note,
        ):
            response = client.post("/mrs/offer", json={"repo": "toy-js", "mr_iid": 15})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "github")
        note.assert_called_once_with(saved, 15, note.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
