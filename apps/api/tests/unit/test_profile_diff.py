"""Unit tests for app/domain/profile_diff.py (v2 ticket 04 -- "Merge incremental").

The Deterministic Diff: pure, no I/O, no LLM. Every case here classifies a ResumeDocument
(freshly "extracted") against a ProfileMaster (the active profile) into new/divergent/equal,
and exercises the Adjudication containment gate (``is_op_in_diff_scope`` /
``filter_ops_to_diff_scope``) that keeps the LLM step from touching anything the diff didn't
flag (CONTEXT.md: Deterministic Diff, Adjudication).
"""

from __future__ import annotations

from app.domain.profile_diff import deterministic_diff, filter_ops_to_diff_scope
from app.domain.profile_patch import PatchOp
from app.domain.schemas import ProfileMaster, ResumeDocument


def _profile(**overrides) -> ProfileMaster:
    base = dict(
        fullName="Lucas Monteiro",
        headline="Full Stack Developer",
        summary="Base summary.",
        location="São Paulo, BR",
        email="lucas@example.com",
        phone="+55 11 90000-0000",
        locale="pt-BR",
        skills=["React", "TypeScript"],
        experience=[
            {
                "company": "SmartHow",
                "title": "Front-End Developer",
                "location": "São Paulo",
                "start": "2025-01",
                "end": None,
                "highlights": ["Shipped the v1 chat experience"],
            }
        ],
        education=[{"institution": "USP", "degree": "Bacharelado", "end": "2022", "details": None}],
        projects=[{"name": "Resume Agent", "description": "This very app."}],
        links=[{"label": "GitHub", "url": "https://github.com/lucas"}],
    )
    base.update(overrides)
    return ProfileMaster.model_validate(base)


def _doc(**overrides) -> ResumeDocument:
    base = dict(
        fullName="Lucas Monteiro",
        headline="Full Stack Developer",
        summary="Base summary.",
        location="São Paulo, BR",
        email="lucas@example.com",
        phone="+55 11 90000-0000",
        locale="pt-BR",
        skills=["React", "TypeScript"],
        experience=[
            {
                "company": "SmartHow",
                "title": "Front-End Developer",
                "location": "São Paulo",
                "start": "2025-01",
                "end": None,
                "highlights": ["Shipped the v1 chat experience"],
            }
        ],
        education=[{"institution": "USP", "degree": "Bacharelado", "end": "2022", "details": None}],
        projects=[{"name": "Resume Agent", "description": "This very app."}],
        links=[{"label": "GitHub", "url": "https://github.com/lucas"}],
    )
    base.update(overrides)
    return ResumeDocument.model_validate(base)


