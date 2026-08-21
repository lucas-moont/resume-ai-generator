"""Unit tests for app/domain/prompts_builder.py (v4 ticket B2; v6 Relevance Filter).

``TestBuildGenerationUserMsgCharacterization`` pins ``build_generation_user_msg``'s output
byte-for-byte. It was originally written BEFORE the ``agreed_improvements`` parameter existed,
to prove that v4 addition was purely additive -- and it still guards that property (the
plan-free prompt must be identical with the parameter omitted or ``None``).

The golden string was updated ONCE, deliberately, by v6: the hard rule that used to read "Keep
the same set of experience entries, education, and projects" was the instruction telling the LLM
never to leave profile noise out, so the Relevance Filter could not exist while it stood. The
old text is quoted in ``test_hard_rules_no_longer_forbid_leaving_irrelevant_content_out`` so the
change stays visible as a change rather than a quietly re-baselined snapshot.

The rest of this module tests the v4/v6 additions: the APPROVED IMPROVEMENT PLAN block (now
including the DROP/COMPRESS ops), and the Analysis / Proposal Turn user-message builders.
"""

from __future__ import annotations

from app.domain.prompts_builder import (
    build_analysis_user_msg,
    build_generation_user_msg,
    build_proposal_analysis_user_msg,
    build_proposal_turn_user_msg,
)
from app.domain.schemas import ProposalItem, ResumeDocument

_PROFILE = ResumeDocument(
    fullName="Ana Souza",
    headline="Backend Developer",
    summary="Backend developer with 5 years of experience.",
    locale="pt-BR",
)


def _expected_without_plan(*, job_description: str, profile: ResumeDocument, sources_block: str, locale: str) -> str:
    # Reproduces prompts_builder.py's plan-free template verbatim (see module docstring) --
    # this is the golden/characterization snapshot, not a re-import of the implementation.
    return f"""Job description:
---
{job_description.strip()}
---

Tailor a resume for the candidate described in the CANDIDATE PROFILE below. Hard rules:
- Use ONLY facts present in the profile (and supporting sources). Do NOT invent employers, job titles, dates, schools, certifications, projects, or metrics.
- Keep the candidate's name and contact details EXACTLY as in the profile.
- Keep every employer, role, dates and school from the profile — never open a gap in the timeline. You may rewrite their wording (bullets/descriptions) freely.
- Relevance beats completeness. Give each role space proportional to how much it serves THIS job: a directly relevant role gets its full 3-5 bullets, a role with little bearing on the job gets one factual bullet (never zero). Same for skills and projects — select the ones this job actually calls for and leave the rest out, rather than listing everything the profile happens to contain. A focused resume of 9 skills beats a padded one of 16.
- If the profile lacks something the job wants, omit it — never fabricate it.

CANDIDATE PROFILE (authoritative JSON — the single source of truth):
{profile.model_dump_json(indent=2)}{sources_block}

Target locale for labels and prose: {locale}
Return the tailored resume as JSON only, using the same schema as the profile."""


class TestBuildGenerationUserMsgCharacterization:
    def test_without_sources_or_agreed_improvements_matches_the_golden_prompt(self) -> None:
        actual = build_generation_user_msg(
            job_description="  We need a backend engineer.  ",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
        )
        expected = _expected_without_plan(
            job_description="  We need a backend engineer.  ",
            profile=_PROFILE,
            sources_block="",
            locale="pt-BR",
        )
        assert actual == expected

    def test_with_sources_and_no_agreed_improvements_matches_the_golden_prompt(self) -> None:
        actual = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="PDF excerpt: some text",
            project_notes="Built a widget.",
            locale="en",
        )
        sources_block = (
            "\n\nSupporting sources (use ONLY to choose wording and which real facts to emphasize; "
            "never introduce employers, roles, projects, or numbers that are not in the profile):\n"
            "PDF excerpt: some text\n\nProject notes:\nBuilt a widget."
        )
        expected = _expected_without_plan(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            sources_block=sources_block,
            locale="en",
        )
        assert actual == expected


_ITEMS = [
    ProposalItem(
        id=1,
        section="headline",
        current="Dev Backend",
        proposed="Backend Engineer especializado em Python",
        rationale="A vaga pede especialização em Python e APIs escaláveis.",
    ),
    ProposalItem(
        id=2,
        section="summary",
        current=None,
        proposed="Backend engineer focado em sistemas distribuídos.",
        rationale="A vaga menciona sistemas distribuídos como requisito central.",
    ),
]


