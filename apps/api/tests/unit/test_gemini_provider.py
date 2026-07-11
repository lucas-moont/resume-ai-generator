import unittest

from app.services.llm.providers.base import ProviderContext
from app.services.llm.providers.gemini_provider import GeminiProvider, _extract_text


def _ctx(**overrides) -> ProviderContext:
    defaults: dict = {"mode": "gemini"}
    defaults.update(overrides)
    return ProviderContext(**defaults)


class TestExtractText(unittest.TestCase):
    def test_joins_candidate_parts(self) -> None:
        data = {"candidates": [{"content": {"parts": [{"text": '{"a":'}, {"text": " 1}"}]}}]}
        self.assertEqual(_extract_text(data), '{"a": 1}')

    def test_empty_when_no_candidates(self) -> None:
        self.assertEqual(_extract_text({"candidates": []}), "")

    def test_empty_when_blocked_by_prompt_feedback(self) -> None:
        data = {"promptFeedback": {"blockReason": "SAFETY"}}
        self.assertEqual(_extract_text(data), "")


class TestGeminiProviderAuthMode(unittest.TestCase):
    """Pre-agreed test seam (v3 ticket 02): adapters are testable by direct construction with a
    fake context (fake key, fake base URL) -- no monkeypatching of any config module needed."""

    def test_api_key_present_selects_api_key_auth_mode(self) -> None:
        provider = GeminiProvider(_ctx(gemini_api_key="fake-gemini-key"))
        self.assertEqual(provider.auth_mode, "api_key")
        self.assertTrue(provider.is_available)

    def test_no_api_key_has_no_viable_auth_path(self) -> None:
        # Unlike Claude, Gemini has no local-session fallback -- no key means "none".
        provider = GeminiProvider(_ctx(gemini_api_key=None))
        self.assertEqual(provider.auth_mode, "none")
        self.assertFalse(provider.is_available)


if __name__ == "__main__":
    unittest.main()
