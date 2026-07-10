import os
import unittest

from app.services.secret_store import resolve_secret


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


if __name__ == "__main__":
    unittest.main()
