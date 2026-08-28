"""Unit tests for app/domain/chat_intent.py (v2 ticket 05 -- "Chat: intencao profile_update").

``TestV1PinnedRouting`` characterizes the v1 3-way routing (generate/refine/question) as it
lived inline in ``chat_service.handle_chat_turn`` before this module existed -- originally
proving the extraction was a pure move rather than a rewrite. Two of its assertions have since
been deliberately flipped: v6 turned a pasted posting into ``generate`` (see
``test_a_job_description_pasted_with_an_active_resume_is_now_generate``), and the conversation
intent turned the two catch-all buckets -- the no-resume ``question`` fallback and the
active-resume ``refine`` default -- into ``converse``. Each flipped assertion documents why in
place of the old expectation; every other line still pins v1 behavior unchanged.
``TestProfileUpdateVsRefineBoundary`` documents the 4th intent added on top in the same module,
``TestSecondPostingRouting`` the v6 routing, and ``TestConversationRouting`` the read-only
conversation lane that now wins whenever a turn is not an explicit edit.
"""

from __future__ import annotations

from app.domain.baseline_brief import build_baseline_brief, has_career_target, is_target_brief
from app.domain.chat_intent import (
    classify_intent,
    looks_like_baseline_resume_request,
    looks_like_job_description,
    looks_like_new_job_posting,
    looks_like_refine_instruction,
)
from app.domain.schemas import ResumeDocument

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


class TestV1PinnedRouting:
    """Pins chat_service.py's pre-extraction inline logic (lines ~125-130): a long/keyword-dense
    job description with no active resume routes to generate; an explicit edit instruction with a
    resume active routes to refine. The two v1 catch-all buckets -- everything else with no
    resume, and everything else with a resume -- used to be ``question`` (canned) and ``refine``
    (a silent edit) respectively; both are now ``converse`` (see the flipped tests below and
    ``TestConversationRouting``)."""

    def test_pasted_job_description_with_no_active_resume_is_generate(self) -> None:
        assert classify_intent(message=GENERIC_JOB_DESCRIPTION, has_active_resume=False) == "generate"

    def test_short_keyword_dense_requirements_list_with_no_active_resume_is_generate(self) -> None:
        # 12+ words, dense with recognized tech keywords (>= 3) -- the weak-signal branch of
        # looks_like_job_description, distinct from the strong (30+ word) signal above.
        weak_signal_jd = (
            "Requirements: strong hands-on experience with Python, FastAPI, PostgreSQL, Docker, "
            "Kubernetes, AWS, and GraphQL is required for this role."
        )
        assert classify_intent(message=weak_signal_jd, has_active_resume=False) == "generate"

    def test_greeting_with_no_active_resume_is_now_converse(self) -> None:
        # Was "question" (a canned no-LLM reply). A greeting now opens the conversation lane like
        # any other non-posting turn: one contract, no heuristic guessing whether "hi" is trivial.
        assert classify_intent(message="hi there", has_active_resume=False) == "converse"

    def test_short_ambiguous_instruction_with_no_active_resume_is_now_converse(self) -> None:
        # Was "question". With nothing to refine and no posting to generate from, this is a plain
        # conversational turn -- the agent answers (or asks) instead of returning canned text.
        assert classify_intent(message="Make the summary punchier.", has_active_resume=False) == "converse"

    def test_an_explicit_edit_with_an_active_resume_is_refine(self) -> None:
        # "make" is an imperative opener, so this stays an edit -- the tightened refine still
        # fires on a clear edit verb even though the catch-all default is now converse.
        assert classify_intent(message="Make the summary punchier.", has_active_resume=True) == "refine"

    def test_a_job_description_pasted_with_an_active_resume_is_now_generate(self) -> None:
        # DELIBERATELY CHANGED in v6 (Second Posting). This used to assert "refine", pinning what
        # ticket 02/04's notes already called the riskiest line in the original code: `elif
        # active_resume_row is not None` caught a pasted posting BEFORE any JD check ran, so an
        # active resume won even over text that reads exactly like a job posting.
        #
        # That is the bug: the second posting in a session was never treated as a posting. It
        # became an edit of the first posting's resume, which is why the resume for job #2 came
        # out in job #1's language. This message carries a section marker ("we are hiring") and
        # 60+ words, so it clears looks_like_new_job_posting and routes to generate. See
        # TestSecondPostingRouting for the gray zone, and for the false positives still avoided.
        assert classify_intent(message=GENERIC_JOB_DESCRIPTION, has_active_resume=True) == "generate"

    def test_translate_instruction_with_active_resume_is_refine(self) -> None:
        assert classify_intent(message="Translate the resume to English.", has_active_resume=True) == "refine"

    def test_short_nonsense_with_active_resume_is_now_converse(self) -> None:
        # The v1 risk boundary called out in ticket 05 is exactly what the conversation lane
        # closes: a short, ambiguous message with an active resume used to fall to the refine
        # DEFAULT and silently edit the document. With no edit verb it is now a conversational
        # turn -- nothing is mutated.
        assert classify_intent(message="ok", has_active_resume=True) == "converse"
        assert classify_intent(message="hmm sure", has_active_resume=True) == "converse"


