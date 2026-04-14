import unittest
from unittest.mock import AsyncMock, patch

from app.services import llm_client


class TestLlmClientRouting(unittest.IsolatedAsyncioTestCase):
    async def test_uses_ollama_when_gemini_disabled(self) -> None:
        with patch.object(llm_client, "use_gemini", return_value=False):
            with patch.object(llm_client, "chat_json_ollama", new_callable=AsyncMock) as ollama:
                ollama.return_value = '{"fullName":"A"}'
                out = await llm_client.chat_json("sys", "user", model="mymodel")
                self.assertEqual(out, '{"fullName":"A"}')
                ollama.assert_awaited_once_with("sys", "user", model="mymodel")

    async def test_uses_gemini_when_enabled(self) -> None:
        with patch.object(llm_client, "use_gemini", return_value=True):
            with patch.object(llm_client, "chat_json_gemini", new_callable=AsyncMock) as gem:
                gem.return_value = '{"fullName":"B"}'
                out = await llm_client.chat_json("sys", "user", model="ignored")
                self.assertEqual(out, '{"fullName":"B"}')
                gem.assert_awaited_once_with("sys", "user")


if __name__ == "__main__":
    unittest.main()
