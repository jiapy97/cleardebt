import unittest

from cleardebt.controls import with_suggestions
from cleardebt.review import render_page


class ReviewPageTest(unittest.TestCase):
    def test_page_has_switches_sheet_and_suggestion(self):
        sheet = {
            "repo": "toy-js",
            "dry_run": False,
            "created_at": "2026-09-22 18:08",
            "decisions": with_suggestions(
                [
                    {
                        "rule": "javascript:S1128",
                        "action": "already",
                        "level": "L1",
                        "web_url": "https://gitlab.example/1",
                    },
                    {
                        "rule": "javascript:S6679",
                        "path": "src/orders.js",
                        "action": "no_mr",
                        "level": "L2",
                        "reason": "改动的行没有测试覆盖",
                    },
                ],
                {("javascript:S6679", "src/orders.js"): {"old_string": "qty == qty", "new_string": "Number.isNaN(qty)"}},
            ),
        }
        html = render_page(
            sheet,
            {
                "configured": True,
                "enabled": True,
                "dry_run": False,
                "sonar_url": "http://localhost:9000",
                "sonar_token": "",
                "sonar_token_set": True,
                "gitlab_url": "https://gitlab.example/group/test",
                "gitlab_token": "",
                "gitlab_token_set": True,
                "github_token": "",
                "azure_token": "",
                "llm_token": "",
                "llm_token_set": True,
                "binding_lines": "toy-js https://gitlab.example/group/js\ntoy-ts https://gitlab.example/group/ts",
                "whitelist": ["toy-js", "toy-ts"],
                "bindings": [
                    {"sonar_key": "toy-js", "gitlab_url": "https://gitlab.example/group/js", "backlog_fix": True, "request_fix": True},
                    {"sonar_key": "toy-ts", "gitlab_url": "https://gitlab.example/group/ts", "backlog_fix": True, "request_fix": True},
                ],
                "repo_choices": [{"key": "toy-js", "selected": True}, {"key": "toy-ts", "selected": False}],
            },
        )
        self.assertIn("/static/app.css", html)
        self.assertIn("检索旧例子", html)
        self.assertIn("总开关", html)
        self.assertIn("空跑", html)
        self.assertIn("清算单", html)
        self.assertIn("白名单", html)
        self.assertIn("已经开过请求", html)
        self.assertIn("https://gitlab.example/1", html)
        self.assertIn("改动的行没有测试覆盖", html)
        self.assertIn("qty == qty", html)
        self.assertIn("Number.isNaN(qty)", html)
        self.assertIn('name="enabled" value="true" checked', html)
        self.assertNotIn('name="dry_run" value="true" checked', html)
        self.assertIn("toy-ts", html)
        self.assertIn("每个仓库的托管地址", html)
        self.assertIn("GitHub 令牌", html)
        self.assertIn("Azure DevOps 令牌", html)
        self.assertIn("大模型密钥", html)
        self.assertIn("已保存，留空则不变", html)
        self.assertNotIn("sonar-secret", html)
        self.assertNotIn("gitlab-secret", html)
        self.assertIn("https://gitlab.example/group/js", html)
        self.assertIn("https://gitlab.example/group/ts", html)
        self.assertIn("指派给 Agent", html)
        self.assertIn("Agent 活动", html)
        self.assertIn("列出告警", html)
        self.assertIn("请求修复", html)
        self.assertIn("按项目开关", html)
        self.assertIn("覆盖日程", html)
        self.assertIn("运行修复 Agent", html)
        self.assertIn("定时清 backlog", html)
        self.assertIn('action="/schedule"', html)
        self.assertIn("打开自动清 backlog", html)

    def test_suggestion_text_is_escaped(self):
        html = render_page(
            {
                "repo": "toy-js",
                "dry_run": True,
                "created_at": "",
                "decisions": [
                    {
                        "rule": "javascript:S6679",
                        "path": "src/orders.js",
                        "action": "dry_run",
                        "level": "L2",
                        "suggestion": {"old_string": "<script>", "new_string": "ok"},
                    }
                ],
            }
        )
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("text-zinc-100'>&lt;script&gt;</pre>", html.replace('"', "'"))
        self.assertEqual(html.count("<script>"), 1)
        self.assertIn("这一轮是空跑", html)


if __name__ == "__main__":
    unittest.main()
