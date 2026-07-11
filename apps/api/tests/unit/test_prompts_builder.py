"""Unit tests for app/domain/prompts_builder.py (v4 ticket B2).

``TestBuildGenerationUserMsgCharacterization`` pins ``build_generation_user_msg``'s CURRENT
output byte-for-byte, run BEFORE the ``agreed_improvements`` parameter existed -- proving the
v4 addition is purely additive (omitting the new parameter must never change a single byte of
what generation_service.py has been sending the LLM since v1). The rest of this module tests
the v4 additions: the parameter's APPROVED IMPROVEMENT PLAN block, and the two new Analysis /
Proposal Turn user-message builders.
"""

from __future__ import annotations

from app.domain.prompts_builder import (
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
    # Reproduces prompts_builder.py's pre-v4 template verbatim (see module docstring above) --
    # this is the golden/characterization snapshot, not a re-import of the implementation.
    return f"""Job description:
---
{job_description.strip()}
---

Tailor a resume for the candidate described in the CANDIDATE PROFILE below. Hard rules:
- Use ONLY facts present in the profile (and supporting sources). Do NOT invent employers, job titles, dates, schools, certifications, projects, or metrics.
- Keep the candidate's name and contact details EXACTLY as in the profile.
- Keep the same set of experience entries, education, and projects; you may rewrite their wording (bullets/descriptions) and reorder/select skills from the profile.
- If the profile lacks something the job wants, omit it — never fabricate it.

CANDIDATE PROFILE (authoritative JSON — the single source of truth):
{profile.model_dump_json(indent=2)}{sources_block}

Target locale for labels and prose: {locale}
Return the tailored resume as JSON only, using the same schema as the profile."""


class TestBuildGenerationUserMsgCharacterization:
    def test_without_sources_or_agreed_improvements_matches_pre_v4_output(self) -> None:
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

    def test_with_sources_and_no_agreed_improvements_matches_pre_v4_output(self) -> None:
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
