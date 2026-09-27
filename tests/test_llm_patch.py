import os
import unittest
from unittest.mock import patch

from cleardebt.b_fix import (
    ModelOutputError,
    build_patch_prompt,
    llm_credentials,
    mechanical_fix_enabled,
    parse_replacement,
    propose_patch,
)


class LlmPatchProtocolTest(unittest.TestCase):
    def test_rejects_a_claim_that_it_is_fixed(self):
        with self.assertRaises(ModelOutputError):
            parse_replacement('{"old_string": "a", "new_string": "b", "fixed": true}')

    def test_prompt_forbids_self_declaring_fixed(self):
        prompt = build_patch_prompt(
            rule="javascript:S1128",
            description="未使用的 import",
            source='import x from "y";\nexport const a = 1;\n',
            path="src/a.js",
            message="Remove this unused import of 'x'.",
        )
        self.assertIn("不能声称已经修好", prompt)
        self.assertIn("javascript:S1128", prompt)
        self.assertIn("未使用的 import", prompt)
        self.assertIn('import x from "y";', prompt)

    def test_secret_prompt_asks_for_env_not_new_key(self):
        prompt = build_patch_prompt(
            rule="javascript:S2068",
            description="硬编码密钥",
            source='const password = "hunter2";\n',
            path="src/auth.js",
            message="hardcoded password",
        )
        self.assertIn("密钥类", prompt)
        self.assertIn("环境变量", prompt)
        self.assertIn("不要编造新的真实密钥", prompt)

    def test_credentials_prefer_cleardebt_llm_key(self):
        with patch.dict(
            os.environ,
            {
                "CLEARDEBT_LLM_API_KEY": "from-cleardebt",
                "DEEPSEEK_API_KEY": "from-deepseek",
                "CLEARDEBT_LLM_BASE_URL": "https://llm.example/v1",
                "CLEARDEBT_LLM_MODEL": "my-model",
            },
            clear=False,
        ):
            creds = llm_credentials()
        self.assertEqual(creds["token"], "from-cleardebt")
        self.assertEqual(creds["base_url"], "https://llm.example/v1")
        self.assertEqual(creds["model"], "my-model")

    def test_missing_key_is_a_model_output_error(self):
        env = {key: value for key, value in os.environ.items() if key not in {
            "CLEARDEBT_LLM_API_KEY",
            "LLM_API_KEY",
            "DEEPSEEK_API_KEY",
        }}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("cleardebt.b_fix._file_token", return_value=""),
            patch("cleardebt.b_fix._db_llm_token", return_value=""),
        ):
            with self.assertRaises(ModelOutputError) as caught:
                llm_credentials()
        self.assertIn("大模型密钥", str(caught.exception))

    def test_mechanical_fix_is_off_by_default(self):
        with patch.dict(os.environ, {"CLEARDEBT_MECHANICAL_FIX": ""}, clear=False):
            self.assertFalse(mechanical_fix_enabled())

    def test_prompt_includes_nearby_evidence(self):
        prompt = build_patch_prompt(
            rule="javascript:S1128",
            description="未使用的 import",
            source='import x from "y";\nexport const a = 1;\n',
            path="src/a.js",
            message="Remove this unused import of 'x'.",
            evidence={
                "nearby": '1|import x from "y";',
                "name": "x",
                "occurrences": [{"line": 1, "text": "import x"}],
            },
        )
        self.assertIn("告警附近代码", prompt)
        self.assertIn("1|import x", prompt)
        self.assertIn("名字：x", prompt)

    def test_propose_patch_posts_to_the_configured_endpoint(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"old_string\\":\\"a\\",\\"new_string\\":\\"b\\"}"}}],"usage":{"total_tokens":37}}'

        observed = []
        with (
            patch.dict(
                os.environ,
                {
                    "CLEARDEBT_LLM_API_KEY": "k",
                    "CLEARDEBT_LLM_BASE_URL": "https://llm.example",
                    "CLEARDEBT_LLM_MODEL": "m",
                },
                clear=False,
            ),
            patch("cleardebt.b_fix.urllib.request.urlopen", return_value=Response()) as urlopen,
        ):
            old, new = propose_patch(
                rule="javascript:S1128",
                source="a\n",
                path="src/a.js",
                message="unused",
                on_usage=observed.append,
            )
        self.assertEqual((old, new), ("a", "b"))
        self.assertEqual(observed, [37])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://llm.example/chat/completions")
        self.assertIn("Bearer k", request.headers["Authorization"])

    def test_fixed_model_timeout_is_a_scored_model_failure(self):
        with (
            patch.dict(os.environ, {"CLEARDEBT_LLM_API_KEY": "k"}, clear=False),
            patch("cleardebt.b_fix.urllib.request.urlopen", side_effect=TimeoutError("timed out")),
        ):
            with self.assertRaisesRegex(ModelOutputError, "模型请求失败"):
                propose_patch(rule="javascript:S1128", source="a\n", path="src/a.js")


if __name__ == "__main__":
    unittest.main()
