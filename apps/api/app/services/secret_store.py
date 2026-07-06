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
