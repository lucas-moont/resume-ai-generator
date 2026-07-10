"""Entity-identity primitives (v2 ticket 02 -- "Kernel de dominio do patch").

Shared by two callers: the anchor's anti-fabrication matching (``_anchor_generate_to_profile``
in ``app/services/llm/resume_json_parser.py``, which becomes a caller of this module) and the
future Deterministic Diff (ticket 03/04), which classifies extracted document data against the
Profile as new/divergent/equal. Pure functions only -- no I/O, no DB, no LLM.

Two normalizers, deliberately NOT unified (a decision recorded in the ticket):

- ``entity_key``: identity for entity NAMES (company, institution, project name) --
  case/accent/spacing-insensitive, alnum-only. Ex-``_norm_key``
  (``resume_json_parser.py``), extended here to transliterate accents (NFKD + strip combining
  marks) before stripping non-alnum characters -- the original ``_norm_key`` only deleted
  non-ASCII letters outright (so "Sao Paulo" and "São Paulo" produced *different* keys, "saopaulo"
  vs "sopaulo"). No existing characterization test exercises an accented entity name, so this is
  a deliberate improvement made during extraction, not a silent behavior change to the anchor's
  covered behavior -- and the Deterministic Diff needs real accent-insensitivity for PT-BR
  institution/company names.
- ``skill_token``: identity for SKILLS -- preserves ``.+#-`` so "C++" != "C" and "Node.js" keeps
  its dot. This is exactly ``domain.keywords.normalize_token`` (reused, not duplicated).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.domain.keywords import normalize_token as _skill_token_impl


def entity_key(value: object) -> str:
    """Alnum-only, case/accent/spacing-insensitive identity key for an entity name."""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def skill_token(value: object) -> str:
    """Identity token for a skill label -- preserves ``.+#-`` (e.g. "C++" != "C")."""
    return _skill_token_impl(str(value or ""))


def _title_norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def title_similarity(a: object, b: object) -> float:
    """Fuzzy [0,1] similarity between two role/title strings (case/accent/punctuation
    insensitive). A tie-breaker identity signal for the Deterministic Diff -- never the
    anchor's primary key, since a legitimately translated title (e.g. pt-BR) must still match
    its profile role via company+start alone."""
    ka, kb = _title_norm(a), _title_norm(b)
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


def _claim_first_unused(indices: list[int], used: list[bool]) -> int | None:
    for idx in indices:
        if not used[idx]:
            used[idx] = True
            return idx
    return None


def match_experience_entries(
    base: list[dict], candidates: list[object]
) -> list[dict | None]:
    """Identity match for ``experience``: primary key (company, start); company-only fallback
    for entries whose start date didn't normalize to an exact match (e.g. reformatted dates).
    Each candidate is claimed at most once, so two same-company base entries never collapse
    onto the same candidate. Returns one entry per ``base`` item, in order; ``None`` when
    unmatched. Non-dict candidates are ignored.
    """
    valid = [c for c in candidates if isinstance(c, dict)]
    used = [False] * len(valid)
    by_company_start: dict[str, list[int]] = {}
    by_company: dict[str, list[int]] = {}
    for idx, c in enumerate(valid):
        ck = entity_key(c.get("company"))
        if not ck:
            continue
        by_company.setdefault(ck, []).append(idx)
        sk = entity_key(c.get("start"))
        if sk:
            by_company_start.setdefault(f"{ck}|{sk}", []).append(idx)

    matched: list[dict | None] = [None] * len(base)
    for i, b in enumerate(base):
        ck, sk = entity_key(b.get("company")), entity_key(b.get("start"))
        if ck and sk:
            idx = _claim_first_unused(by_company_start.get(f"{ck}|{sk}", []), used)
            if idx is not None:
                matched[i] = valid[idx]
    for i, b in enumerate(base):
        if matched[i] is not None:
            continue
        ck = entity_key(b.get("company"))
        if ck:
            idx = _claim_first_unused(by_company.get(ck, []), used)
            if idx is not None:
                matched[i] = valid[idx]
    return matched


def match_education_entries(
    base: list[dict], candidates: list[object]
) -> list[dict | None]:
    """Identity match for ``education``: key is normalized ``institution`` alone. Each
    candidate claimed at most once (same rationale as experience). Returns one entry per
    ``base`` item, in order; ``None`` when unmatched.
    """
    valid = [c for c in candidates if isinstance(c, dict)]
    used = [False] * len(valid)
    by_institution: dict[str, list[int]] = {}
    for idx, c in enumerate(valid):
        ik = entity_key(c.get("institution"))
        if ik:
            by_institution.setdefault(ik, []).append(idx)

    matched: list[dict | None] = [None] * len(base)
    for i, b in enumerate(base):
        ik = entity_key(b.get("institution"))
        if ik:
            idx = _claim_first_unused(by_institution.get(ik, []), used)
            if idx is not None:
                matched[i] = valid[idx]
    return matched


def match_projects_by_name(candidates: list[object]) -> dict[str, dict]:
    """Lookup of candidate projects keyed by normalized ``name``. First occurrence wins for a
    duplicate normalized name (not claim-once -- matches the original anchor behavior, where a
    single patch project could legitimately back more than one profile project of the same
    name).
    """
    by_name: dict[str, dict] = {}
    for c in candidates:
        if isinstance(c, dict):
            k = entity_key(c.get("name"))
            if k:
                by_name.setdefault(k, c)
    return by_name


def build_skill_lookup(base_skills: list[str]) -> dict[str, str]:
    """Lookup of canonical (original-cased) skills keyed by ``skill_token``. First occurrence
    wins for a duplicate token."""
    lookup: dict[str, str] = {}
    for s in base_skills:
        tok = skill_token(s)
        if tok:
            lookup.setdefault(tok, s)
    return lookup
