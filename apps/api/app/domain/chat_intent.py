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
import unicodedata
from typing import Literal

from app.domain.keywords import extract_jd_keywords

Intent = Literal[
    "generate",
    "generate_baseline",
    "refine",
    "profile_update",
    "proposal_turn",
    "clarify_scope",
    "converse",
    "question",
]

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


# --- new-posting vs refine-instruction discrimination (v6, Second Posting) -----------------
#
# Until v6 the router answered "is there an active resume?" and stopped there, so the SECOND
# job description pasted into a session was never a job description -- it became a refine
# instruction against the resume built for the FIRST one. The resume for posting #2 was a patch
# on posting #1's document (inheriting its language, which is how the bug was noticed), no new
# Analysis ran, and no Improvement Proposal was ever offered for the new job.
#
# Simply letting ``looks_like_job_description`` win would trade a silent failure for a noisy
# one: that heuristic fires on 30+ words, or 12+ words with 3 tech keywords, which a real refine
# instruction ("reescreve os bullets destacando React, Node, PostgreSQL, Docker e AWS") clears
# easily -- and a misroute the other way discards a refine session and opens a proposal the user
# never asked for. So three gates run in order instead, and the middle one demands a much
# stronger signal than ``looks_like_job_description`` ever did:
#
#   1. Does it read as an instruction aimed at the agent? -> refine (checked FIRST, so an
#      imperative wins even when it happens to name posting-ish nouns).
#   2. Does it carry the STRUCTURE of a posting -- the section headings a posting has and an
#      instruction never does? -> generate.
#   3. Neither, but it still looks JD-shaped? -> clarify_scope: ask, do not guess. Same valve
#      the refine prompt and the Analysis Turn already use (CONTEXT.md: Clarifying Question).

def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalized(message: str) -> str:
    """Lowercased, accent-folded, whitespace-collapsed -- so the phrase markers below match
    "Requisitos", "requisitos" and "REQUISITOS:" alike, and survive a posting pasted without
    its accents."""
    return re.sub(r"\s+", " ", _strip_accents(message).lower())


# Phrases that appear in a JOB POSTING and essentially never in an instruction to the agent.
# Matched as substrings of the accent-folded text, so each entry is written unaccented.
_POSTING_SECTION_MARKERS = (
    # pt-BR
    "requisitos",
    "responsabilidades",
    "atividades",
    "qualificacoes",
    "diferenciais",
    "sobre a empresa",
    "sobre a vaga",
    "sobre nos",
    "o que oferecemos",
    "o que buscamos",
    "beneficios",
    "desejavel",
    "estamos contratando",
    "buscamos",
    "procuramos",
    "faixa salarial",
    "regime de contratacao",
    "senioridade",
    "vaga para",
    # en
    "requirements",
    "responsibilities",
    "qualifications",
    "about the role",
    "about the company",
    "about us",
    "what you will do",
    "what you'll do",
    "what we offer",
    "benefits",
    "nice to have",
    "must have",
    "who you are",
    "job description",
    "we are looking for",
    "we are hiring",
    "you will be responsible",
)

# A posting long enough that a single section heading is already conclusive.
_POSTING_SINGLE_MARKER_MIN_WORDS = 60

# Verbs that open an order given TO THE AGENT about the document in front of it. Matched only
# among the first few words: "traduz o curriculo" is an instruction, while a posting that
# happens to contain "traduzir" in a requirements list is not.
_REFINE_IMPERATIVE_OPENERS = frozenset(
    {
        # pt-BR
        "tira", "tire", "tirar", "remove", "remova", "remover", "muda", "mude", "mudar",
        "troca", "troque", "trocar", "altera", "altere", "alterar", "adiciona", "adicione",
        "adicionar", "acrescenta", "acrescente", "inclui", "inclua", "incluir", "reescreve",
        "reescreva", "reescrever", "deixa", "deixe", "deixar", "coloca", "coloque", "colocar",
        "poe", "ponha", "ajusta", "ajuste", "ajustar", "aplica", "aplique", "aplicar",
        "atualiza", "atualize", "atualizar", "melhora", "melhore", "melhorar",
        "encurta", "encurte", "encurtar", "resume", "resuma", "resumir", "traduz", "traduza",
        "traduzir", "corrige", "corrija", "corrigir", "destaca", "destaque", "destacar",
        "reordena", "reordene", "reordenar", "foca", "foque", "focar", "usa", "use", "usar",
        "faz", "faca", "fazer", "gera", "gere", "gerar", "refaz", "refaca", "refazer",
        "prioriza", "priorize", "priorizar", "enfatiza", "enfatize", "apaga", "apague",
        "aumenta", "aumente", "diminui", "diminua", "inverte", "inverta", "mantem", "mantenha",
        # en
        "remove", "drop", "delete", "change", "swap", "add", "include", "rewrite", "make",
        "put", "adjust", "improve", "shorten", "summarize", "summarise", "translate", "fix",
        "highlight", "reorder", "focus", "use", "regenerate", "redo", "prioritize",
        "prioritise", "emphasize", "emphasise", "keep", "trim", "expand", "tweak", "polish",
        "reword", "replace", "move", "sort", "shrink", "lengthen",
    }
)

