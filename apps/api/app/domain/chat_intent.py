"""Deterministic chat intent classification (CONTEXT.md: Intent) -- extracted from
``chat_service.handle_chat_turn`` (pre-v2 chat_service.py:125-130) as v2 ticket 05's mandatory
first step.

``classify_intent`` reproduces the v1 3-way routing byte-for-byte:

- No active resume + the message reads like a pasted job description
  (``looks_like_job_description``, a length + JD-keyword-density heuristic) -> ``generate``.
- An active resume exists -> ``refine``, REGARDLESS of what the message says. This is the
  riskiest line in the original inline code (an active resume wins even over text that reads
  exactly like another job posting, or a one-word "ok") -- see
  ``tests/unit/test_chat_intent.py::TestV1PinnedRouting`` for the pinning tests run against
  this extraction to prove no behavior changed.
- Neither -> ``question`` (a canned, locale-aware reply -- no LLM call).

``profile_update`` (v2 ticket 05) is layered BEFORE this routing. CONTEXT.md draws the line as
"refine acts on the Resume, profile_update acts on facts of the Profile" -- see
``_looks_like_profile_update`` below for the deterministic pattern, and
``tests/unit/test_chat_intent.py::TestProfileUpdateVsRefineBoundary`` for the documented,
tested decisions on every ambiguous case this was tuned against.
"""

from __future__ import annotations

import re
from typing import Literal

from app.domain.keywords import extract_jd_keywords

Intent = Literal["generate", "refine", "profile_update", "proposal_turn", "question"]

# A message needs to be substantial to be treated as a pasted job description outright; a
# shorter message can still count if it is dense with recognizable tech/role keywords (e.g.
# someone pasting just the "Requirements" bullet list rather than the full posting).
_JD_MIN_WORDS_STRONG_SIGNAL = 30
_JD_MIN_WORDS_WEAK_SIGNAL = 12
_JD_MIN_KEYWORDS_WEAK_SIGNAL = 3


def looks_like_job_description(message: str) -> bool:
    words = message.split()
    if len(words) >= _JD_MIN_WORDS_STRONG_SIGNAL:
        return True
    if len(words) >= _JD_MIN_WORDS_WEAK_SIGNAL:
        return len(extract_jd_keywords(message)) >= _JD_MIN_KEYWORDS_WEAK_SIGNAL
    return False


# --- profile_update pattern (v2 ticket 05) -------------------------------------------------
#
# Deterministic, no LLM call spent deciding it. The question is never "is this a well-formed
# instruction" but "does it name a PROFILE FACT (contact info, a credential, an entity to
# add/remove) using a change/add/remove verb" -- every case this vocabulary was tuned against,
# including the ones that deliberately stay `refine`, is in
# tests/unit/test_chat_intent.py::TestProfileUpdateVsRefineBoundary.

_TOKEN_RE = re.compile(r"[a-zà-ÿ]+")


def _tokenize(message: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(message.lower()))


def _mentions_any(tokens: frozenset[str], vocab: frozenset[str]) -> bool:
    return not tokens.isdisjoint(vocab)


# An explicit mention of the rendered document always wins: "adiciona React no resumo" is a
# refine even though "adiciona" + a profile-fact noun would otherwise match below. A project
# literally named e.g. "Resume Agent" is a known, accepted collision with this gate (see the
# test suite) -- not worth a more complex heuristic for.
_RESUME_SCOPE_WORDS = frozenset({"resumo", "curriculo", "currículo", "resume", "cv", "documento"})

_ACTION_VERBS = frozenset(
    {
        # pt-BR: change-in-place ("mudei"/"atualizei"/"corrigi" my X)
        "mudei", "mudar", "mude", "atualizei", "atualizar", "atualize", "alterei", "alterar",
        "altere", "troquei", "trocar", "troque", "corrigi", "corrigir", "corrija",
        # pt-BR: add
        "adiciona", "adicione", "adicionar", "adicionei", "inclui", "inclua", "incluir",
        # pt-BR: remove
        "remove", "remova", "remover", "removi", "tira", "tire", "tirar", "exclui", "exclua",
        "excluir", "apaga", "apague", "apagar",
        # en: change-in-place
        "changed", "change", "update", "updated", "fixed", "fix", "corrected", "correct",
        # en: add
        "add", "added", "include", "included",
        # en: remove
        "remove", "removed", "delete", "deleted", "drop", "dropped",
    }
)

