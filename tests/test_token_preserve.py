import unittest
from unittest.mock import patch

from cleardebt.controls import connect_integration


class TokenPreserveTest(unittest.TestCase):
    def test_blank_tokens_keep_saved_values(self):
        current = (
            True,  # enabled
            False,  # dry_run
            ["alpha"],  # whitelist
            True,  # configured
            "http://sonar",  # sonar_url
            "https://gitlab.com/acme/alpha",  # gitlab_url
            "sonar-saved",  # sonar_token
            "gitlab-saved",  # gitlab_token
            1,  # project_id
            False,  # retrieve
            [
                {
                    "sonar_key": "alpha",
                    "gitlab_url": "https://gitlab.com/acme/alpha",
                    "project_id": 1,
                    "provider": "gitlab",
                    "backlog_fix": True,
                    "request_fix": True,
                    "agent_mode": True,
                    "automation": {},
                }
            ],
            {},  # backlog_automation
            True,  # request_fix
            "github-saved",
            "azure-saved",
            "llm-saved",
        )
        with (
            patch("cleardebt.controls._row", return_value=current),
            patch("cleardebt.controls._check_sonar"),
            patch(
                "cleardebt.hosting.resolve_repository",
                return_value={
                    "url": "https://gitlab.com/acme/alpha",
                    "project_id": 1,
                    "project_path": "acme/alpha",
                    "provider": "gitlab",
                },
            ),
            patch("cleardebt.controls.save_integration", return_value={}) as save,
        ):
            connect_integration(
                sonar_url="http://sonar",
                sonar_token="",
                gitlab_token="",
                github_token="",
                azure_token="",
                llm_token="",
                whitelist=["alpha"],
                bindings=[{"sonar_key": "alpha", "gitlab_url": "https://gitlab.com/acme/alpha"}],
            )
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["sonar_token"], "sonar-saved")
        self.assertEqual(kwargs["gitlab_token"], "gitlab-saved")
        self.assertEqual(kwargs["github_token"], "github-saved")
        self.assertEqual(kwargs["azure_token"], "azure-saved")
        self.assertEqual(kwargs["llm_token"], "llm-saved")
        self.assertTrue(kwargs["bindings"][0]["agent_mode"])


class SecretFormTest(unittest.TestCase):
    def test_page_does_not_echo_tokens(self):
        from cleardebt.review import render_page

        html = render_page(
            None,
            {
                "configured": True,
                "enabled": True,
                "dry_run": False,
                "sonar_url": "http://localhost:9000",
                "sonar_token": "",
                "sonar_token_set": True,
                "gitlab_token": "",
                "gitlab_token_set": True,
                "github_token": "",
                "github_token_set": False,
                "azure_token": "",
                "azure_token_set": False,
                "llm_token": "",
                "llm_token_set": True,
                "binding_lines": "",
                "repo_choices": [],
                "whitelist": [],
                "bindings": [],
            },
        )
        self.assertNotIn("sonar-secret", html)
        self.assertIn("已保存，留空则不变", html)
        self.assertIn('type="password"', html)
        self.assertIn("大模型密钥", html)


if __name__ == "__main__":
    unittest.main()
