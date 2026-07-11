import unittest

from app.services.llm.providers.base import ProviderContext
from app.services.llm.providers.ollama_provider import OllamaProvider, _extract_content


def _ctx(**overrides) -> ProviderContext:
    defaults: dict = {"mode": "ollama"}
    defaults.update(overrides)
    return ProviderContext(**defaults)


class TestExtractContent(unittest.TestCase):
    def test_extracts_chat_message_content(self) -> None:
        self.assertEqual(_extract_content({"message": {"content": "hi"}}), "hi")

    def test_extracts_generate_response_field(self) -> None:
        self.assertEqual(_extract_content({"response": "hi"}), "hi")

    def test_empty_when_neither_shape_present(self) -> None:
        self.assertEqual(_extract_content({}), "")


class TestOllamaProviderAuthMode(unittest.TestCase):
    """Pre-agreed test seam (v3 ticket 02): adapters are testable by direct construction with a
    fake context (fake key, fake base URL) -- no monkeypatching of any config module needed."""

    def test_local_server_has_no_key_based_auth(self) -> None:
        provider = OllamaProvider(_ctx(ollama_base_url="http://fake-host:11434"))
        self.assertEqual(provider.auth_mode, "local")
        self.assertTrue(provider.is_available)


if __name__ == "__main__":
    unittest.main()