class TestBuildGenerationUserMsgWithAgreedImprovements:
    def test_omitting_the_parameter_keeps_byte_identical_output(self) -> None:
        with_default = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
        )
        with_explicit_none = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=None,
        )
        assert with_default == with_explicit_none

    def test_agreed_improvements_inserts_approved_plan_block_before_hard_rules(self) -> None:
        out = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=_ITEMS,
        )
        plan_marker = (
            "APPROVED IMPROVEMENT PLAN (agreed with the user in chat — implement EXACTLY these "
            "changes, nothing beyond them):"
        )
        assert plan_marker in out
        assert out.index(plan_marker) < out.index("Tailor a resume for the candidate")
        assert '1. [headline] current: "Dev Backend" -> proposed: "Backend Engineer especializado em Python" (rationale: A vaga pede especialização em Python e APIs escaláveis.)' in out
        assert '2. [summary] current: null -> proposed: "Backend engineer focado em sistemas distribuídos." (rationale: A vaga menciona sistemas distribuídos como requisito central.)' in out

    def test_agreed_improvements_declares_precedence_over_default_conventions(self) -> None:
        # QA-02: the plan must explicitly outrank the hard rules' default conventions on skill
        # selection/order and experience/project order -- the LLM was resolving that conflict in
        # favor of the conservative hard rules, silently dropping approved skill additions and
        # project reorderings. Only the truthfulness rule (never invent facts) should still win.
        out = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=_ITEMS,
        )
        plan_marker = (
            "APPROVED IMPROVEMENT PLAN (agreed with the user in chat — implement EXACTLY these "
            "changes, nothing beyond them):"
        )
        precedence_marker = "This plan takes precedence over the default conventions below"
        assert precedence_marker in out
        assert "truthfulness" in out.lower()
        assert out.index(plan_marker) < out.index(precedence_marker) < out.index(
            "Tailor a resume for the candidate"
        )

    def test_agreed_improvements_includes_final_checklist_instruction(self) -> None:
        out = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=_ITEMS,
        )
        checklist_marker = "verify EVERY numbered item above is reflected in the output"
        assert checklist_marker in out
        assert out.index(checklist_marker) < out.index("Tailor a resume for the candidate")

    def test_empty_agreed_improvements_list_behaves_like_none(self) -> None:
        with_empty = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=[],
        )
        with_none = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=None,
        )
        assert with_empty == with_none


class TestBuildProposalAnalysisUserMsg:
    def test_includes_profile_json_job_description_and_locale(self) -> None:
        out = build_proposal_analysis_user_msg(
            profile=_PROFILE,
            job_description="  We need a backend engineer.  ",
            locale="pt-BR",
        )
        assert "We need a backend engineer." in out
        assert _PROFILE.model_dump_json(indent=2) in out
        assert "pt-BR" in out

    def test_does_not_mention_projects_or_github_context(self) -> None:
        # Spec 4.1: the Analysis builder is deliberately lean -- no project/GitHub context block,
        # unlike build_generation_user_msg's sources_block.
        out = build_proposal_analysis_user_msg(
            profile=_PROFILE,
            job_description="We need a backend engineer.",
            locale="pt-BR",
        )
        assert "Project notes" not in out
        assert "github" not in out.lower()


class TestBuildProposalTurnUserMsg:
    def test_includes_items_revision_history_message_and_locale(self) -> None:
        out = build_proposal_turn_user_msg(
            items=_ITEMS,
            revision=2,
            history_text="Conversation so far:\nUser: oi\nAssistant: ola",
            message="pode ajustar o headline?",
            locale="pt-BR",
        )
        assert "Backend Engineer especializado em Python" in out
        assert '"section": "headline"' in out
        assert "revision 2" in out
        assert "Conversation so far:\nUser: oi\nAssistant: ola" in out
        assert "pode ajustar o headline?" in out
        assert "pt-BR" in out

    def test_empty_history_omits_history_block_cleanly(self) -> None:
        out = build_proposal_turn_user_msg(
            items=_ITEMS,
            revision=1,
            history_text="",
            message="aprova",
            locale="en",
        )
        assert "aprova" in out
        assert "\n\n\n" not in out


class TestBuildAnalysisUserMsg:
    def test_conversational_mode_includes_message_and_locale_no_pdf_block(self) -> None:
        out = build_analysis_user_msg(
            message="melhora meu headline, atual é 'Dev', minha área é dados",
            locale="pt-BR",
        )
        assert "melhora meu headline" in out
        assert "pt-BR" in out
        assert "LinkedIn profile (extracted" not in out  # no PDF block in conversational mode

    def test_pdf_mode_appends_extracted_block_framed_as_critique_not_ingest(self) -> None:
        out = build_analysis_user_msg(
            message="analisa meu perfil",
            locale="en",
            linkedin_pdf_block="John Doe\nSenior PM\n...",
        )
        assert "analisa meu perfil" in out
        assert "John Doe" in out
        assert "NOT profile truth to ingest" in out

    def test_blank_pdf_block_is_omitted_cleanly(self) -> None:
        out = build_analysis_user_msg(message="oi", locale="en", linkedin_pdf_block="   ")
        assert "LinkedIn profile (extracted" not in out


