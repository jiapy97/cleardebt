import json
import unittest
from unittest.mock import patch

from cleardebt.hosting import (
    HostingError,
    askpass_username,
    create_request,
    detect_provider,
    load_pull_request,
    post_comment,
    resolve_repository,
)


class HostingDetectTest(unittest.TestCase):
    def test_detect_providers(self):
        self.assertEqual(detect_provider("https://github.com/acme/app"), "github")
        self.assertEqual(
            detect_provider("https://dev.azure.com/acme/proj/_git/app"), "azure_devops"
        )
        self.assertEqual(detect_provider("https://gitlab.com/acme/app"), "gitlab")
        self.assertEqual(askpass_username("github"), "x-access-token")
        self.assertEqual(askpass_username("azure_devops"), "pat")
        self.assertEqual(askpass_username("gitlab"), "oauth2")


class HostingResolveTest(unittest.TestCase):
    def test_resolve_github(self):
        payload = {"full_name": "acme/app", "html_url": "https://github.com/acme/app"}
        with patch("cleardebt.hosting._github_json", return_value=payload):
            resolved = resolve_repository("https://github.com/acme/app", "tok")
        self.assertEqual(resolved["provider"], "github")
        self.assertEqual(resolved["project_id"], "acme/app")
        self.assertEqual(resolved["project_path"], "acme/app")

    def test_resolve_azure(self):
        payload = {"id": "repo-guid"}
        with patch("cleardebt.hosting._azure_json", return_value=payload):
            resolved = resolve_repository(
                "https://dev.azure.com/acme/proj/_git/app", "tok"
            )
        self.assertEqual(resolved["provider"], "azure_devops")
        self.assertEqual(resolved["project_path"], "acme/proj/app")


class HostingCreateTest(unittest.TestCase):
    def test_create_github_pull_request(self):
        saved = {
            "provider": "github",
            "token": "t",
            "project_path": "acme/app",
            "url": "https://github.com/acme/app",
            "project_id": "acme/app",
        }
        with patch(
            "cleardebt.hosting._github_json",
            return_value={"number": 12, "html_url": "https://github.com/acme/app/pull/12"},
        ) as api:
            opened = create_request(
                saved,
                source_branch="cleardebt/fix",
                target_branch="main",
                title="fix",
                description="body",
            )
        self.assertEqual(opened["iid"], 12)
        self.assertEqual(opened["provider"], "github")
        self.assertIn("/pulls", api.call_args.args[1])

    def test_create_azure_pull_request(self):
        saved = {
            "provider": "azure_devops",
            "token": "t",
            "project_path": "acme/proj/app",
            "url": "https://dev.azure.com/acme/proj/_git/app",
            "project_id": "guid",
        }
        with patch(
            "cleardebt.hosting._azure_json",
            return_value={"pullRequestId": 9, "url": "https://dev.azure.com/..."},
        ):
            opened = create_request(
                saved,
                source_branch="cleardebt/fix",
                target_branch="main",
                title="fix",
                description="body",
            )
        self.assertEqual(opened["iid"], 9)
        self.assertEqual(opened["provider"], "azure_devops")
        self.assertIn("pullrequest/9", opened["web_url"])

    def test_create_gitlab_still_works(self):
        saved = {
            "provider": "gitlab",
            "token": "t",
            "project_path": "acme/app",
            "url": "https://gitlab.com/acme/app",
            "project_id": 42,
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"iid": 3, "web_url": "https://gitlab.com/acme/app/-/merge_requests/3"}
                ).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            opened = create_request(
                saved,
                source_branch="cleardebt/fix",
                target_branch="main",
                title="fix",
                description="body",
            )
        self.assertEqual(opened["iid"], 3)
        self.assertEqual(opened["provider"], "gitlab")

    def test_load_github_pull_request(self):
        saved = {
            "provider": "github",
            "token": "t",
            "project_path": "acme/app",
            "url": "https://github.com/acme/app",
        }
        with patch(
            "cleardebt.hosting._github_json",
            return_value={
                "number": 4,
                "title": "feat",
                "html_url": "https://github.com/acme/app/pull/4",
                "head": {"ref": "feature/a"},
                "base": {"ref": "main"},
                "state": "open",
            },
        ):
            loaded = load_pull_request(saved, 4)
        self.assertEqual(loaded["source_branch"], "feature/a")
        self.assertEqual(loaded["target_branch"], "main")
        self.assertEqual(loaded["provider"], "github")

    def test_post_github_and_azure_comments(self):
        github = {
            "provider": "github",
            "token": "t",
            "project_path": "acme/app",
            "url": "https://github.com/acme/app",
        }
        azure = {
            "provider": "azure_devops",
            "token": "t",
            "url": "https://dev.azure.com/acme/proj/_git/app",
        }
        with patch("cleardebt.hosting._github_json", return_value={"id": 11}) as gh:
            note = post_comment(github, 4, "hello")
        self.assertEqual(note, {"id": 11, "provider": "github"})
        self.assertIn("/issues/4/comments", gh.call_args.args[1])
        with patch(
            "cleardebt.hosting._azure_json",
            return_value={"comments": [{"id": 22}]},
        ) as az:
            note = post_comment(azure, 9, "hello")
        self.assertEqual(note, {"id": 22, "provider": "azure_devops"})
        self.assertIn("pullRequests/9/threads", az.call_args.args[1])

    def test_bad_github_url(self):
        with self.assertRaises(HostingError):
            resolve_repository("https://github.com/only", "tok")


if __name__ == "__main__":
    unittest.main()