# How many leading words are scanned for an imperative opener. Enough to clear a politeness
# preamble ("por favor, tira ...", "can you rewrite ...") without reaching into the body of a
# pasted posting.
_IMPERATIVE_OPENER_WINDOW = 4


def _posting_marker_count(message: str) -> int:
    normalized = _normalized(message)
    return sum(1 for marker in _POSTING_SECTION_MARKERS if marker in normalized)


def looks_like_new_job_posting(message: str) -> bool:
    """Whether ``message`` carries the STRUCTURE of a job posting, not merely its vocabulary.

    Deliberately stricter than ``looks_like_job_description``: this is the signal allowed to
    override an active resume and start a whole new Analysis, so it requires either two distinct
    section markers, or one plus real length. ``looks_like_job_description`` stays the (looser)
    gate for the no-active-resume case, where there is nothing to lose by guessing generate.
    """
    if not looks_like_job_description(message):
        return False
    markers = _posting_marker_count(message)
    if markers >= 2:
        return True
    return markers >= 1 and len(message.split()) >= _POSTING_SINGLE_MARKER_MIN_WORDS


def looks_like_refine_instruction(message: str) -> bool:
    """Whether ``message`` reads as an order to the agent about the document it just produced.

    Two independent signals, either of which is enough: an imperative verb among the opening
    words, or an explicit mention of the document itself (``_RESUME_SCOPE_WORDS``) together with
    a change verb anywhere in the message ("quero o curriculo mais curto").
    """
    words = _normalized(message).split()
    if any(w.strip(".,;:!?") in _REFINE_IMPERATIVE_OPENERS for w in words[:_IMPERATIVE_OPENER_WINDOW]):
        return True
    tokens = _tokenize(message)
    if _mentions_any(tokens, _RESUME_SCOPE_WORDS) and (
        _mentions_any(tokens, _ACTION_VERBS)
        or not frozenset(w.strip(".,;:!?") for w in words).isdisjoint(_REFINE_IMPERATIVE_OPENERS)
    ):
        return True
    return False


# --- baseline (no-posting) resume requests (v6, Baseline Resume) -------------------------------
#
# Every generation path in this app is anchored to a pasted posting -- CONTEXT.md states the
# invariant outright ("No `generate` intent produces a Resume without an approved Improvement
# Proposal"). So "preciso de um curriculo um pouco mais generalista pra por no meu indeed" had
# nowhere to go: 13 words, zero JD keywords, so not a posting; no imperative, so not a refine
# instruction; and the fallback reply could only say "paste a job description". The user was not
# misunderstood -- the capability did not exist.
#
# A baseline request is recognized by TWO signals together, never one: it must name the document
# (``_RESUME_SCOPE_WORDS``) AND ask for breadth. Requiring both is what keeps "tira o Google
# Analytics do currículo" (document named, no breadth word) and a posting that happens to say
# "perfil generalista" (breadth word, document never named) out of this bucket.

_BREADTH_WORDS = frozenset(
    {
        # pt-BR
        "generalista",
        "generalistas",
        "generico",
        "genérico",
        "generica",
        "genérica",
        "geral",
        "abrangente",
        "amplo",
        "ampla",
        "base",
        "padrao",
        "padrão",
        "aberto",
        "aberta",
        # en
        "generalist",
        "generic",
        "general",
        "broad",
        "baseline",
        "master",
        "standard",
        "open",
        "all-purpose",
    }
)

# Places a baseline resume gets published. Naming one is itself the request ("um currículo pro
# meu Indeed" means an open resume even with no breadth adjective anywhere).
_JOB_BOARD_WORDS = frozenset({"indeed", "catho", "vagas", "infojobs", "glassdoor", "monster"})

# Phrases that say outright there is no posting behind the request.
_NO_POSTING_MARKERS = ("sem vaga", "sem uma vaga", "nao tenho vaga", "no specific job", "no job posting")


def looks_like_baseline_resume_request(message: str) -> bool:
    """Whether ``message`` asks for an OPEN resume -- one not aimed at a specific posting.

    Two independent ways to qualify, both of which still require the message to name the
    document itself, so this can never swallow a posting or an ordinary edit:
      - a breadth word (generalista / generic / base / broad ...), or
      - a job board the resume is destined for (Indeed, Catho, ...), or an explicit "no posting".
    """
    tokens = _tokenize(message)
    if not _mentions_any(tokens, _RESUME_SCOPE_WORDS):
        return False
    if _mentions_any(tokens, _BREADTH_WORDS) or _mentions_any(tokens, _JOB_BOARD_WORDS):
        return True
    normalized = _normalized(message)
    return any(marker in normalized for marker in _NO_POSTING_MARKERS)


