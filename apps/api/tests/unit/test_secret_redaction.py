import os
import unittest
from unittest.mock import patch

from app.services.secret_redaction import redact_secrets
from app.services.secret_store import store_secret


class TestSecretRedaction(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")}

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_redacts_configured_secret_value(self) -> None:
        os.environ["GEMINI_API_KEY"] = "AIzaSyD-super-secret-value-1234"  # pragma: allowlist secret
        msg = "HTTP 400 at .../generateContent?key=AIzaSyD-super-secret-value-1234"  # pragma: allowlist secret
        out = redact_secrets(msg)
        self.assertNotIn("AIzaSyD-super-secret-value-1234", out)
        self.assertIn("«redacted»", out)

    def test_passthrough_when_no_secret_present(self) -> None:
        os.environ["GEMINI_API_KEY"] = "AIzaSyD-super-secret-value-1234"  # pragma: allowlist secret
        self.assertEqual(redact_secrets("plain error, no secrets"), "plain error, no secrets")

    def test_empty_and_short_values_do_not_over_redact(self) -> None:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["ANTHROPIC_API_KEY"] = "abc"  # below the min length guard
        self.assertEqual(redact_secrets("contains abc and empty"), "contains abc and empty")

    def test_handles_empty_text(self) -> None:
        self.assertEqual(redact_secrets(""), "")

    def test_redacts_a_key_added_to_the_keychain_at_runtime(self) -> None:
        """v3 ticket 01 acceptance criterion: secret_redaction collects secret values at CALL
        time (not from a frozen config constant), so a key written to the keychain mid-process
        -- e.g. via a future PUT /api/settings/keys -- is redacted on the very next call, no
        restart or reload needed."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        runtime_secret = "sk-ant-runtime-secret-added-mid-process"  # pragma: allowlist secret

        # Not configured yet: passes through untouched.
        before = redact_secrets(f"error mentions {runtime_secret}")
        self.assertIn(runtime_secret, before)

        with patch("keyring.set_password"), patch("keyring.get_password", return_value=runtime_secret):
            self.assertTrue(store_secret("ANTHROPIC_API_KEY", runtime_secret))

            after = redact_secrets(f"error mentions {runtime_secret}")

        self.assertNotIn(runtime_secret, after)
        self.assertIn("«redacted»", after)


if __name__ == "__main__":
    unittest.main()
