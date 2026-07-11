"""v3 ticket 03: GET/PUT /api/settings/providers, GET/PUT/DELETE /api/settings/keys.

Seams (pre-agreed): integration via the existing `client` fixture + `dependency_overrides`;
keyring mocked (never a real OS keychain call); the dynamic model catalog's HTTP calls are
already forced onto a fail-closed transport by conftest.py's autouse
`_no_real_network_for_model_catalog` -- so every provider here degrades to its static
suggestion list / reports Ollama unreachable unless a test explicitly injects its own
`httpx.MockTransport` (see tests/unit/test_model_catalog.py for that seam; not needed here,
since this file exercises the settings contract, not catalog parsing).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app import config as config_module
from app.services.llm.providers import claude_provider as claude_provider_module


@pytest.fixture(autouse=True)
def _no_claude_cli_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic baseline: whether the real `claude` CLI happens to be on THIS machine's
    PATH must not affect the test outcome (the developer running this suite may well have
    Claude Code installed)."""
    monkeypatch.setattr(claude_provider_module.shutil, "which", lambda _name: None)


class TestGetProviders:
    async def test_default_state_reports_auto_and_all_three_providers(self, client) -> None:
        resp = await client.get("/api/settings/providers")

        assert resp.status_code == 200
        body = resp.json()
        assert body["active"] == "auto"
        names = [p["name"] for p in body["providers"]]
        assert names == ["claude", "gemini", "ollama"]

    async def test_claude_without_a_key_reports_cli_auth_and_static_suggestions(self, client) -> None:
        resp = await client.get("/api/settings/providers")

        claude = next(p for p in resp.json()["providers"] if p["name"] == "claude")
        assert claude["auth"] == "cli"
        assert claude["available"] is False  # no key, no CLI on PATH (fixture above)
        assert claude["defaultModel"] == "claude-sonnet-5"
        assert {"claude-sonnet-5", "claude-opus-4-8"} <= {m["value"] for m in claude["models"]}

    async def test_gemini_without_a_key_reports_none_auth_and_static_suggestions(self, client) -> None:
        resp = await client.get("/api/settings/providers")

        gemini = next(p for p in resp.json()["providers"] if p["name"] == "gemini")
        assert gemini["auth"] == "none"
        assert gemini["available"] is False
        assert gemini["defaultModel"] == "gemini-2.5-flash"
        assert any(m["value"] == "gemini-2.5-flash" for m in gemini["models"])

    async def test_ollama_reports_local_auth_and_unreachable_offline(self, client) -> None:
        resp = await client.get("/api/settings/providers")

        ollama = next(p for p in resp.json()["providers"] if p["name"] == "ollama")
        assert ollama["auth"] == "local"
        # No Ollama server reachable in the test sandbox (transport fails closed) -- v3
        # ticket 03's own decision to surface a REAL reachability signal here, unlike
        # OllamaProvider.is_available (sync, always True).
        assert ollama["available"] is False
        assert ollama["models"] == []

    async def test_claude_with_a_key_reports_api_key_auth_and_is_available(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-test-key")  # pragma: allowlist secret

        resp = await client.get("/api/settings/providers")

        claude = next(p for p in resp.json()["providers"] if p["name"] == "claude")
        assert claude["auth"] == "api_key"
        assert claude["available"] is True


class TestPutProviders:
    async def test_switches_the_active_provider_with_immediate_effect(self, client) -> None:
        resp = await client.put("/api/settings/providers", json={"provider": "claude"})

        assert resp.status_code == 200
        assert resp.json()["active"] == "claude"

        follow_up = await client.get("/api/settings/providers")
        assert follow_up.json()["active"] == "claude"

    async def test_persists_via_app_settings_ai_provider_key(self, client) -> None:
        await client.put("/api/settings/providers", json={"provider": "gemini"})

        assert config_module.resolve_ai_provider() == "gemini"

    async def test_default_model_for_a_concrete_provider_updates_that_providers_default(
        self, client
    ) -> None:
        resp = await client.put(
            "/api/settings/providers",
            json={"provider": "claude", "defaultModel": "claude-haiku-4-5"},
        )

        assert resp.status_code == 200
        claude = next(p for p in resp.json()["providers"] if p["name"] == "claude")
        assert claude["defaultModel"] == "claude-haiku-4-5"
        assert config_module.resolve_default_claude_model() == "claude-haiku-4-5"
        # Only claude's own default changed -- gemini/ollama untouched.
        assert config_module.resolve_default_gemini_model() == "gemini-2.5-flash"

    async def test_default_model_while_switching_to_auto_sets_the_generic_override(
        self, client
    ) -> None:
        resp = await client.put(
            "/api/settings/providers",
            json={"provider": "auto", "defaultModel": "claude-opus-4-8"},
        )

        assert resp.status_code == 200
        assert config_module.resolve_ai_default_model() == "claude-opus-4-8"

    async def test_rejects_an_invalid_provider_name(self, client) -> None:
        resp = await client.put("/api/settings/providers", json={"provider": "bogus"})

        assert resp.status_code == 422


class TestGetKeys:
    async def test_default_state_reports_all_three_keys_unconfigured(self, client) -> None:
        resp = await client.get("/api/settings/keys")

        assert resp.status_code == 200
        keys = resp.json()["keys"]
        names = [k["name"] for k in keys]
        assert names == ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GITHUB_TOKEN"]
        for k in keys:
            assert k["configured"] is False
            assert k["source"] is None

    async def test_reports_env_as_the_source_when_set_via_environment(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-fake-test-key")  # pragma: allowlist secret

        resp = await client.get("/api/settings/keys")

        gemini = next(k for k in resp.json()["keys"] if k["name"] == "GEMINI_API_KEY")
        assert gemini["configured"] is True
        assert gemini["source"] == "env"
        # The value itself is never echoed anywhere in the response.
        assert "AIza-fake-test-key" not in resp.text

    async def test_reports_keychain_as_the_source_when_only_the_keychain_has_it(self, client) -> None:
        with patch("keyring.get_password", return_value="stored-fake-key"):  # pragma: allowlist secret
            resp = await client.get("/api/settings/keys")

        anthropic = next(k for k in resp.json()["keys"] if k["name"] == "ANTHROPIC_API_KEY")
        assert anthropic["configured"] is True
        assert anthropic["source"] == "keychain"
        assert "stored-fake-key" not in resp.text  # pragma: allowlist secret


class TestPutKeys:
    async def test_writes_only_to_the_keychain_and_never_echoes_the_value(self, client) -> None:
        # get_password is stubbed to echo back what was "stored" -- this test isn't proving
        # the real keyring backend round-trips correctly (that's test_secret_store.py's job),
        # only that the endpoint calls store_secret and then reports {configured, source} for
        # whatever the keychain now resolves to.
        with patch("keyring.set_password") as set_password, patch(
            "keyring.get_password", return_value="sk-ant-brand-new-secret"  # pragma: allowlist secret
        ):
            resp = await client.put(
                "/api/settings/keys",
                json={"name": "ANTHROPIC_API_KEY", "value": "sk-ant-brand-new-secret"},  # pragma: allowlist secret
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"name": "ANTHROPIC_API_KEY", "configured": True, "source": "keychain"}
        assert "sk-ant-brand-new-secret" not in resp.text  # pragma: allowlist secret
        set_password.assert_called_once_with(
            "resume-agent", "ANTHROPIC_API_KEY", "sk-ant-brand-new-secret"  # pragma: allowlist secret
        )

    async def test_rejects_an_invalid_key_name(self, client) -> None:
        resp = await client.put(
            "/api/settings/keys", json={"name": "NOT_A_MANAGED_KEY", "value": "whatever"}
        )

        assert resp.status_code == 422

    async def test_rejects_an_empty_value_without_ever_touching_the_keychain(self, client) -> None:
        with patch("keyring.set_password") as set_password:
            resp = await client.put(
                "/api/settings/keys", json={"name": "GEMINI_API_KEY", "value": "   "}
            )

        assert resp.status_code == 422
        set_password.assert_not_called()

    async def test_never_lands_in_sqlite_app_settings(
        self, client, isolated_runtime_settings_engine
    ) -> None:
        """AC: a key must never be persisted to app_settings/SQLite -- only the keychain."""
        with patch("keyring.set_password"):
            await client.put(
                "/api/settings/keys",
                json={"name": "GITHUB_TOKEN", "value": "ghp_fake_token_value"},  # pragma: allowlist secret
            )

        # get_runtime_config()/app_settings has no notion of GITHUB_TOKEN at all; the only
        # durable place a value could leak to is the app_settings table itself.
        from app.repositories import app_settings_repo
        from sqlmodel import Session

        with Session(isolated_runtime_settings_engine) as session:
            all_settings = app_settings_repo.get_all(session)
        assert "ghp_fake_token_value" not in str(all_settings)  # pragma: allowlist secret
        assert "GITHUB_TOKEN" not in all_settings


class TestDeleteKeys:
    async def test_removes_the_key_from_the_keychain(self, client) -> None:
        with patch("keyring.delete_password") as delete_password:
            resp = await client.delete("/api/settings/keys/ANTHROPIC_API_KEY")

        assert resp.status_code == 204
        delete_password.assert_called_once_with("resume-agent", "ANTHROPIC_API_KEY")

    async def test_rejects_an_invalid_key_name(self, client) -> None:
        resp = await client.delete("/api/settings/keys/NOT_A_MANAGED_KEY")

        assert resp.status_code == 422

    async def test_deleting_is_reflected_immediately_in_get_keys(self, client) -> None:
        with patch("keyring.get_password", return_value=None), patch("keyring.delete_password"):
            await client.delete("/api/settings/keys/GEMINI_API_KEY")
            resp = await client.get("/api/settings/keys")

        gemini = next(k for k in resp.json()["keys"] if k["name"] == "GEMINI_API_KEY")
        assert gemini["configured"] is False


class TestFirstUseWithoutEnv:
    """Gate v3 acceptance criterion, exercised at the API layer: the app boots and every
    settings endpoint responds even with zero configuration (no .env, no app_settings rows, no
    keychain entries) -- 'auto' degrades to whatever is actually available (Ollama, per
    resolve_provider_name's precedence) instead of erroring."""

    async def test_providers_and_keys_endpoints_respond_with_nothing_configured(self, client) -> None:
        providers_resp = await client.get("/api/settings/providers")
        keys_resp = await client.get("/api/settings/keys")

        assert providers_resp.status_code == 200
        assert keys_resp.status_code == 200
        assert providers_resp.json()["active"] == "auto"
