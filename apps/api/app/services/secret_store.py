from __future__ import annotations

import os

# Namespace used when storing/reading secrets in the OS keychain, e.g.
#   keyring set resume-agent GEMINI_API_KEY
KEYCHAIN_SERVICE = "resume-agent"


def resolve_secret(env_var: str, *, service: str = KEYCHAIN_SERVICE) -> str | None:
    """Resolve a credential by name.

    Order of precedence:
      1. Environment variable (works in CI/containers and matches SDK precedence).
      2. OS keychain (Windows Credential Locker / macOS Keychain / Linux SecretService),
         under ``service`` with the env var name as the entry key.
      3. None when neither is configured.

    ``keyring`` is an optional dependency; if it (or a backend) is unavailable, this falls back
    to environment-only resolution instead of raising.
    """
    value = (os.getenv(env_var) or "").strip()
    if value:
        return value

    try:
        import keyring
    except ModuleNotFoundError:
        return None

    try:
        stored = keyring.get_password(service, env_var)
    except Exception:
        # No backend, locked keychain, access denied, etc. — treat as "not configured".
        return None

    stored = (stored or "").strip()
    return stored or None


def secret_source(env_var: str, *, service: str = KEYCHAIN_SERVICE) -> str | None:
    """Which tier ``resolve_secret`` would resolve ``env_var`` from -- ``"env"``, ``"keychain"``,
    or ``None`` -- WITHOUT returning the value itself. Used by ``GET /api/settings/keys``
    (v3 ticket 03) to report ``{name, configured, source}`` for each managed key: the value
    must never be echoed, only where it currently comes from. Mirrors ``resolve_secret``'s
    precedence exactly (env, then keychain), duplicated rather than refactored out of it so
    ``resolve_secret``'s existing, well-tested contract (return the value) is untouched.
    """
    value = (os.getenv(env_var) or "").strip()
    if value:
        return "env"

    try:
        import keyring
    except ModuleNotFoundError:
        return None

    try:
        stored = keyring.get_password(service, env_var)
    except Exception:
        return None

    return "keychain" if (stored or "").strip() else None


def store_secret(name: str, value: str, *, service: str = KEYCHAIN_SERVICE) -> bool:
    """Write a credential to the OS keychain (v3 ticket 01: PUT /api/settings/keys).

    Returns ``True`` on success, ``False`` when ``keyring`` (or a backend) is unavailable --
    the same graceful degradation as ``resolve_secret`` on the read side, rather than raising.
    Never writes to ``app_settings``/SQLite: API keys live in the keychain only.

    Raises ``ValueError`` for an empty/whitespace-only ``value``: that is invalid input for a
    PUT, not a silent alias for ``delete_secret`` -- deletion of a key must stay an explicit
    DELETE. The API layer is expected to map this to HTTP 422.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("value must not be empty; call delete_secret to remove a key")
    try:
        import keyring
    except ModuleNotFoundError:
        return False

    try:
        keyring.set_password(service, name, cleaned)
    except Exception:
        return False
    return True


def delete_secret(name: str, *, service: str = KEYCHAIN_SERVICE) -> bool:
    """Remove a credential from the OS keychain. Idempotent: deleting an entry that doesn't
    exist is not an error (``PasswordDeleteError``) -- only a missing/broken backend is."""
    try:
        import keyring
        import keyring.errors as keyring_errors
    except ModuleNotFoundError:
        return False

    try:
        keyring.delete_password(service, name)
    except keyring_errors.PasswordDeleteError:
        pass
    except Exception:
        return False
    return True
