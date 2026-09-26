import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cleardebt.agent_jobs import enqueue, job_key
from cleardebt.batch_worker import run_assign_session


class AgentJobsTest(unittest.TestCase):
    def test_job_key_deduplicates_the_same_selection_in_any_order(self):
        a = {"rule": "javascript:S1128", "path": "src/a.js"}
        b = {"rule": "javascript:S1481", "path": "src/b.js"}
        self.assertEqual(job_key("manual", "repo", [a, b]), job_key("manual", "repo", [b, a]))
        self.assertNotEqual(job_key("manual", "repo", [a]), job_key("request_fix", "repo", [a], mr_iid=2))

    def test_enqueue_uses_the_reserved_session_id(self):
        redis = type("Redis", (), {})()
        redis.enqueue_job = AsyncMock(return_value=object())
        redis.aclose = AsyncMock()
        with patch("cleardebt.agent_jobs.create_pool", new=AsyncMock(return_value=redis)):
            asyncio.run(enqueue("run_assign_session", "repo", [], 17, session_id=17))
        self.assertEqual(redis.enqueue_job.call_args.args[0], "run_assign_session")
        self.assertEqual(redis.enqueue_job.call_args.kwargs["_job_id"], "cleardebt-session-17")
        redis.aclose.assert_awaited_once()

    def test_worker_marks_session_running_before_repair(self):
        with (
            patch("cleardebt.assign.session_cancelled", return_value=False),
            patch("cleardebt.assign.mark_running") as running,
            patch("cleardebt.assign.assign_to_agent", return_value={"started": True}) as repair,
        ):
            result = asyncio.run(run_assign_session({}, "repo", [], 17))
        self.assertTrue(result["started"])
        running.assert_called_once_with(17)
        repair.assert_called_once_with("repo", [], session_id=17)


if __name__ == "__main__":
    unittest.main()
