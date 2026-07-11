import unittest

import httpx

from app.services.llm.providers.base import ProviderContext
from app.services.llm.providers.ollama_provider import (
    OllamaProvider,
    _extract_content,
    _parse_ollama_response,
)


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


class TestParseOllamaResponse(unittest.TestCase):
    """Mirrors Gemini's explicit json.JSONDecodeError guard: a 200 response with a non-JSON
    body must raise a clear RuntimeError instead of an unhandled JSONDecodeError."""

    def test_extracts_content_from_a_valid_json_response(self) -> None:
        request = httpx.Request("POST", "http://fake-host:11434/api/chat")
        response = httpx.Response(200, json={"message": {"content": "hi"}}, request=request)
        self.assertEqual(_parse_ollama_response(response, "http://fake-host:11434", "llama3.2"), "hi")

    def test_non_json_body_raises_a_clear_runtime_error(self) -> None:
        request = httpx.Request("POST", "http://fake-host:11434/api/chat")
        response = httpx.Response(200, text="not json", request=request)
        with self.assertRaises(RuntimeError) as ctx:
            _parse_ollama_response(response, "http://fake-host:11434", "llama3.2")
        self.assertIn("non-JSON", str(ctx.exception))
        self.assertIn("not json", str(ctx.exception))


class TestOllamaProviderAuthMode(unittest.TestCase):
    """Pre-agreed test seam (v3 ticket 02): adapters are testable by direct construction with a
    fake context (fake key, fake base URL) -- no monkeypatching of any config module needed."""

    def test_local_server_has_no_key_based_auth(self) -> None:
        provider = OllamaProvider(_ctx(ollama_base_url="http://fake-host:11434"))
        self.assertEqual(provider.auth_mode, "local")
        self.assertTrue(provider.is_available)


if __name__ == "__main__":
    unittest.main()