class TestLooksLikeJobDescriptionUnchanged:
    """``looks_like_job_description`` itself (the heuristic) is exported unchanged -- some
    callers may still want it standalone (e.g. tests, or a future non-chat consumer)."""

    def test_long_message_is_a_job_description(self) -> None:
        assert looks_like_job_description(GENERIC_JOB_DESCRIPTION) is True

    def test_short_message_is_not_a_job_description(self) -> None:
        assert looks_like_job_description("hi there") is False


class TestProfileUpdateVsRefineBoundary:
    """CONTEXT.md draws the line as "refine acts on the Resume, profile_update acts on facts
    of the Profile". Every case below is a documented decision, not an assumption -- see the
    inline comment on each for why it landed where it did."""

    # -- The spec's own examples (pt-BR and en), both with and without an active resume:
    # profile_update must win even when a resume is active (that's the entire point -- a user
    # mid-session can still correct a personal fact without it being swallowed by refine).

    def test_pt_changed_phone_number_is_profile_update_regardless_of_active_resume(self) -> None:
        msg = "Mudei meu telefone para 11 91234-5678"
        assert classify_intent(message=msg, has_active_resume=False) == "profile_update"
        assert classify_intent(message=msg, has_active_resume=True) == "profile_update"

    def test_pt_add_certification_is_profile_update(self) -> None:
        msg = "Adiciona a certificação AWS Certified Developer no meu perfil"
        assert classify_intent(message=msg, has_active_resume=True) == "profile_update"

    def test_pt_remove_project_is_profile_update(self) -> None:
        # Deliberately NOT named e.g. "Resume Agent" -- a project whose own name contains the
        # word "resume" would collide with the resume-scope-word gate below (documented there);
        # that is a real, accepted limitation, not something this test should paper over.
        msg = "Remove o projeto Metrics Dashboard"
        assert classify_intent(message=msg, has_active_resume=True) == "profile_update"

    def test_en_changed_phone_number_is_profile_update(self) -> None:
        msg = "I changed my phone number to 555-0100"
        assert classify_intent(message=msg, has_active_resume=False) == "profile_update"
        assert classify_intent(message=msg, has_active_resume=True) == "profile_update"

    def test_en_add_certification_is_profile_update(self) -> None:
        assert (
            classify_intent(message="Add certification: AWS Certified Developer", has_active_resume=True)
            == "profile_update"
        )

    def test_en_remove_project_is_profile_update(self) -> None:
        assert classify_intent(message="Remove project Metrics Dashboard", has_active_resume=True) == "profile_update"

    # -- The spec's refine counter-examples: these name the RESUME/document itself, not a
    # profile fact, and must stay refine when a resume is active.

    def test_a_verbless_summary_request_now_converses(self) -> None:
        # "resumo mais curto" names the document but carries no edit VERB, so it no longer trips
        # the tightened refine (which used to catch it only via the removed catch-all default).
        # It routes to conversation, where the agent recognizes the elliptic edit and asks
        # "quer que eu aplique isso no currículo?" instead of guessing. "deixa o resumo mais
        # curto" (imperative opener) still refines directly.
        assert classify_intent(message="resumo mais curto", has_active_resume=True) == "converse"
        assert classify_intent(message="deixa o resumo mais curto", has_active_resume=True) == "refine"

    def test_translate_request_stays_refine(self) -> None:
        assert classify_intent(message="traduz pra ingles", has_active_resume=True) == "refine"

    # -- Explicit resume/document scoping always wins over an otherwise-matching add/remove +
    # profile-noun pattern -- e.g. "add ... to my resume" is a refine, not a profile_update,
    # even though "add" + "skill" alone would match below.

    def test_add_skill_explicitly_scoped_to_the_resume_stays_refine(self) -> None:
        msg = "Add a skill to my resume"
        assert classify_intent(message=msg, has_active_resume=True) == "refine"

    def test_translate_the_resume_mentions_resume_explicitly_stays_refine(self) -> None:
        assert classify_intent(message="Translate the resume to English.", has_active_resume=True) == "refine"

    # -- Documented boundary decision: a bare add/remove verb with NO recognized profile-fact
    # noun (a technology name alone, a vague "bullet") defaults to refine, not profile_update.
    # Rationale: a false negative here is cheap (the user can just ask again, more explicitly,
    # and it costs nothing -- refine never touches the permanent profile); a false positive
    # would silently mutate a permanent, cross-session fact from an under-specified message.
    # This is the exact "mensagens curtas/ambiguas com resume ativo" risk boundary ticket 05
    # calls out.

    def test_bare_add_with_no_recognized_profile_noun_stays_refine(self) -> None:
        assert classify_intent(message="adiciona React", has_active_resume=True) == "refine"

    def test_bare_remove_with_no_recognized_profile_noun_stays_refine(self) -> None:
        assert classify_intent(message="remove the bullet about Python", has_active_resume=True) == "refine"

    # -- profile_update also fires with NO active resume at all (a user's very first message,
    # before ever generating a resume) -- it must not fall into v1's "question" bucket.

    def test_profile_update_fires_with_no_active_resume(self) -> None:
        msg = "adiciona a certificacao Scrum Master"
        assert classify_intent(message=msg, has_active_resume=False) == "profile_update"

    # -- Collision guard: a genuine job-description paste must never be hijacked into
    # profile_update just because it happens to contain an action-verb-shaped word plus a
    # profile-fact noun somewhere in its prose (e.g. "update", "company").

    def test_job_description_mentioning_update_and_company_is_not_hijacked(self) -> None:
        jd = (
            "We are a fast-growing company looking to update our engineering team with a "
            "Senior Backend Engineer. You will design and build scalable APIs in Python, own "
            "our PostgreSQL data layer, and help mentor junior engineers across the company. "
            "Experience with Docker, Kubernetes, and CI/CD pipelines is a strong plus."
        )
        assert classify_intent(message=jd, has_active_resume=False) == "generate"


