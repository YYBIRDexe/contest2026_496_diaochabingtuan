import json
import unittest

from cloud_agent.errors import LLMError
from cloud_agent.llm import OpenAIClient

from tests.helpers import make_config, temp_dir


class LLMAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)

    def test_endpoint_and_request_payload(self):
        config = make_config(self.tmp)
        captured = {}

        def transport(url, headers, body, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json.loads(body.decode("utf-8"))
            captured["timeout"] = timeout
            return (
                200,
                {},
                json.dumps(
                    {
                        "model": "test-model",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                    }
                ).encode("utf-8"),
            )

        client = OpenAIClient(config, transport=transport)
        result = client.complete(
            [{"role": "user", "content": "hi"}],
            [{"type": "function", "function": {"name": "x", "parameters": {}}}],
        )
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-secret-key")
        self.assertEqual(captured["body"]["model"], "test-model")
        self.assertEqual(captured["body"]["tool_choice"], "auto")
        self.assertEqual(captured["body"]["messages"][0]["content"], "hi")
        self.assertEqual(result["message"]["content"], "ok")
        self.assertEqual(result["usage"]["prompt_tokens"], 3)

    def test_tool_calls_response_is_preserved(self):
        config = make_config(self.tmp)
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_capabilities",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        client = OpenAIClient(
            config,
            transport=lambda *args: (200, {}, json.dumps(payload).encode("utf-8")),
        )
        result = client.complete([{"role": "user", "content": "capabilities"}], [{"type": "function"}])
        self.assertEqual(result["message"]["content"], "")
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["name"], "get_capabilities")

    def test_deepseek_disables_thinking_only_for_its_endpoint(self):
        response = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]
            }
        ).encode("utf-8")

        def body_for(base_url):
            config = make_config(self.tmp)
            config.base_url = base_url
            captured = {}

            def transport(url, headers, body, timeout):
                captured["body"] = json.loads(body.decode("utf-8"))
                return 200, {}, response

            OpenAIClient(config, transport=transport).complete(
                [{"role": "user", "content": "hi"}], []
            )
            return captured["body"]

        deepseek = body_for("https://api.deepseek.com")
        self.assertEqual(deepseek["thinking"], {"type": "disabled"})
        other = body_for("https://example.test/v1")
        self.assertNotIn("thinking", other)

    def test_base_url_ending_in_chat_completions_is_not_doubled(self):
        config = make_config(self.tmp)
        config.base_url = "https://example.test/v1/chat/completions"
        client = OpenAIClient(config, transport=lambda *args: (200, {}, b"{}"))
        self.assertEqual(client.endpoint, "https://example.test/v1/chat/completions")

    def test_http_401_maps_to_auth_error_and_redacts_key(self):
        config = make_config(self.tmp)
        client = OpenAIClient(
            config,
            transport=lambda *args: (
                401,
                {},
                json.dumps({"error": {"message": "bad key test-secret-key"}}).encode("utf-8"),
            ),
        )
        with self.assertRaises(LLMError) as context:
            client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(context.exception.code, "llm_auth_failed")
        self.assertNotIn("test-secret-key", json.dumps(context.exception.to_dict(), ensure_ascii=False))

    def test_invalid_json_response_is_an_error(self):
        config = make_config(self.tmp)
        client = OpenAIClient(config, transport=lambda *args: (200, {}, b"not json"))
        with self.assertRaises(LLMError) as context:
            client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(context.exception.code, "llm_invalid_response")

    def test_unconfigured_client_raises_configuration_error(self):
        from cloud_agent.errors import ConfigurationError

        config = make_config(self.tmp, configured=False)
        client = OpenAIClient(config, transport=lambda *args: (200, {}, b"{}"))
        with self.assertRaises(ConfigurationError):
            client.complete([{"role": "user", "content": "hi"}], [])


if __name__ == "__main__":
    unittest.main()
