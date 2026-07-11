import unittest
from types import SimpleNamespace

from app.services.llm.providers.base import ProviderContext
from app.services.llm.providers.claude_provider import (
    ClaudeProvider,
    _extract_text,
    _thinking_config,
)


def _ctx(**overrides) -> ProviderContext:
    defaults: dict = {"mode": "claude"}
    defaults.update(overrides)
    return ProviderContext(**defaults)


def _block(block_type: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(type=block_type, text=text)


class TestExtractText(unittest.TestCase):
    def test_joins_only_text_blocks(self) -> None:
        message = SimpleNamespace(
            content=[
                _block("thinking", "ignored reasoning"),
                _block("text", '{"a":'),
                _block("text", " 1}"),
            ]
        )
        self.assertEqual(_extract_text(message), '{"a": 1}')

    def test_empty_when_no_text_blocks(self) -> None:
        message = SimpleNamespace(content=[_block("thinking", "x")])
        self.assertEqual(_extract_text(message), "")

    def test_handles_missing_content(self) -> None:
        self.assertEqual(_extract_text(SimpleNamespace()), "")


class TestThinkingConfig(unittest.TestCase):
    """_thinking_config now takes the thinking mode as a plain argument (v3 ticket 02: adapters
    read config only from their injected ProviderContext, never a config module), so these no
    longer patch app.config -- they just pass the value directly."""

    def test_off_maps_to_disabled(self) -> None:
        self.assertEqual(_thinking_config("off"), {"type": "disabled"})

    def test_adaptive_maps_to_adaptive(self) -> None:
        self.assertEqual(_thinking_config("adaptive"), {"type": "adaptive"})


class TestClaudeProviderAuthMode(unittest.TestCase):
    """Pre-agreed test seam (v3 ticket 02): adapters are testable by direct construction with a
    fake context (fake key, fake base URL) -- no monkeypatching of any config module needed."""

    def test_api_key_present_selects_api_key_auth_mode(self) -> None:
        provider = ClaudeProvider(_ctx(anthropic_api_key="sk-ant-fake-test-key"))  # pragma: allowlist secret
        self.assertEqual(provider.auth_mode, "api_key")
        self.assertTrue(provider.is_available)

    def test_no_api_key_falls_back_to_cli_auth_mode(self) -> None:
        provider = ClaudeProvider(_ctx(anthropic_api_key=None))
        self.assertEqual(provider.auth_mode, "cli")

    def test_no_api_key_and_no_cli_on_path_is_unavailable(self) -> None:
        import app.services.llm.providers.claude_provider as claude_provider_module

        original_which = claude_provider_module.shutil.which
        claude_provider_module.shutil.which = lambda _name: None
        try:
            provider = ClaudeProvider(_ctx(anthropic_api_key=None))
            self.assertEqual(provider.auth_mode, "cli")
            self.assertFalse(provider.is_available)
        finally:
            claude_provider_module.shutil.which = original_which


if __name__ == "__main__":
    unittest.main()
