import os
import unittest

from app.services.secret_redaction import redact_secrets


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


if __name__ == "__main__":
    unittest.main()
