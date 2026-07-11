"""Regression test for a real risk this repo's own dev environment exposes: `.env` at the repo
root ships a real GEMINI_API_KEY (see app/config.py's `load_dotenv`). Before v3 ticket 03, the
model catalog never made an HTTP call driven by that key's value, so its presence in the test
process's environment was harmless. As of the dynamic catalog (Anthropic/Gemini/Ollama listing
calls), a test that does not explicitly mock the catalog's transport could otherwise make a
REAL network call using that real key. tests/conftest.py's autouse
`_no_real_network_for_model_catalog` fixture closes this by forcing every test onto a
transport that always fails closed -- this test proves that seam, independent of whatever
secrets happen to be configured on the machine running the suite.
"""

from __future__ import annotations

import unittest

from app.services import model_catalog


class TestNoRealNetworkByDefault(unittest.IsolatedAsyncioTestCase):
    async def test_claude_models_falls_back_even_with_a_key_present(self) -> None:
        # A "real-looking" key does not matter -- the autouse fixture in conftest.py forces
        # every outbound call through a transport that always raises, so this must degrade to
        # the static fallback rather than attempt real I/O.
        models = await model_catalog.claude_models("sk-ant-not-a-real-key-but-non-empty")
        self.assertEqual(models, model_catalog.CLAUDE_MODEL_SUGGESTIONS)

    async def test_gemini_models_falls_back_even_with_a_key_present(self) -> None:
        models = await model_catalog.gemini_models("AIza-not-a-real-key-but-non-empty")
        self.assertEqual(models, model_catalog.GEMINI_MODEL_SUGGESTIONS)

    async def test_ollama_reachable_is_false_by_default(self) -> None:
        self.assertFalse(await model_catalog.ollama_reachable())


if __name__ == "__main__":
    unittest.main()
