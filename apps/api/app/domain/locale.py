"""Locale auto-detection (pt-BR vs en) -- extracted from app/main.py (B2).

The app only writes resumes in Portuguese or English, so a dependency-free, deterministic
heuristic (distinctive function words + Portuguese diacritics) is preferred over a heavier
language-detection library that would add non-determinism and an offline-unfriendly dependency.
"""

import re

DEFAULT_LOCALE = "pt-BR"
SUPPORTED_LOCALES = frozenset({"pt-BR", "en"})
PT_DIACRITICS = frozenset("ãõáéíóúâêôàçÃÕÁÉÍÓÚÂÊÔÀÇ")
# Highly Portuguese-specific tokens (avoid forms that are also common English words).
PT_LANG_WORDS = frozenset(
    {
        "de", "da", "do", "das", "dos", "para", "com", "uma", "que", "voce", "você", "não", "nao",
        "experiência", "experiencia", "desenvolvimento", "vaga", "requisitos", "conhecimento",
        "conhecimentos", "trabalho", "equipe", "habilidades", "ferramentas", "responsável",
        "responsavel", "desejável", "desejavel", "atuar", "sólidos", "solidos", "área", "area",
        "empresa", "atividades", "diferencial", "salário", "salario", "benefícios", "beneficios",
    }
)
# Highly English-specific tokens.
EN_LANG_WORDS = frozenset(
    {
        "the", "and", "with", "for", "you", "your", "our", "are", "have", "will", "role",
        "experience", "development", "requirements", "skills", "work", "team", "ability",
        "knowledge", "strong", "must", "we", "responsibilities", "proficiency", "familiarity",
        "such", "including", "features", "code", "applications", "best", "practices",
    }
)


def detect_locale(text: str) -> str | None:
    """Detect whether free-form text is Portuguese or English.

    Returns "pt-BR", "en", or None when there is not enough signal to decide.
    """
    if not text or not text.strip():
        return None
    lowered = text.lower()
    tokens = re.findall(r"[a-zà-ÿ]+", lowered)
    if not tokens:
        return None
    pt_hits = sum(1 for t in tokens if t in PT_LANG_WORDS)
    en_hits = sum(1 for t in tokens if t in EN_LANG_WORDS)
    # Diacritics are a near-certain Portuguese signal; weight them but do not let them dominate.
    diacritics = sum(1 for ch in text if ch in PT_DIACRITICS)
    pt_score = pt_hits + min(diacritics, 8) * 0.5
    en_score = float(en_hits)
    if pt_score == en_score:
        return None
    return "pt-BR" if pt_score > en_score else "en"


# Words that mean the user's instruction is ABOUT language. Nothing else may change a
# document's language (see ``mentions_language_change``), so this vocabulary is the entire
# licence for a refine to switch it.
_LANGUAGE_CHANGE_WORDS = frozenset(
    {
        # pt-BR
        "traduz", "traduza", "traduzir", "traducao", "tradução", "idioma", "lingua", "língua",
        "ingles", "inglês", "portugues", "português", "bilingue", "bilíngue",
        # en
        "translate", "translated", "translation", "language", "english", "portuguese",
        "brazilian",
    }
)


def mentions_language_change(message: str) -> bool:
    """Whether a refine instruction is about the document's LANGUAGE.

    Used as a licence, not a command: when it is False the caller pins the document to the
    language it already had, so the model cannot switch it as a side effect of an unrelated
    edit. When True the caller stands back and lets the LLM answer the actual request -- a user
    asking "traduz para inglês" must still get English.
    """
    if not message:
        return False
    tokens = set(re.findall(r"[a-zà-ÿ]+", message.lower()))
    return not tokens.isdisjoint(_LANGUAGE_CHANGE_WORDS)


def normalize_locale(value: object) -> str | None:
    """Fold a locale-ish string onto one of ``SUPPORTED_LOCALES``, or ``None`` if it is not one.

    The app writes resumes in exactly two languages, but nothing stopped an LLM from returning
    a third label for one of them: ``en-US`` reached ``ResumeDocument.locale`` (a bare ``str``,
    validated by nothing) and was persisted as-is -- 8 stored resume versions carry it. Every
    consumer then has to guess: the preview's ``startsWith('pt')`` happens to survive it, an
    equality check against ``"en"`` does not.

    Region subtags are dropped (``en-US`` -> ``en``, ``pt_BR`` -> ``pt-BR``) and any Portuguese
    variant folds onto ``pt-BR``, since that is the only Portuguese this app writes. Anything
    genuinely unsupported returns ``None`` so the caller decides -- this function never invents
    a language for a document.
    """
    if not isinstance(value, str):
        return None
    tag = value.strip().replace("_", "-").lower()
    if not tag:
        return None
    primary = tag.split("-")[0]
    if primary == "pt":
        return "pt-BR"
    if primary == "en":
        return "en"
    return None


def resolve_locale(requested: str | None, job_description: str, profile_locale: str | None) -> str:
    """Resolve the output locale.

    Explicit "pt-BR"/"en" always win. "auto" (or empty) triggers job-description language
    detection, falling back to the profile locale and finally the app default.
    """
    if requested in SUPPORTED_LOCALES:
        return requested  # explicit manual override
    detected = detect_locale(job_description)
    if detected:
        return detected
    if profile_locale in SUPPORTED_LOCALES:
        return profile_locale
    return DEFAULT_LOCALE
