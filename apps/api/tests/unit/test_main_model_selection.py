import unittest

from app import main


class MainModelSelectionTests(unittest.TestCase):
    def test_resolve_requested_model_returns_none_for_empty_values(self) -> None:
        self.assertIsNone(main._resolve_requested_model(None))
        self.assertIsNone(main._resolve_requested_model(""))
        self.assertIsNone(main._resolve_requested_model("   "))

    def test_resolve_requested_model_returns_trimmed_model(self) -> None:
        self.assertEqual(main._resolve_requested_model(" gemini-2.5-flash "), "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
