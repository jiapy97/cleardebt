import tempfile
import unittest
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from cleardebt.agent_tools import AgentTools, replay_receipts, sha256
from cleardebt.agent_model import AgentModelError, choose_tool
from cleardebt.issue_graph import agent_model, agent_tool, anti_cheat, build_graph, route_after_agent_tool, run_tests


def _call(number, name, arguments):
    call = {"id": f"call-{number}", "type": "function", "function": {"name": name, "arguments": "{}"}}
    return {
        "assistant": {"role": "assistant", "content": "", "tool_calls": [call]},
        "call_id": call["id"], "name": name, "arguments": arguments,
        "model": "fake-tools", "usage": {"total_tokens": 10},
    }


class AgentToolsTest(unittest.TestCase):
    def test_report_blocker_explains_why_repair_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            result, update = AgentTools({"work_dir": directory}).execute(
                "report_blocker", {"reason": "缺少返回值的业务语义"},
            )
        self.assertTrue(result["ok"])
        self.assertIn("缺少返回值的业务语义", update["model_error"])

    def test_patch_receipt_replays_a_completed_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "work"
            root.mkdir()
            file = root / "a.js"
            file.write_text("const n = 1;\n")
            state = {"work_dir": str(root), "path": "a.js", "changed_files": []}
            args = {"files": [{"path": "a.js", "expected_sha256": sha256(file.read_text()),
                               "edits": [{"old_string": "= 1", "new_string": "= 2"}]}]}
            first, first_update = AgentTools(state, call_id="same-call").execute("apply_patch", args)
            second, second_update = AgentTools(state, call_id="same-call").execute("apply_patch", args)
            self.assertTrue(first["ok"])
            self.assertEqual(second, first)
            self.assertEqual(second_update, first_update)
            self.assertEqual(file.read_text(), "const n = 2;\n")
            shutil.rmtree(root)
            root.mkdir()
            file.write_text("const n = 1;\n")
            replay_receipts(state)
            self.assertEqual(file.read_text(), "const n = 2;\n")

    def test_multi_file_patch_rejects_stale_hash_without_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            one = root / "src" / "one.js"
            two = root / "src" / "two.js"
            one.write_text("const one = 1;\n")
            two.write_text("const two = 2;\n")
            tool = AgentTools({"work_dir": directory, "path": "src/one.js", "changed_files": []})
            result, update = tool.execute("apply_patch", {"files": [
                {"path": "src/one.js", "expected_sha256": sha256(one.read_text()),
                 "edits": [{"old_string": "= 1", "new_string": "= 3"}]},
                {"path": "src/two.js", "expected_sha256": "stale",
                 "edits": [{"old_string": "= 2", "new_string": "= 4"}]},
            ]})
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "stale_file")
            self.assertEqual(update, {})
            self.assertEqual(one.read_text(), "const one = 1;\n")
            self.assertEqual(two.read_text(), "const two = 2;\n")

    def test_tools_refuse_paths_outside_the_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.js").write_text("const a = 1;\n")
            tool = AgentTools({"work_dir": directory, "path": "a.js"})
            for path in ("../outside.js", "/tmp/outside.js", "sub/../../outside.js"):
                result, _ = tool.execute("read_file", {"path": path})
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "invalid_path")


