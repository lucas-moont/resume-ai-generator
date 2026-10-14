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


class TestEffectiveModelId(unittest.TestCase):
    """What gets recorded as the model of a call. A request with no model used to be stored as
    NULL, so a change of default left no trace of which model wrote a resume."""

    def test_an_explicit_model_is_recorded_as_is(self) -> None:
        self.assertEqual(llm_client.effective_model_id("claude-fable-5-1"), "claude-fable-5-1")

    def test_no_model_records_the_active_providers_default(self) -> None:
        with patch.object(llm_client, "resolve_active_provider_name", return_value="claude"), patch.dict(
            llm_client._DEFAULT_MODEL_RESOLVERS, {"claude": lambda: "claude-opus-5-5"}
        ):
            self.assertEqual(llm_client.effective_model_id(None), "claude-opus-5-5")
            self.assertEqual(llm_client.effective_model_id("  "), "claude-opus-5-5")

    def test_the_configured_ai_default_model_wins_over_the_provider_default(self) -> None:
        runtime = llm_client.config_module.get_runtime_config()
        with patch.object(
            llm_client.config_module,
            "get_runtime_config",
            return_value=runtime.__class__(**{**runtime.__dict__, "ai_default_model": "gemini-2.5-flash"}),
        ):
            self.assertEqual(llm_client.effective_model_id(None), "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
