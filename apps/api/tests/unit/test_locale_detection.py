import unittest

from app.domain.locale import (
    detect_locale as _detect_locale,
    mentions_language_change as _mentions_language_change,
    normalize_locale as _normalize_locale,
    resolve_locale as _resolve_locale,
)
from app.domain.quality import quality_issues, wrong_language_issue
from app.domain.schemas import ResumeDocument

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


class NormalizeLocaleTests(unittest.TestCase):
    """v6: the app writes two languages, but nothing stopped an LLM from labelling one of them
    a third way. ``en-US`` reached ``ResumeDocument.locale`` (a bare ``str``, validated by
    nothing) and 8 stored resume versions in the local DB carry it."""

    def test_region_subtags_are_dropped(self) -> None:
        self.assertEqual(_normalize_locale("en-US"), "en")
        self.assertEqual(_normalize_locale("en_US"), "en")
        self.assertEqual(_normalize_locale("EN-GB"), "en")

    def test_every_portuguese_variant_folds_onto_pt_br(self) -> None:
        # pt-BR is the only Portuguese this app writes, so pt-PT is not a third option.
        for value in ("pt", "pt-BR", "pt_BR", "PT-br", "pt-PT"):
            self.assertEqual(_normalize_locale(value), "pt-BR", value)

    def test_an_unsupported_language_returns_none_rather_than_a_guess(self) -> None:
        # None means "the caller decides" — this function never invents a language.
        self.assertIsNone(_normalize_locale("fr"))
        self.assertIsNone(_normalize_locale("es-AR"))
        self.assertIsNone(_normalize_locale(""))
        self.assertIsNone(_normalize_locale("   "))
        self.assertIsNone(_normalize_locale(None))
        self.assertIsNone(_normalize_locale(7))


class ResumeDocumentLocaleFoldingTests(unittest.TestCase):
    def test_an_invented_locale_label_is_folded_on_load(self) -> None:
        doc = ResumeDocument(fullName="X", headline="Y", summary="Z", locale="en-US")
        self.assertEqual(doc.locale, "en")

    def test_an_unsupported_locale_falls_back_instead_of_raising(self) -> None:
        # locale stays a `str` rather than a Literal precisely so this cannot raise: making it
        # a Literal would render the already-persisted en-US rows unloadable, breaking
        # rehydration of real sessions to fix a cosmetic drift.
        doc = ResumeDocument(fullName="X", headline="Y", summary="Z", locale="fr")
        self.assertEqual(doc.locale, "pt-BR")

    def test_a_supported_locale_is_untouched(self) -> None:
        self.assertEqual(
            ResumeDocument(fullName="X", headline="Y", summary="Z", locale="en").locale, "en"
        )


class MentionsLanguageChangeTests(unittest.TestCase):
    """The single licence for a refine to switch the document's language."""

    def test_an_instruction_about_language_is_recognized(self) -> None:
        for message in (
            "traduz para ingles",
            "traduza o currículo para inglês",
            "translate the resume to English",
            "muda o idioma para português",
        ):
            self.assertTrue(_mentions_language_change(message), message)

    def test_an_ordinary_edit_is_not_about_language(self) -> None:
        for message in (
            "deixa o resumo mais curto",
            "tira o Google Analytics das skills",
            "make the summary punchier",
            "reordena os projetos",
            "",
        ):
            self.assertFalse(_mentions_language_change(message), message)


class WrongLanguageIssueTests(unittest.TestCase):
    """v6: detection runs on the generated PROSE, never on the ``locale`` field — since that
    field is now pinned by the server it always says the right thing and can no longer reveal
    the drift."""

    def _resume(self, highlights: list[str], summary: str) -> ResumeDocument:
        return ResumeDocument(
            fullName="Ana Costa",
            headline="Senior Backend Engineer",
            summary=summary,
            experience=[
                {
                    "company": "Acme",
                    "title": "Senior Backend Engineer",
                    "start": "2021",
                    "end": None,
                    "highlights": highlights,
                }
            ],
            locale="pt-BR",
        )

    def _english(self) -> ResumeDocument:
        return self._resume(
            [
                "Led the migration of the billing service and designed the data layer for it",
                "Built and shipped the payments API with strong ownership of its reliability",
                "Mentored engineers and drove the code review culture across the whole team",
            ],
            "Senior backend engineer with strong experience building and shipping reliable "
            "services for the payments team, with a pragmatic approach to delivery.",
        )

    def test_an_english_document_for_a_portuguese_job_is_reported(self) -> None:
        issue = wrong_language_issue(self._english(), "pt-BR")
        self.assertIsNotNone(issue)
        self.assertIn("pt-BR", issue)
        self.assertIn("keeping every fact identical", issue)

    def test_a_matching_language_reports_nothing(self) -> None:
        self.assertIsNone(wrong_language_issue(self._english(), "en"))

    def test_no_expected_locale_reports_nothing(self) -> None:
        self.assertIsNone(wrong_language_issue(self._english(), None))

    def test_a_document_with_too_little_prose_is_not_judged(self) -> None:
        # Below the word floor detect_locale is not trustworthy, and a false "wrong language"
        # would trigger a full rewrite of a perfectly good document.
        thin = self._resume(["Shipped the API"], "Backend engineer.")
        self.assertIsNone(wrong_language_issue(thin, "pt-BR"))

    def test_skills_are_excluded_from_the_language_signal(self) -> None:
        # Technology names look the same in both languages; counting them would bias English.
        pt = self._resume(
            [
                "Desenvolvi a migração do serviço de cobrança e desenhei a camada de dados dele",
                "Construí e entreguei a API de pagamentos com responsabilidade pela confiabilidade",
                "Orientei pessoas do time e conduzi a cultura de revisão de código na equipe",
            ],
            "Desenvolvedor back-end sênior com experiência sólida em construir e entregar "
            "serviços confiáveis para o time de pagamentos, com uma abordagem pragmática.",
        )
        pt = pt.model_copy(update={"skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"]})
        self.assertIsNone(wrong_language_issue(pt, "pt-BR"))

    def test_the_language_issue_leads_the_issue_list(self) -> None:
        # A resume in the wrong language fails the reader no matter how good its bullets are.
        issues = quality_issues(self._english(), "Vaga em português", expected_locale="pt-BR")
        self.assertTrue(issues)
        self.assertIn("pt-BR", issues[0])
