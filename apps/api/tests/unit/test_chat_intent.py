"""Unit tests for app/domain/chat_intent.py (v2 ticket 05 -- "Chat: intencao profile_update").

``TestV1PinnedRouting`` characterizes the v1 3-way routing (generate/refine/question) exactly
as it lived inline in ``chat_service.handle_chat_turn`` before this module existed (see that
function's pre-v2 module docstring) -- these pass against the freshly-extracted
``classify_intent`` with NO behavior change, proving the extraction is a pure move, not a
rewrite. ``TestProfileUpdateVsRefineBoundary`` documents the 4th intent added on top in the
same module.
"""

from __future__ import annotations

from app.domain.chat_intent import classify_intent, looks_like_job_description

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


class TestV1PinnedRouting:
    """Pins chat_service.py's pre-extraction inline logic (lines ~125-130): a long/keyword-dense
    job description with no active resume routes to generate; ANY message at all routes to
    refine once a resume is active (there is no session-level way back to question/generate
    without clearing the active resume first -- this is the riskiest, most surprising v1
    behavior per ticket 02/04's own architecture notes); anything else is a plain reply."""

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

    def test_greeting_with_no_active_resume_is_question(self) -> None:
        assert classify_intent(message="hi there", has_active_resume=False) == "question"

    def test_short_ambiguous_instruction_with_no_active_resume_is_question(self) -> None:
        # Doesn't look like a JD (too short, no tech-keyword density) and there is nothing
        # active to refine -- v1's fallback bucket.
        assert classify_intent(message="Make the summary punchier.", has_active_resume=False) == "question"

    def test_any_message_with_an_active_resume_is_refine(self) -> None:
        assert classify_intent(message="Make the summary punchier.", has_active_resume=True) == "refine"

    def test_a_job_description_pasted_with_an_active_resume_is_still_refine(self) -> None:
        # The riskiest line in the original code (chat_service.py:127, per ticket 02/04 notes):
        # `elif active_resume_row is not None` catches this BEFORE any JD check runs -- an
        # active resume always wins, even over text that reads exactly like a job posting.
        assert classify_intent(message=GENERIC_JOB_DESCRIPTION, has_active_resume=True) == "refine"

    def test_translate_instruction_with_active_resume_is_refine(self) -> None:
        assert classify_intent(message="Translate the resume to English.", has_active_resume=True) == "refine"

    def test_short_nonsense_with_active_resume_is_refine(self) -> None:
        # The v1 risk boundary called out in ticket 05: a short, ambiguous message with an
        # active resume has no bucket other than refine -- pinned explicitly.
        assert classify_intent(message="ok", has_active_resume=True) == "refine"
        assert classify_intent(message="hmm sure", has_active_resume=True) == "refine"


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

    def test_shorter_summary_request_stays_refine(self) -> None:
        assert classify_intent(message="resumo mais curto", has_active_resume=True) == "refine"

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
        assert classify_intent(message="hi there", has_active_resume=False) == "question"


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
