"""Job Listing identity (v7 ticket 03) -- the key two postings must share to be ONE listing.

CONTEXT.md (Job Listing): "deduplicated across boards by normalized company + normalized
title". This module owns that normalization and nothing else: pure functions, no I/O, no DB,
no LLM -- the same discipline as ``domain/entity_identity.py``, whose character-level
normalizers this module is built on rather than re-deriving:

* ``entity_key`` (accent/case/punctuation-insensitive, alnum-only) is the token normalizer for
  the COMPANY side -- a company name is exactly the kind of entity name it was written for.
* ``skill_token`` (preserves ``.+#-``) is the token normalizer for the TITLE side, because a
  title can carry a technology name whose punctuation is load-bearing: collapsing it the way
  ``entity_key`` does would make "C# Developer" and "C++ Developer" -- two genuinely different
  jobs at the same company -- a single Job Listing. It is applied to an already-transliterated
  string (``_deaccent``) since ``skill_token`` deliberately does not strip accents (it would
  turn "Sênior" into "snior" and never match "Senior").

The asymmetry that governs every judgment call here: **over-normalizing is the worse failure**.
Two keys that should have merged only cost the user a duplicate card; two keys that merge when
they should not make a real job disappear from the list (it becomes a Listing Source of another
job). So each rule below strips only what is provably noise -- a closed vocabulary of corporate
suffixes, of work-arrangement markers, and of seniority synonyms -- and never anything merely
suspicious. Locations in a title, notably, are left alone: the set of place names is open, and
"Engineer (Berlin)" vs "Engineer (Munich)" are two openings.
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.entity_identity import entity_key, skill_token

# --- Company -------------------------------------------------------------------------------

# Trailing legal-form markers a board may or may not print ("Acme" on Indeed, "Acme Ltda." on
# LinkedIn, "Acme, Inc." on Glassdoor -- one employer). Stripped only from the END, and never
# down to nothing: a company literally named "Ltda" keeps its only token.
_COMPANY_SUFFIXES = frozenset(
    {
        # pt-BR
        "ltda", "eireli", "epp", "me", "sa",
        # en
        "inc", "incorporated", "llc", "llp", "ltd", "limited", "plc", "corp", "corporation",
        "co", "company", "holding", "holdings",
        # de / nl / it / es / fr
        "gmbh", "mbh", "ag", "kg", "bv", "nv", "srl", "spa", "sas", "sarl", "sl",
    }
)

# Glue characters removed BEFORE tokenizing a company, so a dotted/slashed legal form collapses
# into one token the suffix list can recognize: "S.A." and "S/A" both become "sa", "Trader
# Joe's" becomes "joes", "Booking.com" becomes "bookingcom".
_COMPANY_GLUE_RE = re.compile(r"[.'’`/]")
_WORD_SPLIT_RE = re.compile(r"[^0-9A-Za-zÀ-ɏ]+")


def _company_tokens(value: object) -> list[str]:
    glued = _COMPANY_GLUE_RE.sub("", str(value or ""))
    return [t for t in (entity_key(p) for p in _WORD_SPLIT_RE.split(glued)) if t]


def normalize_company(value: object) -> str:
    """Identity form of an employer name: lowercase, accent-free, punctuation-free, without
    trailing legal-form suffixes.

    Tokens are joined with NOTHING, exactly as ``entity_key`` joins them -- word boundaries
    are not identity here, because the same employer is printed "Acme Tech" on one board and
    "AcmeTech" on another. It costs readability in a stored key ("acmetech|seniorbackend…")
    and buys the merge those two spellings need.
    """
    tokens = _company_tokens(value)
    while len(tokens) > 1 and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


# --- Title ---------------------------------------------------------------------------------

# Split on ``+#.`` preserved so "C++", "C#", ".NET" and "Node.js" survive as tokens.
_TITLE_SPLIT_RE = re.compile(r"[^0-9A-Za-zÀ-ɏ.+#]+")

# Segment separators boards use to bolt an annotation onto a title
# ("Backend Engineer | Remote", "Backend Engineer - Remote"). A bare hyphen is only a separator
# when surrounded by spaces, so "Front-end Developer" stays one segment.
_TITLE_SEGMENT_RE = re.compile(r"\s*[|·•—–]\s*|\s+-\s+")

_BRACKETED_RE = re.compile(r"[(\[{]([^)\]}]*)[)\]}]")

# A bracketed group or a trailing segment is dropped only when its WHOLE content is one of
# these -- work arrangement, contract form, or the gender markers German-language boards append.
# Anything else (a team name, a product, a city) is kept, because it may be what distinguishes
# two openings at the same employer.
_NOISE_PHRASES = frozenset(
    {
        "remote", "remoto", "remota", "remote work", "trabalho remoto", "fully remote",
        "100 remote", "remote first", "remote friendly", "anywhere", "work from home",
        "home office", "homeoffice",
        "hybrid", "hibrido", "hibrida", "onsite", "on site", "presencial",
        "pj", "clt", "cnpj",
        "full time", "fulltime", "part time", "parttime",
        "m f", "f m", "m f d", "m w d", "w m d", "m f x", "m f d x", "d f m", "h f", "f h",
        "m f diverse", "all genders",
    }
)

# Seniority written two ways is one seniority. Mapped to a canonical token (which is KEPT --
# "Senior Engineer" and "Junior Engineer" are different jobs), then de-duplicated, so a board
# that prints it twice ("Sr. Senior Developer") matches one that prints it once.
_SENIORITY_ALIASES = {
    "sr": "senior",
    "snr": "senior",
    "senior": "senior",
    "jr": "junior",
    "jnr": "junior",
    "junior": "junior",
    "pl": "mid",
    "pleno": "mid",
    "mid": "mid",
    "middle": "mid",
}
_SENIORITY_CANON = frozenset(_SENIORITY_ALIASES.values())

# Tokens that only ever qualify a seniority word ("Mid-Level" == "Mid").
_TITLE_FILLER = frozenset({"level", "nivel"})


def _deaccent(value: str) -> str:
    """NFKD transliteration -- the same pass ``entity_key`` applies internally, repeated here
    because the title side needs it BEFORE ``skill_token`` (which preserves ``.+#-`` but does
    not transliterate, so "Sênior" would come out as "snior")."""
    s = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _title_tokens(value: object) -> list[str]:
    tokens: list[str] = []
    for part in _TITLE_SPLIT_RE.split(str(value or "")):
        token = skill_token(_deaccent(part)).strip(".-")
        if token:
            tokens.append(token)
    return tokens


def _is_noise(text: str) -> bool:
    return " ".join(_title_tokens(text)) in _NOISE_PHRASES


def _strip_noise_brackets(title: str) -> str:
    return _BRACKETED_RE.sub(lambda m: "" if _is_noise(m.group(1)) else m.group(0), title)


def _drop_noise_segments(title: str) -> str:
    segments = _TITLE_SEGMENT_RE.split(title)
    kept = [s for s in segments if s.strip() and not _is_noise(s)]
    # A title made of nothing but noise ("Remote | Remote") keeps its original text: an empty
    # title side would collapse every such posting from one employer into one listing.
    return " ".join(kept) if kept else title


def _canonical_title_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    seen_seniority: set[str] = set()
    for token in tokens:
        if token in _TITLE_FILLER:
            continue
        canonical = _SENIORITY_ALIASES.get(token, token)
        if canonical in _SENIORITY_CANON:
            if canonical in seen_seniority:
                continue
            seen_seniority.add(canonical)
        out.append(canonical)
    return out


def normalize_title(value: object) -> str:
    """Identity form of a job title: lowercase, accent-free, without work-arrangement noise
    ("(Remote)", "| Remote", "(m/f/d)"), with seniority synonyms folded onto one spelling and
    a repeated seniority collapsed. Technology punctuation is preserved ("c#developer").

    Joined without separators like the company side, which is what makes the hyphenation
    boards disagree on -- "Front-end Developer", "Front End Developer", "Frontend Developer" --
    one title instead of three.
    """
    text = _drop_noise_segments(_strip_noise_brackets(str(value or "")))
    return "".join(_canonical_title_tokens(_title_tokens(text)))


# --- The key -------------------------------------------------------------------------------


def identity_key(company: object, title: object) -> str:
    """The Job Listing identity (CONTEXT.md: Job Listing, Listing Memory).

    ``normalize_company(company) + "|" + normalize_title(title)``. Two postings sharing it are
    one Job Listing with two Listing Sources; a Listing Memory row is keyed by it, which is why
    it must stay stable across Scans -- changing any rule in this module orphans every memory
    written by the previous one (``acmetech|seniorbackendengineer``).

    The separator is a literal ``|``, which neither normalizer can emit, so the two halves are
    unambiguous. A posting missing both company and title yields ``"|"``: garbage in, one
    deterministic key out -- callers filter empty postings, this function does not judge.
    """
    return f"{normalize_company(company)}|{normalize_title(title)}"
