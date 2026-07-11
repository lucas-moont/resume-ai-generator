"""v3 ticket 03: dynamic per-provider model catalog (Anthropic GET /v1/models, Gemini
models.list, Ollama /api/tags) with a ~5min cache and a static fallback offline/without a key.

Seams (pre-agreed in the ticket): HTTP listing calls are mocked at the httpx transport level
(``model_catalog._transport``, an ``httpx.MockTransport`` -- never a real network call), and the
cache TTL is tested by injecting a fake clock (``model_catalog._clock``), never ``time.sleep``.
"""

from __future__ import annotations

import unittest

import httpx

from app.services import model_catalog


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ModelCatalogTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._orig_transport = model_catalog._transport
        self._orig_clock = model_catalog._clock
        model_catalog.invalidate_catalog_cache()
        self._clock = _FakeClock()
        model_catalog._clock = self._clock

    def tearDown(self) -> None:
        model_catalog._transport = self._orig_transport
        model_catalog._clock = self._orig_clock
        model_catalog.invalidate_catalog_cache()

    def _mock(self, handler) -> None:
        model_catalog._transport = httpx.MockTransport(handler)


class TestListInstalledModels(ModelCatalogTestCase):
    async def test_parses_and_sorts_installed_models_cloud_last(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/tags")
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "mystery-model:cloud"},
                        {"name": "llama3.2"},
                        {"name": "Gemma3"},
                    ]
                },
            )

        self._mock(handler)

        names = await model_catalog.list_installed_models()

        self.assertEqual(names, ["Gemma3", "llama3.2", "mystery-model:cloud"])

    async def test_returns_empty_list_on_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        self._mock(handler)

        self.assertEqual(await model_catalog.list_installed_models(), [])

    async def test_returns_empty_list_on_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        self._mock(handler)

        self.assertEqual(await model_catalog.list_installed_models(), [])


class TestOllamaReachable(ModelCatalogTestCase):
    async def test_true_when_the_server_responds(self) -> None:
        self._mock(lambda request: httpx.Response(200, json={"models": []}))

        self.assertTrue(await model_catalog.ollama_reachable())

    async def test_false_when_the_server_is_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        self._mock(handler)

        self.assertFalse(await model_catalog.ollama_reachable())


class TestClaudeModels(ModelCatalogTestCase):
    async def test_falls_back_to_static_suggestions_without_a_key(self) -> None:
        models = await model_catalog.claude_models(None)
        self.assertEqual(models, model_catalog.CLAUDE_MODEL_SUGGESTIONS)

    async def test_fetches_the_dynamic_catalog_when_a_key_is_present(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "api.anthropic.com")
            self.assertEqual(request.headers["x-api-key"], "test-key")
            self.assertIn("anthropic-version", request.headers)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
                        {"id": "claude-opus-4-8", "display_name": "Claude Opus 4.8"},
                    ]
                },
            )

        self._mock(handler)

        models = await model_catalog.claude_models("test-key")  # pragma: allowlist secret

        self.assertEqual(
            models,
            [
                {"value": "claude-sonnet-5", "label": "Claude Sonnet 5"},
                {"value": "claude-opus-4-8", "label": "Claude Opus 4.8"},
            ],
        )

    async def test_falls_back_to_static_suggestions_on_http_error(self) -> None:
        self._mock(lambda request: httpx.Response(401, json={"error": "invalid key"}))

        models = await model_catalog.claude_models("bad-key")  # pragma: allowlist secret

        self.assertEqual(models, model_catalog.CLAUDE_MODEL_SUGGESTIONS)

    async def test_falls_back_to_static_suggestions_on_unexpected_body_shape(self) -> None:
        self._mock(lambda request: httpx.Response(200, json={"unexpected": "shape"}))

        models = await model_catalog.claude_models("test-key")  # pragma: allowlist secret

        self.assertEqual(models, model_catalog.CLAUDE_MODEL_SUGGESTIONS)


class TestGeminiModels(ModelCatalogTestCase):
    async def test_falls_back_to_static_suggestions_without_a_key(self) -> None:
        models = await model_catalog.gemini_models(None)
        self.assertEqual(models, model_catalog.GEMINI_MODEL_SUGGESTIONS)

    async def test_fetches_the_dynamic_catalog_when_a_key_is_present(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "generativelanguage.googleapis.com")
            self.assertEqual(request.headers["x-goog-api-key"], "test-key")
            self.assertNotIn("key", request.url.params)  # never in the query string
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash"},
                    ]
                },
            )

        self._mock(handler)

        models = await model_catalog.gemini_models("test-key")  # pragma: allowlist secret

        self.assertEqual(models, [{"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"}])

    async def test_falls_back_to_static_suggestions_on_http_error(self) -> None:
        self._mock(lambda request: httpx.Response(403, json={"error": "forbidden"}))

        models = await model_catalog.gemini_models("bad-key")  # pragma: allowlist secret

        self.assertEqual(models, model_catalog.GEMINI_MODEL_SUGGESTIONS)


class TestCatalogCache(ModelCatalogTestCase):
    async def test_repeated_calls_within_ttl_do_not_refetch(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

        self._mock(handler)

        await model_catalog.claude_models("test-key")  # pragma: allowlist secret
        await model_catalog.claude_models("test-key")  # pragma: allowlist secret

        self.assertEqual(calls["n"], 1)

    async def test_refetches_after_the_ttl_expires(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

        self._mock(handler)

        await model_catalog.claude_models("test-key")  # pragma: allowlist secret
        self._clock.advance(model_catalog.CATALOG_CACHE_TTL_SECONDS + 1)
        await model_catalog.claude_models("test-key")  # pragma: allowlist secret

        self.assertEqual(calls["n"], 2)

    async def test_invalidate_forces_an_immediate_refetch(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

        self._mock(handler)

        await model_catalog.claude_models("test-key")  # pragma: allowlist secret
        model_catalog.invalidate_catalog_cache()
        await model_catalog.claude_models("test-key")  # pragma: allowlist secret

        self.assertEqual(calls["n"], 2)


class TestListModelsCatalog(ModelCatalogTestCase):
    async def test_adds_an_additive_provider_field_per_item(self) -> None:
        """GET /api/models gains `provider` per item -- additive, existing `value`/`label`
        keys must still be present (compat is pinned in
        tests/integration/test_generate_endpoints_compat.py)."""
        self._mock(lambda request: httpx.Response(200, json={"models": []}))

        body = await model_catalog.list_models_catalog()

        self.assertIn("default", body)
        self.assertIn("models", body)
        for item in body["models"]:
            self.assertEqual(set(item.keys()), {"value", "label", "provider"})
            self.assertIn(item["provider"], ("claude", "gemini", "ollama"))

    async def test_deduplicates_across_providers_keeping_first_seen(self) -> None:
        self._mock(lambda request: httpx.Response(200, json={"models": [{"name": "claude-sonnet-5"}]}))

        body = await model_catalog.list_models_catalog()

        values = [m["value"] for m in body["models"]]
        self.assertEqual(values.count("claude-sonnet-5"), 1)
        # First-seen (claude's static suggestion) wins the provider tag over ollama's namesake.
        winner = next(m for m in body["models"] if m["value"] == "claude-sonnet-5")
        self.assertEqual(winner["provider"], "claude")


if __name__ == "__main__":
    unittest.main()
