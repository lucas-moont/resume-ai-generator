import os
import unittest
from unittest.mock import patch

from app.services.secret_store import (
    KEYCHAIN_SERVICE,
    delete_secret,
    resolve_secret,
    secret_source,
    store_secret,
)


class TestResolveSecret(unittest.TestCase):
    _VAR = "RESUME_AGENT_TEST_SECRET"

    def tearDown(self) -> None:
        os.environ.pop(self._VAR, None)

    def test_environment_takes_precedence(self) -> None:
        os.environ[self._VAR] = "  from-env  "
        self.assertEqual(resolve_secret(self._VAR), "from-env")

    def test_returns_none_when_unset_and_no_keychain_entry(self) -> None:
        os.environ.pop(self._VAR, None)
        # No keychain entry exists for this synthetic var, so resolution is None regardless of
        # whether a keyring backend is installed (missing entry / missing backend both -> None).
        self.assertIsNone(resolve_secret(self._VAR))

    def test_blank_environment_value_is_not_used(self) -> None:
        os.environ[self._VAR] = "   "
        self.assertIsNone(resolve_secret(self._VAR))


class TestStoreSecret(unittest.TestCase):
    _VAR = "RESUME_AGENT_TEST_SECRET"

    def test_writes_trimmed_value_to_keychain(self) -> None:
        with patch("keyring.set_password") as set_password:
            self.assertTrue(store_secret(self._VAR, "  a-new-value  "))
            set_password.assert_called_once_with(KEYCHAIN_SERVICE, self._VAR, "a-new-value")

    def test_returns_false_when_backend_unavailable(self) -> None:
        # No backend, locked keychain, access denied, etc. -- same degradation as resolve_secret.
        with patch("keyring.set_password", side_effect=RuntimeError("no backend")):
            self.assertFalse(store_secret(self._VAR, "value"))

    def test_rejects_empty_value(self) -> None:
        """Fix-round decision (v3 ticket 01 review): an empty/whitespace value is invalid
        input for PUT /api/settings/keys, not a silent alias for delete_secret -- deletion
        must stay an explicit DELETE. The API layer maps this ValueError to 422."""
        with patch("keyring.set_password") as set_password:
            with self.assertRaises(ValueError):
                store_secret(self._VAR, "")
            set_password.assert_not_called()

    def test_rejects_whitespace_only_value(self) -> None:
        with patch("keyring.set_password") as set_password:
            with self.assertRaises(ValueError):
                store_secret(self._VAR, "   ")
            set_password.assert_not_called()


class TestDeleteSecret(unittest.TestCase):
    _VAR = "RESUME_AGENT_TEST_SECRET"

    def test_removes_entry_from_keychain(self) -> None:
        with patch("keyring.delete_password") as delete_password:
            self.assertTrue(delete_secret(self._VAR))
            delete_password.assert_called_once_with(KEYCHAIN_SERVICE, self._VAR)

    def test_missing_entry_is_not_an_error(self) -> None:
        import keyring.errors as errors

        with patch("keyring.delete_password", side_effect=errors.PasswordDeleteError("no entry")):
            self.assertTrue(delete_secret(self._VAR))

    def test_returns_false_when_backend_unavailable(self) -> None:
        with patch("keyring.delete_password", side_effect=RuntimeError("no backend")):
            self.assertFalse(delete_secret(self._VAR))


class TestSecretSource(unittest.TestCase):
    """v3 ticket 03: GET /api/settings/keys reports WHERE a key resolves from (env|keychain|
    None) without ever echoing the value itself."""

    _VAR = "RESUME_AGENT_TEST_SECRET"

    def tearDown(self) -> None:
        os.environ.pop(self._VAR, None)

    def test_env_takes_precedence_and_reports_env(self) -> None:
        os.environ[self._VAR] = "from-env"
        with patch("keyring.get_password", return_value="from-keychain"):
            self.assertEqual(secret_source(self._VAR), "env")

    def test_reports_keychain_when_env_is_unset(self) -> None:
        os.environ.pop(self._VAR, None)
        with patch("keyring.get_password", return_value="from-keychain"):
            self.assertEqual(secret_source(self._VAR), "keychain")

    def test_reports_none_when_neither_is_configured(self) -> None:
        os.environ.pop(self._VAR, None)
        with patch("keyring.get_password", return_value=None):
            self.assertIsNone(secret_source(self._VAR))

    def test_reports_none_when_keyring_backend_is_unavailable(self) -> None:
        os.environ.pop(self._VAR, None)
        with patch("keyring.get_password", side_effect=RuntimeError("no backend")):
            self.assertIsNone(secret_source(self._VAR))

    def test_blank_environment_value_falls_through_to_keychain(self) -> None:
        os.environ[self._VAR] = "   "
        with patch("keyring.get_password", return_value="from-keychain"):
            self.assertEqual(secret_source(self._VAR), "keychain")


if __name__ == "__main__":
    unittest.main()
