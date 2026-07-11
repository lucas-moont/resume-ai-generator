"""Standards fix round (v3 ticket 03): model_catalog._cache's correctness depends entirely on
every write path calling invalidate_catalog_cache() -- there is no TTL-based staleness check on
write, only on read. This proves the module's two production call sites actually uphold that
invariant, rather than leaving it implicit.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import model_catalog, settings_service


class TestKeyWritesInvalidateTheCatalogCache(unittest.TestCase):
    def setUp(self) -> None:
        model_catalog.invalidate_catalog_cache()

    def tearDown(self) -> None:
        model_catalog.invalidate_catalog_cache()

    def test_upsert_key_invalidates_the_catalog_cache(self) -> None:
        model_catalog._cache["claude"] = (float("inf"), model_catalog.CLAUDE_MODEL_SUGGESTIONS)

        with patch("keyring.set_password"):
            settings_service.upsert_key("ANTHROPIC_API_KEY", "sk-ant-fake-test-key")  # pragma: allowlist secret

        self.assertNotIn("claude", model_catalog._cache)

    def test_delete_key_invalidates_the_catalog_cache(self) -> None:
        model_catalog._cache["gemini"] = (float("inf"), model_catalog.GEMINI_MODEL_SUGGESTIONS)

        with patch("keyring.delete_password"):
            settings_service.delete_key("GEMINI_API_KEY")

        self.assertNotIn("gemini", model_catalog._cache)


if __name__ == "__main__":
    unittest.main()
