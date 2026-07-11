"""Characterization + new-behavior tests for the config call-time prefactor (v3 ticket 01).

Before this ticket, AI_PROVIDER/AI_DEFAULT_MODEL/API keys/DEFAULT_*_MODEL were frozen at
import time in app/config.py -- a runtime settings write would never take effect without a
process restart. get_runtime_config() (and the per-field resolve_* accessors) replace that:
env -> app_settings -> hardcoded default (API keys: env -> keychain, never app_settings --
see app/services/secret_store.py), cached and invalidated on every app_settings write.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app import config
from app.repositories import app_settings_repo


_AI_ENV_VARS = (
    "AI_PROVIDER",
    "AI_DEFAULT_MODEL",
    "CLAUDE_MODEL",
    "GEMINI_MODEL",
    "OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def settings_engine(isolated_runtime_settings_engine, monkeypatch: pytest.MonkeyPatch):
    """Builds on conftest.py's repo-wide ``isolated_runtime_settings_engine`` (which already
    points config's app_settings resolution at a fresh in-memory DB) and additionally clears
    the AI env vars, so the developer's real .env (AI_PROVIDER=claude, custom GEMINI_MODEL/
    OLLAMA_MODEL, etc.) never leaks into a test expecting the hardcoded default.
    """
    for name in _AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield isolated_runtime_settings_engine


def _write_setting(engine, key: str, value) -> None:
    with Session(engine) as session:
        app_settings_repo.set(session, key, value)
        session.commit()


class TestResolveAiProvider:
    def test_defaults_to_auto(self) -> None:
        assert config.resolve_ai_provider() == "auto"

    def test_app_settings_value_is_used_when_env_is_unset(self, settings_engine, monkeypatch) -> None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        _write_setting(settings_engine, "ai_provider", "claude")

        assert config.resolve_ai_provider() == "claude"

    def test_env_takes_precedence_over_app_settings(self, settings_engine, monkeypatch) -> None:
        _write_setting(settings_engine, "ai_provider", "claude")
        monkeypatch.setenv("AI_PROVIDER", "gemini")

        assert config.resolve_ai_provider() == "gemini"


class TestResolveAiDefaultModel:
    def test_defaults_to_none(self) -> None:
        assert config.resolve_ai_default_model() is None

    def test_app_settings_value_is_used_when_env_is_unset(self, settings_engine, monkeypatch) -> None:
        monkeypatch.delenv("AI_DEFAULT_MODEL", raising=False)
        _write_setting(settings_engine, "ai_default_model", "claude-opus-4-8")

        assert config.resolve_ai_default_model() == "claude-opus-4-8"


class TestResolveDefaultModels:
    def test_claude_default_falls_back_to_hardcoded_value(self) -> None:
        assert config.resolve_default_claude_model() == "claude-sonnet-5"

    def test_claude_default_reads_app_settings_override(self, settings_engine, monkeypatch) -> None:
        monkeypatch.delenv("CLAUDE_MODEL", raising=False)
        _write_setting(settings_engine, "default_claude_model", "claude-haiku-4-5")

        assert config.resolve_default_claude_model() == "claude-haiku-4-5"

    def test_gemini_default_falls_back_to_hardcoded_value(self) -> None:
        assert config.resolve_default_gemini_model() == "gemini-2.5-flash"

    def test_ollama_default_falls_back_to_hardcoded_value(self) -> None:
        assert config.resolve_default_ollama_model() == "llama3.2"


class TestGetRuntimeConfig:
    def test_bundles_provider_and_model_fields(self, settings_engine, monkeypatch) -> None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        _write_setting(settings_engine, "ai_provider", "gemini")

        runtime = config.get_runtime_config()

        assert runtime.ai_provider == "gemini"
        assert runtime.default_claude_model == "claude-sonnet-5"
        assert runtime.default_gemini_model == "gemini-2.5-flash"
        assert runtime.default_ollama_model == "llama3.2"

    def test_resolves_api_keys_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")  # pragma: allowlist secret
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")  # pragma: allowlist secret

        runtime = config.get_runtime_config()

        assert runtime.anthropic_api_key == "test-anthropic-key"  # pragma: allowlist secret
        assert runtime.gemini_api_key == "test-gemini-key"  # pragma: allowlist secret

    def test_reflects_a_settings_write_without_restart_or_reimport(
        self, settings_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The acceptance-criteria integration scenario at the config layer: provider X active,
        write settings, the very next call (same process, same import) sees provider Y."""
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        assert config.get_runtime_config().ai_provider == "auto"

        config.set_app_setting("ai_provider", "claude")

        assert config.get_runtime_config().ai_provider == "claude"


class TestRuntimeConfigCache:
    def test_repeated_calls_do_not_repeatedly_hit_the_database(
        self, settings_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}
        original_get_all = app_settings_repo.get_all

        def _counting_get_all(session):
            calls["n"] += 1
            return original_get_all(session)

        monkeypatch.setattr(app_settings_repo, "get_all", _counting_get_all)

        config.get_runtime_config()
        config.get_runtime_config()
        config.get_runtime_config()

        assert calls["n"] == 1

    def test_invalidate_forces_a_fresh_read_on_the_next_call(
        self, settings_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}
        original_get_all = app_settings_repo.get_all

        def _counting_get_all(session):
            calls["n"] += 1
            return original_get_all(session)

        monkeypatch.setattr(app_settings_repo, "get_all", _counting_get_all)

        config.get_runtime_config()
        config.invalidate_runtime_config_cache()
        config.get_runtime_config()

        assert calls["n"] == 2

    def test_set_app_setting_invalidates_the_cache(self, settings_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        config.get_runtime_config()  # warm the cache with the pre-write state

        config.set_app_setting("ai_provider", "ollama")

        assert config.get_runtime_config().ai_provider == "ollama"

    def test_delete_app_setting_invalidates_the_cache(self, settings_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        config.set_app_setting("ai_provider", "gemini")
        assert config.get_runtime_config().ai_provider == "gemini"

        config.delete_app_setting("ai_provider")

        assert config.get_runtime_config().ai_provider == "auto"
