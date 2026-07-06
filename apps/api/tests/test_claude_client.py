import unittest
from types import SimpleNamespace

from app.services import claude_client


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
        self.assertEqual(claude_client._extract_text(message), '{"a": 1}')

    def test_empty_when_no_text_blocks(self) -> None:
        message = SimpleNamespace(content=[_block("thinking", "x")])
        self.assertEqual(claude_client._extract_text(message), "")

    def test_handles_missing_content(self) -> None:
        self.assertEqual(claude_client._extract_text(SimpleNamespace()), "")


class TestThinkingConfig(unittest.TestCase):
    def test_off_maps_to_disabled(self) -> None:
        original = claude_client.CLAUDE_THINKING
        try:
            claude_client.CLAUDE_THINKING = "off"
            self.assertEqual(claude_client._thinking_config(), {"type": "disabled"})
        finally:
            claude_client.CLAUDE_THINKING = original

    def test_adaptive_maps_to_adaptive(self) -> None:
        original = claude_client.CLAUDE_THINKING
        try:
            claude_client.CLAUDE_THINKING = "adaptive"
            self.assertEqual(claude_client._thinking_config(), {"type": "adaptive"})
        finally:
            claude_client.CLAUDE_THINKING = original


if __name__ == "__main__":
    unittest.main()
