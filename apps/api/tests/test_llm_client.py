import unittest
from unittest.mock import AsyncMock, patch

from app.services import llm_client


class TestLlmClientRouting(unittest.IsolatedAsyncioTestCase):
    async def test_chat_json_routes_to_resolved_provider(self) -> None:
        provider = AsyncMock()
        provider.chat_json = AsyncMock(return_value='{"fullName":"A"}')
        provider.name = "ollama"
        with patch.object(llm_client, "resolve_active_provider", return_value=provider):
            out = await llm_client.chat_json("sys", "user", model="mymodel")
            self.assertEqual(out, '{"fullName":"A"}')
            provider.chat_json.assert_awaited_once_with("sys", "user", model_override="mymodel")

    def test_backend_label_uses_resolved_provider_name(self) -> None:
        provider = AsyncMock()
        provider.name = "gemini"
        with patch.object(llm_client, "resolve_active_provider", return_value=provider):
            self.assertEqual(llm_client.llm_backend_label(), "gemini")


if __name__ == "__main__":
    unittest.main()