class TestProposalTurnRouting:
    """v4 ticket B3 (docs/v4-improvement-proposal.md SS2): ``has_pending_proposal`` defaults to
    False, so every test above (written before this kwarg existed) is unaffected -- proving the
    new routing is additive, not a rewrite of the v1/v2 behavior."""

    def test_pending_proposal_routes_to_proposal_turn_regardless_of_message_shape(self) -> None:
        assert (
            classify_intent(message="Aprova a proposta", has_active_resume=False, has_pending_proposal=True)
            == "proposal_turn"
        )
        assert (
            classify_intent(message="ok", has_active_resume=False, has_pending_proposal=True)
            == "proposal_turn"
        )

    def test_pending_proposal_wins_over_a_pasted_job_description(self) -> None:
        # New JD while a proposal is pending is itself a proposal_turn case (the "new_jd"
        # short-circuit inside _handle_proposal_turn, per spec SS2) -- NOT a fresh `generate`.
        assert (
            classify_intent(
                message=GENERIC_JOB_DESCRIPTION, has_active_resume=False, has_pending_proposal=True
            )
            == "proposal_turn"
        )

    def test_has_pending_proposal_defaults_to_false(self) -> None:
        # No proposal, no resume, not a posting -> the conversation lane (was "question").
        assert classify_intent(message="hi there", has_active_resume=False) == "converse"