class TestEmptyDiff:
    def test_identical_document_produces_no_diff(self) -> None:
        profile = _profile()
        diff = deterministic_diff(profile, _doc())
        assert diff.is_empty
        assert diff.summary() == []

    def test_accent_and_case_variants_are_still_equal(self) -> None:
        profile = _profile()
        extracted = _doc(
            experience=[
                {
                    "company": "smarthow",
                    "title": "Front-End Developer",
                    "location": "Sao Paulo",
                    "start": "2025-01",
                    "end": None,
                    "highlights": ["Shipped the v1 chat experience"],
                }
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert diff.is_empty


class TestScalarDivergence:
    def test_changed_summary_is_divergent(self) -> None:
        profile = _profile()
        extracted = _doc(summary="A rewritten, more complete summary.")
        diff = deterministic_diff(profile, extracted)
        assert len(diff.divergent_scalars) == 1
        assert diff.divergent_scalars[0].field == "summary"
        assert diff.divergent_scalars[0].extracted == "A rewritten, more complete summary."

    def test_blank_extracted_scalar_is_not_divergent(self) -> None:
        profile = _profile()
        extracted = _doc(phone=None)
        diff = deterministic_diff(profile, extracted)
        assert diff.is_empty


class TestSkillsDiff:
    def test_new_skill_is_flagged(self) -> None:
        profile = _profile(skills=["React"])
        extracted = _doc(skills=["React", "GraphQL"])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_skills == ["GraphQL"]

    def test_cpp_and_c_are_distinct_skills(self) -> None:
        profile = _profile(skills=["C"])
        extracted = _doc(skills=["C", "C++"])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_skills == ["C++"]

    def test_case_insensitive_skill_is_not_new(self) -> None:
        profile = _profile(skills=["React"])
        extracted = _doc(skills=["react"])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_skills == []


class TestExperienceDiff:
    def test_new_experience_entry(self) -> None:
        profile = _profile()
        new_role = {
            "company": "Acme",
            "title": "Engineer",
            "location": None,
            "start": "2020-01",
            "end": "2024-12",
            "highlights": ["Did things"],
        }
        extracted = _doc(experience=[*profile.model_dump()["experience"], new_role])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_experience == [new_role]
        assert diff.divergent_experience == []

    def test_divergent_when_highlights_differ(self) -> None:
        profile = _profile()
        extracted = _doc(
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "location": "São Paulo",
                    "start": "2025-01",
                    "end": None,
                    "highlights": ["Shipped the v1 chat experience", "Led a migration"],
                }
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert len(diff.divergent_experience) == 1
        assert diff.divergent_experience[0].base_index == 0
        assert diff.new_experience == []

    def test_partial_date_completion_is_divergent(self) -> None:
        profile = _profile(
            experience=[
                {"company": "Acme", "title": "Engineer", "start": "2020", "end": None, "highlights": []}
            ]
        )
        extracted = _doc(
            experience=[
                {"company": "Acme", "title": "Engineer", "start": "2020-03", "end": None, "highlights": []}
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert len(diff.divergent_experience) == 1


class TestEducationDiff:
    def test_new_degree_at_same_institution_is_new_not_divergent(self) -> None:
        profile = _profile()  # USP / Bacharelado
        extracted = _doc(
            education=[
                {"institution": "USP", "degree": "Bacharelado", "end": "2022", "details": None},
                {"institution": "USP", "degree": "Mestrado", "end": "2024", "details": None},
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert len(diff.new_education) == 1
        assert diff.new_education[0]["degree"] == "Mestrado"
        assert diff.divergent_education == []

    def test_reworded_degree_at_same_institution_is_divergent(self) -> None:
        profile = _profile()  # USP / Bacharelado
        extracted = _doc(
            education=[
                {
                    "institution": "USP",
                    "degree": "Bacharelado em Ciencia da Computacao",
                    "end": "2022",
                    "details": None,
                }
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert diff.new_education == []
        assert len(diff.divergent_education) == 1
        assert diff.divergent_education[0].base_index == 0


class TestProjectsDiff:
    def test_new_project(self) -> None:
        profile = _profile()
        new_project = {"name": "Side Quest", "description": "A weekend project."}
        extracted = _doc(projects=[*profile.model_dump()["projects"], new_project])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_projects == [new_project]

    def test_divergent_project_description(self) -> None:
        profile = _profile()
        extracted = _doc(projects=[{"name": "resume agent", "description": "A rewritten description."}])
        diff = deterministic_diff(profile, extracted)
        assert len(diff.divergent_projects) == 1
        assert diff.divergent_projects[0].base_index == 0


class TestLinksDiff:
    def test_new_link(self) -> None:
        profile = _profile()
        new_link = {"label": "LinkedIn", "url": "https://linkedin.com/in/lucas"}
        extracted = _doc(links=[*profile.model_dump()["links"], new_link])
        diff = deterministic_diff(profile, extracted)
        assert diff.new_links == [new_link]

    def test_normalized_url_is_not_a_new_link(self) -> None:
        profile = _profile()  # https://github.com/lucas
        extracted = _doc(links=[{"label": "GitHub", "url": "https://www.github.com/lucas/"}])
        diff = deterministic_diff(profile, extracted)
        assert diff.is_empty

    def test_divergent_link_label(self) -> None:
        profile = _profile()
        extracted = _doc(links=[{"label": "My GitHub Profile", "url": "https://github.com/lucas"}])
        diff = deterministic_diff(profile, extracted)
        assert len(diff.divergent_links) == 1
        assert diff.divergent_links[0].base_index == 0


class TestBootstrapAgainstBlankProfile:
    def test_everything_is_new_when_profile_is_blank(self) -> None:
        blank = ProfileMaster(fullName="", headline="", summary="", locale="pt-BR")
        extracted = _doc()
        diff = deterministic_diff(blank, extracted)
        assert not diff.is_empty
        assert len(diff.new_experience) == 1
        assert len(diff.new_education) == 1
        assert len(diff.new_projects) == 1
        assert len(diff.new_links) == 1
        assert set(diff.new_skills) == {"React", "TypeScript"}
        assert any(s.field == "fullName" for s in diff.divergent_scalars)


class TestDiffSummary:
    def test_summary_mentions_new_and_updated_items(self) -> None:
        profile = _profile()
        extracted = _doc(
            summary="A rewritten summary.",
            skills=["React", "TypeScript", "Rust"],
        )
        diff = deterministic_diff(profile, extracted)
        summary = diff.summary()
        assert any("summary" in line.lower() for line in summary)
        assert any("rust" in line.lower() for line in summary)


class TestAdjudicationContainment:
    """CONTEXT.md: Adjudication -- "the LLM never touches what the Deterministic Diff didn't
    flag". These pin the containment gate directly against a hand-built diff + hand-built ops,
    independent of any LLM."""

    def test_replace_on_an_index_the_diff_never_flagged_is_dropped(self) -> None:
        profile = _profile(
            experience=[
                {"company": "SmartHow", "title": "Dev", "start": "2025-01", "end": None, "highlights": []},
                {"company": "Other Co", "title": "Dev", "start": "2020-01", "end": None, "highlights": []},
            ]
        )
        extracted = _doc(
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Senior Dev",  # divergent, base_index 0
                    "start": "2025-01",
                    "end": None,
                    "highlights": [],
                },
                {"company": "Other Co", "title": "Dev", "start": "2020-01", "end": None, "highlights": []},
            ]
        )
        diff = deterministic_diff(profile, extracted)
        assert diff.divergent_experience[0].base_index == 0

        legit_op = PatchOp(
            op="replace",
            path="/experience/0/title",
            value="Senior Dev",
            reason="diff-flagged",
            confidence=0.9,
            sourceExcerpt="Senior Dev",
        )
        hallucinated_op = PatchOp(
            op="replace",
            path="/experience/1/title",  # index 1 was never flagged divergent
            value="Hallucinated Title",
            reason="not in diff",
            confidence=0.9,
            sourceExcerpt="n/a",
        )
        kept = filter_ops_to_diff_scope(diff, [legit_op, hallucinated_op])
        assert kept == [legit_op]

    def test_add_on_a_category_with_no_new_items_is_dropped(self) -> None:
        profile = _profile()
        extracted = _doc()  # identical -- no new projects
        diff = deterministic_diff(profile, extracted)

        op = PatchOp(
            op="add",
            path="/projects/-",
            value={"name": "Fabricated", "description": "never in the diff"},
            reason="hallucinated",
            confidence=0.5,
            sourceExcerpt="n/a",
        )
        assert filter_ops_to_diff_scope(diff, [op]) == []

    def test_replace_on_a_scalar_the_diff_never_flagged_is_dropped(self) -> None:
        profile = _profile()
        extracted = _doc(summary="A rewritten summary.")
        diff = deterministic_diff(profile, extracted)

        legit = PatchOp(
            op="replace", path="/summary", value="A rewritten summary.",
            reason="diff-flagged", confidence=0.9, sourceExcerpt="x",
        )
        hallucinated = PatchOp(
            op="replace", path="/phone", value="+1 555 0000",
            reason="not flagged", confidence=0.9, sourceExcerpt="x",
        )
        kept = filter_ops_to_diff_scope(diff, [legit, hallucinated])
        assert kept == [legit]

    def test_add_for_a_genuinely_new_item_is_kept(self) -> None:
        profile = _profile()
        new_project = {"name": "Side Quest", "description": "A weekend project."}
        extracted = _doc(projects=[*profile.model_dump()["projects"], new_project])
        diff = deterministic_diff(profile, extracted)

        op = PatchOp(
            op="add", path="/projects/-", value=new_project,
            reason="new project found", confidence=0.9, sourceExcerpt="Side Quest",
        )
        assert filter_ops_to_diff_scope(diff, [op]) == [op]
