import unittest
from unittest.mock import patch

from cleardebt.controls import backlog_gate, gate, project_switches
from cleardebt.gitlab_mr import render_description
from cleardebt.request_fix import request_fix_gate


READY = {
    "configured": True,
    "enabled": True,
    "whitelist": ["alpha", "beta"],
    "request_fix": True,
    "bindings": [
        {"sonar_key": "alpha", "backlog_fix": True, "request_fix": True},
        {"sonar_key": "beta", "backlog_fix": False, "request_fix": False},
    ],
}


class ProjectSwitchesTest(unittest.TestCase):
    def test_defaults_are_on(self):
        settings = {"configured": True, "enabled": True, "whitelist": ["x"], "request_fix": True, "bindings": []}
        self.assertEqual(project_switches(settings, "x"), {"backlog_fix": True, "request_fix": True})

    def test_global_request_fix_forces_off(self):
        settings = dict(READY, request_fix=False)
        self.assertFalse(project_switches(settings, "alpha")["request_fix"])

    def test_backlog_gate_respects_project_flag(self):
        self.assertIsNone(backlog_gate(READY, "alpha"))
        self.assertIn("backlog 修复关掉了", backlog_gate(READY, "beta"))
        self.assertIsNone(gate(READY, "beta"))

    def test_request_fix_gate_respects_project_flag(self):
        self.assertIsNone(request_fix_gate(READY, "alpha"))
        self.assertIn("请求修复关掉了", request_fix_gate(READY, "beta"))

    def test_description_requires_human_merge(self):
        text = render_description(
            {
                "rule": "javascript:S1128",
                "path": "src/a.js",
                "fingerprint": "fp",
                "rescan_removed": [],
                "rescan_added": [],
                "tests_passed": True,
                "uncovered_lines": [],
            }
        )
        self.assertIn("待审", text)
        self.assertIn("不会自动合并", text)


class ProjectSwitchesApiTest(unittest.TestCase):
    def test_assign_uses_backlog_gate(self):
        from fastapi.testclient import TestClient

        from cleardebt.api import app

        client = TestClient(app)
        with (
            patch("cleardebt.assign.load_controls", return_value=READY),
            patch("cleardebt.assign.backlog_gate", return_value="beta 的 backlog 修复关掉了。") as blocked,
            patch("cleardebt.assign.create_session") as session,
            patch("cleardebt.assign.run_issue.execute") as execute,
        ):
            response = client.post(
                "/issues/assign",
                json={"repo": "beta", "issues": [{"rule": "javascript:S1128", "path": "src/a.js"}]},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("backlog", response.json()["detail"])
        blocked.assert_called_once()
        session.assert_not_called()
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