class TestProfileUpdateVsProposalTurnBoundary:
    """v4 ticket B4 originally exempted messages naming literal PROPOSAL-scope vocabulary
    (``sugestao``/``proposta``/``melhoria``/``item``/their English counterparts) from
    ``has_pending_proposal`` and routed them to ``profile_update`` instead. QA-03 (P1, QA live)
    found the hole: a natural adjustment phrase that names no trigger word ("adiciona tambem
    FastAPI nas skills ... e reordena os projetos ...") slipped past the guard and silently wrote
    a real ProfileVersion to the permanent Living Profile mid-negotiation, with no user
    confirmation. REVISED (spec SS2, QA-03): ``has_pending_proposal`` now wins unconditionally,
    evaluated BEFORE the profile_update check, with no message-shape exception -- see
    ``classify_intent``'s docstring for the full data-safety rationale (misroute to
    proposal_turn is recoverable; the inverse misroute corrupts profile data)."""

    def test_qa03_exact_repro_phrase_with_pending_proposal_is_proposal_turn(self) -> None:
        # The exact QA-03 repro: no PROPOSAL-scope trigger word anywhere in the message, yet it
        # reads exactly like a profile_update ("adiciona"/"remova" + "skills"/"projetos") --
        # this is the phrase that leaked past the old guard and wrote v19 to the Living Profile.
        assert (
            classify_intent(
                message=(
                    "adiciona também FastAPI nas skills (não remova nenhuma skill existente) "
                    "e reordena os projetos colocando Space Tourism Website em primeiro lugar, "
                    "sem remover nenhum projeto da lista."
                ),
                has_active_resume=False,
                has_pending_proposal=True,
            )
            == "proposal_turn"
        )

    def test_changed_phone_number_with_pending_proposal_is_now_proposal_turn(self) -> None:
        # Trade-off accepted by the spec revision: a genuine profile-fact edit ("mudei meu
        # telefone") that happens to arrive while a proposal is pending is NOT applied to the
        # permanent profile anymore -- it routes conversationally instead, and the user can
        # repeat the edit once the proposal is approved or discarded. This is the intentional
        # cost of closing the QA-03 hole (see classify_intent's docstring: no deterministic
        # heuristic can tell the two apart reliably, so routing must fail non-destructively).
        assert (
            classify_intent(
                message="mudei meu telefone para 11 99999-0000",
                has_active_resume=False,
                has_pending_proposal=True,
            )
            == "proposal_turn"
        )

    def test_changed_phone_number_with_no_pending_proposal_is_still_profile_update(self) -> None:
        # Without a pending proposal the v1/v2 routing is byte-identical to before this ticket --
        # profile_update still wins.
        assert (
            classify_intent(message="mudei meu telefone para 11 99999-0000", has_active_resume=False)
            == "profile_update"
        )

    def test_removing_a_suggestion_about_skills_with_pending_proposal_is_proposal_turn(self) -> None:
        assert (
            classify_intent(
                message="remove a sugestão sobre skills",
                has_active_resume=False,
                has_pending_proposal=True,
            )
            == "proposal_turn"
        )

    def test_adjust_the_proposal_item_2_with_pending_proposal_is_proposal_turn(self) -> None:
        assert (
            classify_intent(
                message="ajusta o item 2 da proposta",
                has_active_resume=False,
                has_pending_proposal=True,
            )
            == "proposal_turn"
        )


