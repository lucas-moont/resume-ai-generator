"""Locale auto-detection (pt-BR vs en) -- extracted from app/main.py (B2).

The app only writes resumes in Portuguese or English, so a dependency-free, deterministic
heuristic (distinctive function words + Portuguese diacritics) is preferred over a heavier
language-detection library that would add non-determinism and an offline-unfriendly dependency.
"""

import re

_DEFAULT_LOCALE = "pt-BR"
_SUPPORTED_LOCALES = frozenset({"pt-BR", "en"})
_PT_DIACRITICS = frozenset("ãõáéíóúâêôàçÃÕÁÉÍÓÚÂÊÔÀÇ")
# Highly Portuguese-specific tokens (avoid forms that are also common English words).
_PT_LANG_WORDS = frozenset(
    {
        "de", "da", "do", "das", "dos", "para", "com", "uma", "que", "voce", "você", "não", "nao",
        "experiência", "experiencia", "desenvolvimento", "vaga", "requisitos", "conhecimento",
        "conhecimentos", "trabalho", "equipe", "habilidades", "ferramentas", "responsável",
        "responsavel", "desejável", "desejavel", "atuar", "sólidos", "solidos", "área", "area",
        "empresa", "atividades", "diferencial", "salário", "salario", "benefícios", "beneficios",
    }
)
# Highly English-specific tokens.
_EN_LANG_WORDS = frozenset(
    {
        "the", "and", "with", "for", "you", "your", "our", "are", "have", "will", "role",
        "experience", "development", "requirements", "skills", "work", "team", "ability",
        "knowledge", "strong", "must", "we", "responsibilities", "proficiency", "familiarity",
        "such", "including", "features", "code", "applications", "best", "practices",
    }
)


def _detect_locale(text: str) -> str | None:
    """Detect whether free-form text is Portuguese or English.

    Returns "pt-BR", "en", or None when there is not enough signal to decide.
    """
    if not text or not text.strip():
        return None
    lowered = text.lower()
    tokens = re.findall(r"[a-zà-ÿ]+", lowered)
    if not tokens:
        return None
    pt_hits = sum(1 for t in tokens if t in _PT_LANG_WORDS)
    en_hits = sum(1 for t in tokens if t in _EN_LANG_WORDS)
    # Diacritics are a near-certain Portuguese signal; weight them but do not let them dominate.
    diacritics = sum(1 for ch in text if ch in _PT_DIACRITICS)
    pt_score = pt_hits + min(diacritics, 8) * 0.5
    en_score = float(en_hits)
    if pt_score == en_score:
        return None
    return "pt-BR" if pt_score > en_score else "en"


def _resolve_locale(requested: str | None, job_description: str, profile_locale: str | None) -> str:
    """Resolve the output locale.

    Explicit "pt-BR"/"en" always win. "auto" (or empty) triggers job-description language
    detection, falling back to the profile locale and finally the app default.
    """
    if requested in _SUPPORTED_LOCALES:
        return requested  # explicit manual override
    detected = _detect_locale(job_description)
    if detected:
        return detected
    if profile_locale in _SUPPORTED_LOCALES:
        return profile_locale
    return _DEFAULT_LOCALE