class AgentLoopTest(unittest.TestCase):
    def test_research_limit_offers_patch_or_blocker_and_stops_on_blocker(self):
        state = {"rule": "javascript:S3516", "path": "src/a.js", "agent_research_count": 8,
                 "agent_tool_count": 8}
        offered = []

        def choose(_messages, tools):
            offered.extend(tool["function"]["name"] for tool in tools)
            return _call(9, "report_blocker", {"reason": "无法判断预期返回值"})

        with tempfile.TemporaryDirectory() as directory, \
                patch("cleardebt.agent_model.choose_tool", side_effect=choose):
            selected = agent_model(state)
            after = {**state, **selected, "work_dir": directory}
            after.update(agent_tool(after))
        self.assertEqual(set(offered), {"apply_patch", "report_blocker"})
        self.assertEqual(route_after_agent_tool(after), "decide")
        self.assertIn("无法判断预期返回值", after["model_error"])

    def test_multiple_model_calls_run_sequentially_with_matching_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.js").write_text("const answer = 42;\n")
            first = _call(1, "read_file", {"path": "a.js"})
            second = _call(2, "read_file", {"path": "a.js", "start_line": 1})
            first["assistant"]["tool_calls"].append(second["assistant"]["tool_calls"][0])
            first["pending_calls"] = [{"call_id": second["call_id"], "name": second["name"],
                                       "arguments": second["arguments"]}]
            state = {"work_dir": directory, "path": "a.js", "agent_call": first,
                     "agent_pending_calls": first["pending_calls"], "agent_messages": [], "agent_tool_count": 0}
            after_first = {**state, **agent_tool(state)}
            self.assertEqual(route_after_agent_tool(after_first), "agent_tool")
            self.assertEqual(after_first["agent_call"]["call_id"], "call-2")
            self.assertEqual([x["role"] for x in after_first["agent_messages"]], ["assistant", "tool"])
            after_second = {**after_first, **agent_tool(after_first)}
            self.assertEqual(route_after_agent_tool(after_second), "agent_model")
            self.assertEqual(after_second["agent_tool_count"], 2)
            self.assertEqual([x["role"] for x in after_second["agent_messages"]], ["assistant", "tool", "tool"])
            self.assertEqual([x["tool_call_id"] for x in after_second["agent_messages"][1:]], ["call-1", "call-2"])

    def test_model_failure_is_visible_in_session_events(self):
        state = {"session_id": 7, "fingerprint": "fp", "rule": "javascript:S3516", "path": "src/a.js"}
        with patch("cleardebt.assign.session_cancelled", return_value=False), \
                patch("cleardebt.agent_model.choose_tool", side_effect=AgentModelError("未返回工具调用")), \
                patch("cleardebt.agent_events.record") as record:
            result = agent_model(state)
        self.assertEqual(result["model_error"], "未返回工具调用")
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["kind"], "error")
        self.assertIn("未返回工具调用", record.call_args.kwargs["summary"])

    def test_reused_checkpoint_shows_the_original_tool_events(self):
        from cleardebt.agent_events import events_for_session, record

        fingerprint = "reuse-fingerprint-session-28"
        record(900027, fingerprint, kind="tool", tool="read_file", call_id="reuse-call-1", summary="完成")
        try:
            reused = events_for_session(900028, [fingerprint])
            self.assertEqual(reused["source_session_ids"], [900027])
            self.assertEqual(reused["events"][0]["tool"], "read_file")
            own = events_for_session(900027, [fingerprint])
            self.assertEqual(own["source_session_ids"], [])
            self.assertEqual(own["events"][0]["tool"], "read_file")
        finally:
            import psycopg

            from cleardebt.agent_events import DB_URI

            with psycopg.connect(DB_URI) as conn:
                conn.execute("DELETE FROM agent_events WHERE session_id IN (900027, 900028)")

    def test_model_tool_selection_is_visible_in_session_events(self):
        state = {"session_id": 7, "fingerprint": "fp", "rule": "javascript:S3516", "path": "src/a.js"}
        with patch("cleardebt.assign.session_cancelled", return_value=False), \
                patch("cleardebt.agent_model.choose_tool", return_value=_call(1, "read_file", {"path": "src/a.js"})), \
                patch("cleardebt.agent_events.record") as record:
            result = agent_model(state)
        self.assertEqual(result["agent_call"]["name"], "read_file")
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["kind"], "model")
        self.assertIn("read_file", record.call_args.kwargs["summary"])

    def test_cancellation_stops_selected_tool_before_execution(self):
        state = {"session_id": 7, "agent_call": _call(1, "apply_patch", {})}
        with patch("cleardebt.assign.session_cancelled", return_value=True), \
                patch("cleardebt.agent_tools.AgentTools.execute") as execute:
            result = agent_tool(state)
        execute.assert_not_called()
        self.assertEqual(result["model_error"], "会话已取消。")

    def test_multi_file_checks_include_secondary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coverage").mkdir()
            (root / "coverage" / "coverage-final.json").write_text("{}")
            changed = [
                {"path": "src/a.js", "before": "const a = 1;\n", "after": "const a = 2;\n"},
                {"path": "src/b.js", "before": "const b = 1;\n", "after": "const b = 2;\n"},
            ]
            state = {"rule": "javascript:S1128", "path": "src/a.js", "work_dir": directory,
                     "changed_files": changed}
            with patch("cleardebt.issue_graph.has_node_test_stack", return_value=True), \
                 patch("cleardebt.issue_graph.run_project_tests", return_value=type("Run", (), {"returncode": 0})()), \
                 patch("cleardebt.issue_graph.uncovered_changed_lines", side_effect=[[], [2]]):
                result = run_tests(state)
            self.assertEqual(result["uncovered_lines"], ["src/b.js:2"])
            changed[1]["after"] = "// NOSONAR\nconst b = 2;\n"
            self.assertTrue(anti_cheat(state)["rejections"])

    def test_sonar_failure_is_returned_to_model_then_second_patch_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            file = root / "src" / "a.js"
            file.write_text("export const x = foo();\n")
            scan_calls = {"count": 0}
            seen_messages = []

            def choose(messages, _tools):
                seen_messages.append(messages)
                number = len(seen_messages)
                if number == 1:
                    return _call(number, "read_file", {"path": "src/a.js"})
                if number == 2:
                    return _call(number, "apply_patch", {"files": [{
                        "path": "src/a.js", "expected_sha256": sha256("export const x = foo();\n"),
                        "edits": [{"old_string": "foo()", "new_string": "bar()"}],
                    }]})
                if number == 3:
                    return _call(number, "run_checks", {"level": "full"})
                if number == 4:
                    self.assertIn("原告警仍在", str(messages))
                    return _call(number, "read_file", {"path": "src/a.js"})
                if number == 5:
                    return _call(number, "apply_patch", {"files": [{
                        "path": "src/a.js", "expected_sha256": sha256("export const x = bar();\n"),
                        "edits": [{"old_string": "bar()", "new_string": "baz()"}],
                    }]})
                return _call(number, "run_checks", {"level": "full"})

            def scan(_state):
                scan_calls["count"] += 1
                return {"rescan_ok": scan_calls["count"] > 1, "rescan_removed": [], "rescan_added": [],
                        "history": ["rescan"]}

            state = {
                "fingerprint": "agent-fp", "sonar_fingerprint": "sonar-fp", "rule": "javascript:S1128",
                "path": "src/a.js", "message": "Fix x", "start_line": 1, "end_line": 1,
                "work_dir": directory, "project": "toy-js", "history": [], "rejections": [],
                "rescan_removed": [], "rescan_added": [], "uncovered_lines": [],
            }
            graph = build_graph(MemorySaver(), rescan_node=scan,
                                test_node=lambda _state: {"tests_passed": True, "tests_skipped": False,
                                                          "uncovered_lines": [], "history": ["test"]})
            with (
                patch.dict("os.environ", {"CLEARDEBT_AUTONOMOUS_AGENT": "1"}),
                patch("cleardebt.issue_graph.apply_mechanical", return_value=None),
                patch("cleardebt.agent_model.choose_tool", side_effect=choose),
                patch("cleardebt.triage.listed", return_value=True),
            ):
                result = graph.invoke(state, {"configurable": {"thread_id": "agent-fp"}, "recursion_limit": 70})
            self.assertEqual(result["level"], "L1")
            self.assertEqual(scan_calls["count"], 2)
            self.assertEqual(file.read_text(), "export const x = baz();\n")
            self.assertEqual(result["changed_files"][0]["before"], "export const x = foo();\n")
            self.assertEqual(result["changed_files"][0]["after"], "export const x = baz();\n")
            self.assertEqual(result["agent_tool_count"], 6)

    def test_model_claim_without_tool_cannot_pass(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "修好了"}}]}).encode()

        with patch("cleardebt.agent_model.llm_credentials", return_value={
            "token": "fake", "base_url": "https://example.invalid", "model": "fake",
        }), patch("cleardebt.agent_model.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(AgentModelError):
                choose_tool([{"role": "user", "content": "fix"}], [])

    def test_native_tool_call_is_parsed(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "", "reasoning_content": "consider files", "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"a.js"}'},
                }]}}], "usage": {"total_tokens": 22}}).encode()

        requests = []

        def open_request(request, timeout):
            requests.append(json.loads(request.data))
            return Response()

        with patch("cleardebt.agent_model.llm_credentials", return_value={
            "token": "fake", "base_url": "https://example.invalid", "model": "fake",
        }), patch("cleardebt.agent_model.urllib.request.urlopen", side_effect=open_request), \
                patch.dict("os.environ", {}, clear=True):
            call = choose_tool([{"role": "user", "content": "fix"}], [])
        self.assertEqual(call["name"], "read_file")
        self.assertEqual(call["arguments"], {"path": "a.js"})
        self.assertEqual(call["usage"]["total_tokens"], 22)
        self.assertEqual(call["assistant"]["reasoning_content"], "consider files")
        self.assertEqual(requests[0]["tool_choice"], "required")
        self.assertNotIn("thinking", requests[0])

    def test_malformed_tool_arguments_get_one_bounded_retry(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        requests = []

        def open_request(request, timeout):
            requests.append(json.loads(request.data))
            args = '{"path":' if len(requests) == 1 else '{"path":"a.js"}'
            return Response({"choices": [{"message": {"tool_calls": [{
                "id": f"call-{len(requests)}", "type": "function",
                "function": {"name": "read_file", "arguments": args},
            }]}}], "usage": {"total_tokens": 15}})

        with patch("cleardebt.agent_model.llm_credentials", return_value={
            "token": "fake", "base_url": "https://example.invalid", "model": "fake",
        }), patch("cleardebt.agent_model.urllib.request.urlopen", side_effect=open_request):
            call = choose_tool([{"role": "user", "content": "fix"}], [])
        self.assertEqual(call["arguments"], {"path": "a.js"})
        self.assertEqual(call["usage"]["total_tokens"], 30)
        self.assertEqual(len(requests), 2)
        self.assertIn("完整的 JSON 对象", requests[1]["messages"][-1]["content"])

    def test_multiple_native_tool_calls_are_queued(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.js"}'}},
                    {"id": "call-2", "type": "function", "function": {"name": "get_diff", "arguments": "{}"}},
                ]}}]}).encode()

        with patch("cleardebt.agent_model.llm_credentials", return_value={
            "token": "fake", "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
        }), patch("cleardebt.agent_model.urllib.request.urlopen", return_value=Response()):
            result = choose_tool([{"role": "user", "content": "fix"}], [])
        self.assertEqual(result["name"], "read_file")
        self.assertEqual(result["pending_calls"], [{"call_id": "call-2", "name": "get_diff", "arguments": {}}])
        self.assertEqual(len(result["assistant"]["tool_calls"]), 2)

    def test_deepseek_required_tool_call_uses_non_thinking_mode(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "get_issue_context", "arguments": "{}"},
                }]}}]}).encode()

        requests = []

        def open_request(request, timeout):
            requests.append(json.loads(request.data))
            return Response()

        with patch("cleardebt.agent_model.llm_credentials", return_value={
            "token": "fake", "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
        }), patch("cleardebt.agent_model.urllib.request.urlopen", side_effect=open_request), \
                patch.dict("os.environ", {}, clear=True):
            call = choose_tool([{"role": "user", "content": "fix"}], [])
        self.assertEqual(call["name"], "get_issue_context")
        self.assertEqual(requests[0]["tool_choice"], "required")
        self.assertEqual(requests[0]["thinking"], {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()