_FULL_PT_POSTING = (
    "Vaga para Desenvolvedor Back-end Sênior. Sobre a empresa: somos uma fintech em "
    "crescimento acelerado no setor de meios de pagamento. Responsabilidades: projetar e "
    "manter APIs em Python e FastAPI, cuidar da camada de dados em PostgreSQL, participar do "
    "processo de code review e apoiar a evolução da arquitetura de microsserviços. "
    "Requisitos: sólidos conhecimentos em Python, experiência com bancos relacionais, "
    "familiaridade com Docker e pipelines de CI/CD. Diferenciais: Kubernetes, AWS, "
    "observabilidade. Benefícios: plano de saúde, vale-refeição e horário flexível."
)

_FULL_EN_POSTING = (
    "About the role: we are hiring a Senior Frontend Engineer for our platform team. "
    "Responsibilities: build and maintain our React and Next.js application, own the design "
    "system, and collaborate with backend engineers on GraphQL contracts. Requirements: "
    "strong TypeScript, deep React experience, and a track record shipping accessible "
    "interfaces. Nice to have: Remotion, WebGL, or video tooling experience. What we offer: "
    "remote-first work, equity, and a learning budget."
)

_LONG_REFINE_INSTRUCTION = (
    "Reescreve os bullets da minha experiência mais recente destacando React, Node.js, "
    "PostgreSQL, Docker, AWS, GraphQL e Kubernetes, e deixa o resumo mais curto para caber "
    "em uma página só, mantendo o tom que já está lá."
)


class TestSecondPostingRouting:
    """v6 (Second Posting): a genuinely new posting can now beat an active resume.

    Before v6 the router asked "is there an active resume?" and stopped, so the SECOND job
    description pasted into a session became a refine instruction against the resume built for
    the FIRST one — inheriting its language (how the bug surfaced) and, worse, producing a patch
    of the previous document instead of a resume for the new job, with no Analysis and no
    Improvement Proposal. The tests below pin the three-gate replacement AND the false positives
    it has to keep avoiding, since a misroute the other way discards a refine session.
    """

    def test_a_full_pt_posting_beats_an_active_resume(self) -> None:
        assert classify_intent(message=_FULL_PT_POSTING, has_active_resume=True) == "generate"

    def test_a_full_en_posting_beats_an_active_resume(self) -> None:
        assert classify_intent(message=_FULL_EN_POSTING, has_active_resume=True) == "generate"

    def test_a_long_keyword_dense_refine_instruction_stays_refine(self) -> None:
        # The false positive that makes "just let looks_like_job_description win" unsafe: this
        # clears that heuristic easily (30+ words, many tech keywords) and is plainly an edit.
        assert looks_like_job_description(_LONG_REFINE_INSTRUCTION) is True
        assert classify_intent(message=_LONG_REFINE_INSTRUCTION, has_active_resume=True) == "refine"

    def test_a_jd_shaped_message_with_no_posting_structure_asks_instead_of_guessing(self) -> None:
        # Reads like a job blurb but carries no section headings and no imperative — exactly the
        # case where either guess is a real loss, so the agent asks.
        blurb = (
            "Uma startup de logística está montando um time de dados para trabalhar com "
            "Python, dbt, Airflow e BigQuery em um ambiente de alto volume de eventos."
        )
        assert looks_like_job_description(blurb) is True
        assert classify_intent(message=blurb, has_active_resume=True) == "clarify_scope"

    def test_the_clarify_valve_never_fires_without_an_active_resume(self) -> None:
        # With nothing to lose, generate is the right guess — clarify only exists to protect an
        # existing document.
        blurb = (
            "Uma startup de logística está montando um time de dados para trabalhar com "
            "Python, dbt, Airflow e BigQuery em um ambiente de alto volume de eventos."
        )
        assert classify_intent(message=blurb, has_active_resume=False) == "generate"

    def test_a_short_non_edit_message_with_an_active_resume_now_converses(self) -> None:
        # "ok" carries no edit verb, so it no longer falls to the removed refine default -- it
        # converses. "deixa mais curto" opens with an imperative, so it stays a refine.
        assert classify_intent(message="ok", has_active_resume=True) == "converse"
        assert classify_intent(message="deixa mais curto", has_active_resume=True) == "refine"

    def test_a_pending_proposal_still_wins_over_a_pasted_posting(self) -> None:
        # The v4 rule is unconditional and v6 must not have punched a hole in it: mid-negotiation
        # every message is a proposal turn, posting-shaped or not.
        assert (
            classify_intent(
                message=_FULL_PT_POSTING, has_active_resume=True, has_pending_proposal=True
            )
            == "proposal_turn"
        )

    def test_a_profile_update_still_wins_over_the_new_posting_gate(self) -> None:
        assert (
            classify_intent(message="mudei meu telefone para 11 91234-5678", has_active_resume=True)
            == "profile_update"
        )


