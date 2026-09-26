import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cleardebt.api import app


READY = {"configured": True, "enabled": True, "whitelist": ["toy-js"], "dry_run": False}


class ApiTest(unittest.TestCase):
    def test_overview_does_not_echo_saved_tokens(self):
        client = TestClient(app)
        secrets = {
            "sonar_token": "secret-sonar",
            "gitlab_token": "secret-gitlab",
            "github_token": "secret-github",
            "azure_token": "secret-azure",
            "llm_token": "secret-llm",
        }
        with (
            patch("cleardebt.api._form_settings", return_value={"configured": True}),
            patch("cleardebt.controls.form_values", return_value=secrets) as form_values,
        ):
            body = client.get("/api/overview").json()
        for key in ("sonar_token", "gitlab_token", "github_token", "azure_token", "llm_token"):
            self.assertNotIn(key, body)
        form_values.assert_not_called()

    def test_run_opens_a_merge_request_only_after_l1(self):
        client = TestClient(app)
        with (
            patch("cleardebt.api.load_controls", return_value=READY),
            patch("cleardebt.api.run_issue.execute", return_value={"level": "L1", "fingerprint": "fp"}),
            patch(
                "cleardebt.api.open_merge_request.execute",
                return_value={"action": "opened", "web_url": "https://gitlab.example/1"},
            ) as open_mr,
        ):
            response = client.post("/issues/run", params={"repo": "toy-js"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["merge_request"]["action"], "opened")
        open_mr.assert_called_once_with(
            "javascript:S1128",
            "toy-js",
            path=None,
            fingerprint="fp",
        )

    def test_run_does_not_open_a_merge_request_for_l2(self):
        client = TestClient(app)
        with (
            patch("cleardebt.api.load_controls", return_value=READY),
            patch("cleardebt.api.run_issue.execute", return_value={"level": "L2", "fingerprint": "fp"}),
            patch("cleardebt.api.open_merge_request.execute") as open_mr,
        ):
            response = client.post("/issues/run", params={"repo": "toy-js"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["merge_request"])
        open_mr.assert_not_called()

    def test_missing_project_does_not_run(self):
        client = TestClient(app)
        with (
            patch("cleardebt.api.load_controls", return_value=READY),
            patch("cleardebt.api.run_issue.execute") as execute,
        ):
            response = client.post("/issues/run")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["started"])
        self.assertIn("不会跑", response.json()["reason"])
        execute.assert_not_called()

    def test_only_a_whitelisted_project_runs(self):
        client = TestClient(app)
        with (
            patch("cleardebt.api.load_controls", return_value=READY),
            patch("cleardebt.api.run_issue.execute", return_value={"level": "L3", "rule": "javascript:S1481"}) as execute,
        ):
            refused = client.post("/issues/run", params={"repo": "other"})
            accepted = client.post("/issues/run", params={"repo": "toy-js", "rule": "javascript:S1481"})
        self.assertFalse(refused.json()["started"])
        self.assertIn("不在白名单", refused.json()["reason"])
        self.assertTrue(accepted.json()["started"])
        execute.assert_called_once_with("javascript:S1481", "toy-js")

    def test_typed_project_key_joins_the_whitelist(self):
        client = TestClient(app)
        with patch("cleardebt.api.connect_integration", return_value={}) as connect:
            response = client.post(
                "/setup",
                data={
                    "sonar_url": "http://sonar.example",
                    "sonar_token": "sonar-token",
                    "gitlab_token": "gitlab-token",
                    "project_keys": "my-app, other",
                    "bindings": "my-app https://gitlab.com/acme/app\nother https://gitlab.com/acme/other",
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(connect.call_args.kwargs["whitelist"], ["my-app", "other"])
        self.assertEqual(
            connect.call_args.kwargs["bindings"],
            [
                {"sonar_key": "my-app", "gitlab_url": "https://gitlab.com/acme/app"},
                {"sonar_key": "other", "gitlab_url": "https://gitlab.com/acme/other"},
            ],
        )

    def test_a_selected_project_without_an_address_stays_unbound(self):
        client = TestClient(app)
        with patch("cleardebt.api.connect_integration", return_value={}) as connect:
            response = client.post(
                "/setup",
                data={
                    "sonar_url": "http://sonar.example",
                    "sonar_token": "sonar-token",
                    "gitlab_token": "gitlab-token",
                    "whitelist": ["alpha", "orphan"],
                    "bindings": "alpha https://gitlab.com/acme/alpha",
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            connect.call_args.kwargs["bindings"],
            [
                {"sonar_key": "alpha", "gitlab_url": "https://gitlab.com/acme/alpha"},
                {"sonar_key": "orphan", "gitlab_url": ""},
            ],
        )

    def test_switch_form_saves_both_flags(self):
        client = TestClient(app)
        with patch("cleardebt.api.save_controls", return_value={}) as save:
            response = client.post(
                "/switches",
                data={"enabled": "true", "dry_run": "true"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        save.assert_called_once_with(enabled=True, dry_run=True, retrieve=False, request_fix=False)

    def test_unchecked_switches_turn_both_off(self):
        client = TestClient(app)
        with patch("cleardebt.api.save_controls", return_value={}) as save:
            response = client.post("/switches", data={}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        save.assert_called_once_with(enabled=False, dry_run=False, retrieve=False, request_fix=False)

    def test_schedule_form_saves_automation(self):
        client = TestClient(app)
        with patch("cleardebt.api.save_controls", return_value={}) as save:
            response = client.post(
                "/schedule",
                data={
                    "schedule_enabled": "true",
                    "frequency": "weekly",
                    "weekday": "2",
                    "hour": "9",
                    "minute": "30",
                    "timezone": "UTC",
                    "pause_when_open_mrs": "5",
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        save.assert_called_once_with(
            backlog_automation={
                "enabled": True,
                "frequency": "weekly",
                "weekday": "2",
                "hour": "9",
                "minute": "30",
                "timezone": "UTC",
                "pause_when_open_mrs": "5",
            }
        )


if __name__ == "__main__":
    unittest.main()


class RevealTokensTest(unittest.TestCase):
    def test_plaintext_token_reveal_is_not_exposed(self):
        client = TestClient(app)
        response = client.post("/api/tokens/reveal")
        self.assertEqual(response.status_code, 404)