def _looks_like_profile_update(message: str) -> bool:
    if looks_like_job_description(message):
        return False  # a genuine JD paste always wins -- see classify_intent's docstring
    tokens = _tokenize(message)
    if _mentions_any(tokens, _RESUME_SCOPE_WORDS):
        return False
    return _mentions_any(tokens, _ACTION_VERBS) and _mentions_any(tokens, _PROFILE_FACT_NOUNS)


def classify_intent(
    *, message: str, has_active_resume: bool, has_pending_proposal: bool = False
) -> Intent:
    """The single seam ``chat_service.handle_chat_turn`` calls to route a turn. No LLM call is
    spent deciding it (CONTEXT.md: Intent). Without a pending proposal, ``profile_update`` is
    checked FIRST -- it wins even over an active resume (a user mid-refine-session can still
    correct a profile fact without it being swallowed into a refine turn); the rest is the
    untouched v1 3-way routing.

    ``has_pending_proposal`` (v4 ticket B3, docs/v4-improvement-proposal.md SS2) is checked
    BEFORE the profile_update check above and wins UNCONDITIONALLY -- no message shape exempts
    it. Defaults to False so every pre-v4 call site (and every pinning test that predates this
    kwarg) is byte-identical.

    v4 ticket B4 originally tried to carve out an exception: while a proposal was pending, a
    message naming literal PROPOSAL-scope vocabulary ("sugestao"/"proposta"/"melhoria"/"item")
    was exempted from this rule and still routed to profile_update. QA-03 (P1, QA live) found
    the hole: the natural-language adjustment "adiciona também FastAPI nas skills ... e reordena
    os projetos ..." names no trigger word, so it slipped past the guard and was routed to
    profile_update -- silently writing a real ProfileVersion to the permanent Living Profile
    with no user confirmation. The guard was removed; the rule is now unconditional.

    Security/data-safety rationale (QA-03): the Pending Proposal window is short-lived (closed
    by approve or supersede) and, by construction, no deterministic heuristic can tell "adjust
    the proposal" apart from "update my permanent profile" with full reliability -- the
    vocabulary genuinely overlaps ("remove the FastAPI skill" reads identically either way).
    Given that ambiguity, routing MUST fail toward the non-destructive outcome: a misroute to
    ``proposal_turn`` is recoverable (the LLM replies or asks for clarification, nothing is
    written); the inverse misroute permanently corrupts profile data outside the negotiation the
    user is actually having. A user who wants to fix a profile fact mid-negotiation gets the
    conversational turn instead and can make the edit after approving or discarding the proposal.

    The two catch-all buckets are ``converse``, not the old ``question`` (a canned no-LLM reply)
    and ``refine`` (a silent edit). The default now assumes the user wants to TALK, not to edit:
    a turn only refines when it carries an explicit edit verb (``looks_like_refine_instruction``).
    Everything else with a resume open -- a real question, a soft "podia puxar mais pro backend",
    an off-schema "me manda um qualification summary" -- is a read-only conversation that never
    mutates the resume. This closes the reported bug where a question fell to the refine default
    and produced an unwanted diff. A genuinely edit-shaped but verb-less turn is not disambiguated
    here: it converses, and the conversation LLM (which reads the resume) is what asks "quer que
    eu aplique isso no currículo?" -- deterministic code cannot separate that from a plain
    question about the resume, so it routes to the non-mutating lane and lets the model decide.
    """
    if has_pending_proposal:
        return "proposal_turn"
    if _looks_like_profile_update(message):
        return "profile_update"
    if not has_active_resume:
        # Nothing to refine, so a baseline request is unambiguous here and is checked before the
        # posting heuristic (a baseline request is not posting-shaped anyway, but the order
        # states the precedence rather than relying on that).
        if looks_like_baseline_resume_request(message):
            return "generate_baseline"
        return "generate" if looks_like_job_description(message) else "converse"
    # An active resume no longer wins unconditionally (v6, Second Posting). Order matters and is
    # the whole safety argument -- see the block comment above ``looks_like_new_job_posting``.
    #
    # ``refine`` is checked BEFORE the baseline gate on purpose: with a document already open,
    # "deixa o currículo mais generalista" is an edit of THAT document (the user is pointing at
    # it), while "preciso de um currículo mais generalista" asks for a new one. The imperative is
    # what separates the two, and it is the only signal that reliably does.
    if looks_like_refine_instruction(message):
        return "refine"
    if looks_like_baseline_resume_request(message):
        return "generate_baseline"
    if looks_like_new_job_posting(message):
        return "generate"
    if looks_like_job_description(message):
        return "clarify_scope"
    # No explicit edit verb, not a posting -- assume conversation, never a silent edit.
    return "converse"
