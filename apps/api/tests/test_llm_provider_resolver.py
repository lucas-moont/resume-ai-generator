import unittest

from app.services.llm.provider_resolver import (
    resolve_provider_name,
    resolve_provider_name_for_model,
)


class TestProviderResolver(unittest.TestCase):
    def test_auto_uses_gemini_when_key_is_configured(self) -> None:
        self.assertEqual(resolve_provider_name("auto", "abc123"), "gemini")

    def test_auto_uses_ollama_when_gemini_key_missing(self) -> None:
        self.assertEqual(resolve_provider_name("auto", ""), "ollama")

    def test_none_provider_defaults_to_auto(self) -> None:
        self.assertEqual(resolve_provider_name(None, "abc123"), "gemini")

    def test_explicit_gemini_provider(self) -> None:
        self.assertEqual(resolve_provider_name("gemini", ""), "gemini")

    def test_explicit_ollama_provider(self) -> None:
        self.assertEqual(resolve_provider_name("ollama", "abc123"), "ollama")

    def test_invalid_provider_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_provider_name("invalid-provider", "abc123")

    # --- Claude ---------------------------------------------------------------------------------
    def test_auto_prefers_claude_when_anthropic_key_present(self) -> None:
        self.assertEqual(resolve_provider_name("auto", "gemini-key", "anthropic-key"), "claude")

    def test_auto_falls_back_to_gemini_without_anthropic_key(self) -> None:
        self.assertEqual(resolve_provider_name("auto", "gemini-key", None), "gemini")

    def test_auto_falls_back_to_ollama_without_any_key(self) -> None:
        self.assertEqual(resolve_provider_name("auto", "", ""), "ollama")

    def test_explicit_claude_provider(self) -> None:
        # Explicit claude works even without an env key (local `ant auth login` sets none).
        self.assertEqual(resolve_provider_name("claude", "", ""), "claude")


class TestProviderNameForModel(unittest.TestCase):
    def test_claude_models_route_to_claude(self) -> None:
        self.assertEqual(resolve_provider_name_for_model("claude-sonnet-5"), "claude")
        self.assertEqual(resolve_provider_name_for_model("claude-opus-4-8"), "claude")
        self.assertEqual(resolve_provider_name_for_model("Claude-Haiku-4-5"), "claude")

    def test_gemini_models_route_to_gemini(self) -> None:
        self.assertEqual(resolve_provider_name_for_model("gemini-2.5-flash"), "gemini")

    def test_unknown_or_empty_returns_none(self) -> None:
        self.assertIsNone(resolve_provider_name_for_model("llama3.2"))
        self.assertIsNone(resolve_provider_name_for_model(""))
        self.assertIsNone(resolve_provider_name_for_model(None))


if __name__ == "__main__":
    unittest.main()
