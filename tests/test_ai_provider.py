import unittest
from unittest.mock import patch

from app.core.ai_provider import _normalize_response, request_json


class AIProviderTests(unittest.TestCase):
    def test_normalizes_deepseek_response(self):
        result = _normalize_response(
            "DeepSeek",
            {
                "choices": [{"message": {"content": '{"message":"ok"}'}}],
                "usage": {"total_tokens": 2},
            },
            "deepseek-test",
        )
        self.assertEqual(result["content"]["message"], "ok")

    def test_rejects_non_deepseek_provider_before_network_request(self):
        with patch("app.core.ai_provider._post") as post:
            with self.assertRaisesRegex(ValueError, "supports the DeepSeek API only"):
                request_json("Claude", "key", "model", "system", "user")
        post.assert_not_called()

    def test_rejects_invalid_deepseek_response(self):
        with self.assertRaisesRegex(RuntimeError, "contains no valid text"):
            _normalize_response("DeepSeek", {"choices": []}, "deepseek-test")


if __name__ == "__main__":
    unittest.main()