class TestPostingStructureDetection:
    def test_a_posting_needs_structure_not_just_vocabulary(self) -> None:
        # Two section markers, or one plus real length — deliberately stricter than
        # looks_like_job_description, which is all that guards the no-active-resume case.
        assert looks_like_new_job_posting(_FULL_PT_POSTING) is True
        assert looks_like_new_job_posting(_FULL_EN_POSTING) is True

    def test_a_short_message_is_never_a_new_posting_however_structured(self) -> None:
        assert looks_like_new_job_posting("Requisitos: Python. Benefícios: vale.") is False

    def test_a_refine_instruction_is_never_a_new_posting(self) -> None:
        assert looks_like_new_job_posting(_LONG_REFINE_INSTRUCTION) is False


class TestRefineInstructionDetection:
    def test_an_imperative_opener_marks_an_instruction(self) -> None:
        assert looks_like_refine_instruction("tira o Google Analytics das skills") is True
        assert looks_like_refine_instruction("Rewrite the summary to be shorter") is True

    def test_a_politeness_preamble_does_not_hide_the_imperative(self) -> None:
        assert looks_like_refine_instruction("por favor, tira o Power BI") is True
        assert looks_like_refine_instruction("can you rewrite the first bullet") is True

    def test_naming_the_document_with_a_change_verb_marks_an_instruction(self) -> None:
        # No imperative opener, but unmistakably about the document in front of the agent.
        assert looks_like_refine_instruction("quero o currículo mais curto, remove um projeto") is True

    def test_a_posting_is_not_an_instruction(self) -> None:
        assert looks_like_refine_instruction(_FULL_PT_POSTING) is False
        assert looks_like_refine_instruction(_FULL_EN_POSTING) is False

    def test_an_accent_stripped_instruction_is_still_recognized(self) -> None:
        # Users type without accents; the detector folds them before matching.
        assert looks_like_refine_instruction("traduz o curriculo para ingles") is True


