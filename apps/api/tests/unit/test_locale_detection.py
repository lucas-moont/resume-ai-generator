import unittest

from app.main import _detect_locale, _resolve_locale

_EN_JD = (
    "We are hiring a JavaScript Frontend Developer. Develop and maintain applications "
    "using modern frameworks such as React. Experience with Node.js and REST APIs is required. "
    "Participate in code reviews and adhere to best practices."
)
_PT_JD = (
    "Estamos contratando uma pessoa desenvolvedora Front-End. A vaga exige experiência com "
    "React e Node.js, além de conhecimento em APIs REST. É desejável atuar em equipe e "
    "participar de revisões de código seguindo boas práticas."
)


class LocaleDetectionTests(unittest.TestCase):
    def test_detects_english_job(self) -> None:
        self.assertEqual(_detect_locale(_EN_JD), "en")

    def test_detects_portuguese_job(self) -> None:
        self.assertEqual(_detect_locale(_PT_JD), "pt-BR")

    def test_returns_none_for_empty_or_neutral_text(self) -> None:
        self.assertIsNone(_detect_locale(""))
        self.assertIsNone(_detect_locale("   "))
        self.assertIsNone(_detect_locale("React Node.js TypeScript 2024"))


class ResolveLocaleTests(unittest.TestCase):
    def test_explicit_locale_overrides_detection(self) -> None:
        # A Portuguese JD must still yield English when the user forces "en".
        self.assertEqual(_resolve_locale("en", _PT_JD, "pt-BR"), "en")
        self.assertEqual(_resolve_locale("pt-BR", _EN_JD, "en"), "pt-BR")

    def test_auto_detects_from_job_description(self) -> None:
        self.assertEqual(_resolve_locale("auto", _EN_JD, "pt-BR"), "en")
        self.assertEqual(_resolve_locale("auto", _PT_JD, "en"), "pt-BR")

    def test_none_locale_behaves_as_auto(self) -> None:
        self.assertEqual(_resolve_locale(None, _EN_JD, "pt-BR"), "en")

    def test_falls_back_to_profile_then_default_when_inconclusive(self) -> None:
        neutral = "React Node.js TypeScript"
        self.assertEqual(_resolve_locale("auto", neutral, "en"), "en")
        self.assertEqual(_resolve_locale("auto", neutral, None), "pt-BR")


if __name__ == "__main__":
    unittest.main()