_SUBTRACTION_ITEMS = [
    ProposalItem(
        id=1,
        section="skills",
        op="drop",
        current="Google Analytics, Power BI",
        proposed="Remover as ferramentas de analytics da lista de skills.",
        targets=["Google Analytics", "Power BI"],
        rationale="A vaga não menciona analytics ou BI em nenhum requisito.",
    ),
    ProposalItem(
        id=2,
        section="experience",
        op="compress",
        current="Agência XYZ",
        proposed="Reduzir a experiência na Agência XYZ a um bullet.",
        targets=["Agência XYZ"],
        rationale="A vaga é de backend; o trabalho lá foi de marketing digital.",
    ),
    ProposalItem(
        id=3,
        section="skills",
        op="add",
        proposed="FastAPI",
        rationale="A vaga pede FastAPI explicitamente.",
    ),
]


class TestApprovedPlanRendersSubtractionOps:
    """v6 (Relevance Filter): a DROP has to *look* like a removal in the plan block.

    Rendered as ``current: X -> proposed: Y`` (the pre-v6 shape for every item) a removal reads
    as a text swap, and the model resolves it against the conservative hard rules instead of
    obeying it — the same failure mode QA-02 documented for added skills. These tests pin the
    imperative shape and the presence of the ops gloss that explains what each one licenses.
    """

    def _plan(self) -> str:
        return build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=_SUBTRACTION_ITEMS,
        )

    def test_a_drop_item_renders_as_an_imperative_removal_with_its_targets(self) -> None:
        out = self._plan()
        assert (
            '1. [skills] DROP (remove from the resume entirely): "Google Analytics", "Power BI"'
            in out
        )
        # Never as a text swap, which is what the LLM was under-obeying.
        assert "1. [skills] current:" not in out

    def test_a_compress_item_states_that_the_entry_stays(self) -> None:
        out = self._plan()
        assert (
            '2. [experience] COMPRESS (keep the entry, reduce it to one factual bullet): '
            '"Agência XYZ"' in out
        )

    def test_an_add_item_renders_as_an_addition(self) -> None:
        out = self._plan()
        assert '3. [skills] ADD: "FastAPI"' in out

    def test_the_block_explains_what_drop_and_compress_license(self) -> None:
        out = self._plan()
        assert "A DROP item is an instruction to OMIT the listed entries from the output" in out
        assert "A COMPRESS item keeps the" in out

    def test_a_rewrite_item_still_renders_in_the_pre_v6_shape(self) -> None:
        # The default op must be byte-compatible with what the block emitted before v6, so a
        # proposal persisted back then reaches the LLM unchanged.
        out = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=_ITEMS,
        )
        assert (
            '1. [headline] current: "Dev Backend" -> proposed: '
            '"Backend Engineer especializado em Python"' in out
        )
        assert "2. [summary] current: null -> proposed:" in out

    def test_a_drop_with_no_targets_falls_back_to_its_prose(self) -> None:
        # Tolerance, not endorsement: the prompt requires targets, but a model that omits them
        # must still produce a legible line rather than "DROP: " with nothing after it. The
        # anchor separately removes nothing in that case — targets are its only input.
        out = build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
            agreed_improvements=[
                ProposalItem(
                    id=1,
                    section="skills",
                    op="drop",
                    proposed="Remover as skills de analytics.",
                    rationale="A vaga não menciona analytics.",
                )
            ],
        )
        assert (
            '1. [skills] DROP (remove from the resume entirely): "Remover as skills de analytics."'
            in out
        )


class TestGenerationHardRulesLicenseSubtraction:
    """The hard rules are where v6's behavior change actually lives: the pre-v6 rule "Keep the
    same set of experience entries, education, and projects" was a standing instruction never to
    leave profile noise out, so no amount of prompt craft downstream could produce a focused
    resume while it stood. These tests pin the replacement — and pin that the timeline guarantee
    it also carried was not lost along with it."""

    def _prompt(self) -> str:
        return build_generation_user_msg(
            job_description="We need a backend engineer.",
            profile=_PROFILE,
            pdf_block="",
            project_notes="",
            locale="pt-BR",
        )

    def test_the_rule_forbidding_omission_is_gone(self) -> None:
        assert "Keep the same set of experience entries" not in self._prompt()

    def test_relevance_is_stated_to_beat_completeness(self) -> None:
        out = self._prompt()
        assert "Relevance beats completeness" in out
        assert "leave the rest out" in out

    def test_the_timeline_guarantee_survives_the_rewrite(self) -> None:
        out = self._prompt()
        assert "never open a gap in the timeline" in out
        assert "one factual bullet (never zero)" in out