class TestBaselineResumeRouting:
    """v6 (Baseline Resume): a request for an OPEN resume — one not aimed at any posting.

    The reported case, verbatim: "Preciso de um currículo um pouco mais generalista pra pôr no meu
    indeed." 13 words, zero JD keywords, no imperative — so not a posting, not a refine
    instruction, and the fallback reply could only say "paste a job description". The user was not
    misunderstood: every generation path in the app was anchored to a posting, so the capability
    did not exist.
    """

    _REPORTED = "Preciso de um currículo um pouco mais generalista pra pôr no meu indeed."

    def test_the_reported_message_routes_to_a_baseline_resume(self) -> None:
        assert classify_intent(message=self._REPORTED, has_active_resume=False) == "generate_baseline"

    def test_it_routes_the_same_way_with_a_resume_already_open(self) -> None:
        # Asking for "um currículo generalista" is a request for a NEW document, not an edit of
        # the tailored one sitting there.
        assert classify_intent(message=self._REPORTED, has_active_resume=True) == "generate_baseline"

    def test_an_imperative_about_the_open_document_stays_a_refine(self) -> None:
        # The distinction that makes the gate safe: "deixa o currículo mais generalista" points AT
        # the document on screen, so it is an edit. Only the imperative separates the two.
        assert classify_intent(message="deixa o currículo mais generalista", has_active_resume=True) == "refine"

    def test_naming_a_job_board_is_itself_the_request(self) -> None:
        assert classify_intent(message="me gera um CV pro Indeed", has_active_resume=False) == "generate_baseline"

    def test_saying_there_is_no_posting_qualifies(self) -> None:
        assert (
            classify_intent(message="quero um curriculo base, sem vaga especifica", has_active_resume=False)
            == "generate_baseline"
        )

    def test_a_breadth_word_alone_is_not_enough(self) -> None:
        # A posting that happens to say "perfil generalista" must never become a baseline request:
        # the message has to name the DOCUMENT too.
        posting = (
            "Estamos contratando uma pessoa desenvolvedora com perfil generalista. "
            "Requisitos: Python, PostgreSQL, Docker e experiência com APIs REST. "
            "Responsabilidades: manter serviços em produção e participar de code review. "
            "Benefícios: plano de saúde e horário flexível."
        )
        assert looks_like_baseline_resume_request(posting) is False
        assert classify_intent(message=posting, has_active_resume=True) == "generate"

    def test_naming_the_document_alone_is_not_enough(self) -> None:
        # No breadth word and no job board: an ordinary edit.
        assert looks_like_baseline_resume_request("tira o Google Analytics do currículo") is False

    def test_a_pending_proposal_still_wins(self) -> None:
        assert (
            classify_intent(message=self._REPORTED, has_active_resume=True, has_pending_proposal=True)
            == "proposal_turn"
        )


class TestBaselineBrief:
    def _profile(self, **overrides) -> ResumeDocument:
        base = {
            "fullName": "Lucas Monteiro",
            "headline": "Desenvolvedor Full Stack",
            "summary": "Base summary.",
            "locale": "pt-BR",
        }
        base.update(overrides)
        return ResumeDocument(**base)

    def test_the_brief_states_there_is_no_posting(self) -> None:
        brief = build_baseline_brief(self._profile(), "quero um currículo generalista")
        assert "TARGET BRIEF" in brief
        assert "no specific job posting" in brief

    def test_the_career_target_comes_from_the_profile_headline(self) -> None:
        brief = build_baseline_brief(self._profile(), "quero um currículo generalista")
        assert "Career target: Desenvolvedor Full Stack" in brief

    def test_the_users_own_words_are_carried_verbatim(self) -> None:
        # Not parsed: a heuristic pulling "front-end" out of this would be exactly the kind of
        # quiet wrong guess the routing gates exist to avoid. The model reads the note instead.
        brief = build_baseline_brief(self._profile(), "quero um generalista de front-end")
        assert "quero um generalista de front-end" in brief
        assert "follow THEIR words" in brief

    def test_a_blank_message_leaves_no_empty_note_block(self) -> None:
        # And no dangling "follow their words" rule either: instructing the model to obey
        # something absent from the prompt invites it to invent what that something said.
        brief = build_baseline_brief(self._profile(), "   ")
        assert "own words for this request" not in brief
        assert "follow THEIR words" not in brief

    def test_the_brief_asks_for_breadth_without_asking_for_vagueness(self) -> None:
        brief = build_baseline_brief(self._profile(), "")
        assert "favour BREADTH" in brief
        assert "broad, not" in brief

    def test_the_brief_never_licenses_invention(self) -> None:
        brief = build_baseline_brief(self._profile(), "")
        assert "never invent a fact" in brief

    def test_a_brief_is_distinguishable_from_a_real_posting(self) -> None:
        # Load-bearing, and found by a failing test rather than by review: the brief lives in the
        # same job_description column a real posting does, and it is ENGLISH prompt text -- so any
        # stage that sniffs that column for the output language ships a Portuguese-targeted
        # baseline resume in English. Callers check this to skip detection on a brief.
        brief = build_baseline_brief(self._profile(), "quero um currículo generalista")
        assert is_target_brief(brief) is True
        assert is_target_brief("Estamos contratando uma pessoa desenvolvedora...") is False
        assert is_target_brief("") is False
        assert is_target_brief(None) is False

    def test_a_profile_with_no_headline_has_no_career_target(self) -> None:
        # Broad is not unfocused: with nothing to be broad ABOUT, the caller must ask rather than
        # invent a career direction for the candidate.
        assert has_career_target(self._profile()) is True
        assert has_career_target(self._profile(headline="")) is False
        assert has_career_target(self._profile(headline="   ")) is False


