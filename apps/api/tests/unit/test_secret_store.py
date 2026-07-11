import os
import unittest
from unittest.mock import patch

from app.services.secret_store import KEYCHAIN_SERVICE, delete_secret, resolve_secret, store_secret


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


if __name__ == "__main__":
    unittest.main()