_PROFILE_FACT_NOUNS = frozenset(
    {
        # contact/identity fields
        "telefone", "celular", "email", "endereco", "endereço", "linkedin", "github", "phone",
        "address",
        # credentials -- this schema has no dedicated "certifications" field (see
        # prompts/system/profile_update.md); the noun is still a recognizable profile fact
        "certificacao", "certificação", "certificado", "certification", "certifications",
        # entities -- shared vocabulary with the ProfileMaster schema itself
        "projeto", "project", "projects",
        "formacao", "formação", "educacao", "educação", "education", "faculdade", "universidade",
        "experiencia", "experiência", "experience", "emprego", "empresa", "company", "job",
        "cargo", "role", "title",
        "habilidade", "skill", "skills", "competencia", "competência",
    }
)


def _looks_like_profile_update(message: str) -> bool:
    if looks_like_job_description(message):
        return False  # a genuine JD paste always wins -- see classify_intent's docstring
    tokens = _tokenize(message)
    if _mentions_any(tokens, _RESUME_SCOPE_WORDS):
        return False
    return _mentions_any(tokens, _ACTION_VERBS) and _mentions_any(tokens, _PROFILE_FACT_NOUNS)


# --- proposal_turn vs. profile_update guard (v4 ticket B4, spec SS2) -----------------------
#
# A Pending Proposal introduces a second kind of "scope" a message can name (on top of the
# resume-scope gate above): the proposal itself. "remove a sugestao sobre skills" reads exactly
# like a profile_update ("remove" + "skills") to the pattern above, but with a proposal pending
# it means "adjust the proposal", not "delete the skill from my permanent profile" -- the same
# vocabulary the spec hands us verbatim.
_PROPOSAL_SCOPE_WORDS = frozenset(
    {
        "sugestao", "sugestão", "proposta", "melhoria", "melhorias", "item",
        "suggestion", "suggestions", "proposal", "improvement", "improvements",
    }
)


def _mentions_proposal_scope(message: str) -> bool:
    return _mentions_any(_tokenize(message), _PROPOSAL_SCOPE_WORDS)


def classify_intent(
    *, message: str, has_active_resume: bool, has_pending_proposal: bool = False
) -> Intent:
    """The single seam ``chat_service.handle_chat_turn`` calls to route a turn. No LLM call is
    spent deciding it (CONTEXT.md: Intent). ``profile_update`` is checked FIRST -- it wins even
    over an active resume (a user mid-refine-session can still correct a profile fact without
    it being swallowed into a refine turn); the rest is the untouched v1 3-way routing.

    ``has_pending_proposal`` (v4 ticket B3, docs/v4-improvement-proposal.md SS2): a session with
    a Pending Proposal routes to ``proposal_turn`` next -- AFTER the profile_update check above,
    BEFORE the v1 3-way routing below. Defaults to False so every pre-v4 call site (and every
    pinning test that predates this kwarg) is byte-identical.

    v4 ticket B4 adds the guard the spec calls for: while a proposal is pending, a message that
    names PROPOSAL scope (``_PROPOSAL_SCOPE_WORDS`` -- "sugestao"/"proposta"/"melhoria"/"item"/
    their English counterparts) is exempted from the profile_update check entirely, even when it
    would otherwise match (action verb + profile-fact noun) -- "remove a sugestao sobre skills"
    means "adjust the proposal's skills item", not "delete skills from my permanent profile".
    Without a pending proposal this guard never fires (there is no proposal to be talking
    about), so every pre-B4 profile_update test is unaffected.
    """
    profile_update_guarded = has_pending_proposal and _mentions_proposal_scope(message)
    if not profile_update_guarded and _looks_like_profile_update(message):
        return "profile_update"
    if has_pending_proposal:
        return "proposal_turn"
    if not has_active_resume and looks_like_job_description(message):
        return "generate"
    if has_active_resume:
        return "refine"
    return "question"