class TestConversationRouting:
    """The read-only conversation lane. It wins whenever a turn is NOT an explicit edit, a
    posting, a baseline request, or a profile fact -- flipping the default from "assume the user
    wants an edit" (the old refine catch-all, which silently edited on a mere question) to
    "assume the user wants to talk". A turn routed here is answered by an LLM that reads the
    resume/profile/active proposal and never mutates anything; a genuinely edit-shaped but
    verb-less turn is where that LLM asks "quer que eu aplique?" -- which is why no deterministic
    gate tries to separate a soft edit suggestion from a plain question (both name the resume
    with no imperative and are indistinguishable without reading them)."""

    def test_a_real_question_about_the_resume_no_longer_edits_it(self) -> None:
        # The flagship bug: this fell to the refine default and produced an unwanted resume diff.
        assert classify_intent(message="por que o resumo está assim?", has_active_resume=True) == "converse"
        assert classify_intent(message="why is the summary written like this?", has_active_resume=True) == "converse"

    def test_an_off_schema_artifact_request_does_not_hijack_the_resume(self) -> None:
        # "give me a qualification summary for another form" is not an edit to THIS resume -- it
        # comes out of the conversation lane as chat text, saved to nothing.
        msg = "me manda um qualification summary pra colar em outro formulário"
        assert classify_intent(message=msg, has_active_resume=True) == "converse"
        assert classify_intent(message="write me a short cover letter for this role", has_active_resume=True) == "converse"

    def test_a_conversational_turn_needs_no_active_resume(self) -> None:
        assert classify_intent(message="o que você acha do meu perfil?", has_active_resume=False) == "converse"

    def test_a_clear_edit_verb_still_refines(self) -> None:
        # The verbs the tightened refine must keep catching, including two added for this lane
        # ("aplica"/"atualiza") that previously had no opener entry.
        assert classify_intent(message="aplica isso no currículo", has_active_resume=True) == "refine"
        assert classify_intent(message="atualiza o resumo com meu cargo novo", has_active_resume=True) == "refine"
        assert classify_intent(message="troca o título por Engenheiro de Software", has_active_resume=True) == "refine"

    def test_a_pending_proposal_still_wins_over_a_conversational_turn(self) -> None:
        # The v4 unconditional rule is untouched: mid-negotiation even a plain question is a
        # proposal turn (the LLM there answers it without leaving the negotiation).
        assert (
            classify_intent(
                message="por que o resumo está assim?", has_active_resume=True, has_pending_proposal=True
            )
            == "proposal_turn"
        )
