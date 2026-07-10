"""Unit tests for app/domain/entity_identity.py (v2 ticket 02).

Pure-domain identity/matching primitives shared by the anchor (anti-fabrication tailoring in
app/services/llm/resume_json_parser.py) and the future Deterministic Diff (ticket 03/04). No
I/O anywhere in this module -- every case here is a direct call into it.
"""

from __future__ import annotations

from app.domain.entity_identity import (
    build_skill_lookup,
    entity_key,
    match_education_entries,
    match_experience_entries,
    match_projects_by_name,
    skill_token,
    title_similarity,
)


class TestEntityKey:
    def test_case_insensitive(self) -> None:
        assert entity_key("SmartHow") == entity_key("smarthow") == entity_key("SMARTHOW")

    def test_spacing_insensitive(self) -> None:
        assert entity_key("Tech Corp") == entity_key("TechCorp") == entity_key("  Tech   Corp  ")

    def test_accent_insensitive(self) -> None:
        assert entity_key("São Paulo") == entity_key("Sao Paulo") == entity_key("SÃO PAULO")

    def test_punctuation_stripped_unlike_skill_token(self) -> None:
        # entity_key is for entity NAMES (company/institution/project), not skills -- it
        # collapses "C++" and "C" to the same key. skill_token below must not.
        assert entity_key("C++") == entity_key("C")

    def test_none_and_non_string_inputs(self) -> None:
        assert entity_key(None) == ""
        assert entity_key(123) == "123"
        assert entity_key("") == ""


class TestSkillToken:
    def test_preserves_meaningful_punctuation(self) -> None:
        assert skill_token("C++") != skill_token("C")
        assert skill_token("Node.js") == "node.js"

    def test_case_insensitive(self) -> None:
        assert skill_token("React") == skill_token("react") == skill_token("REACT")

    def test_distinguished_from_entity_key_by_design(self) -> None:
        # The ticket's decision: the two normalizers are NOT unified.
        assert skill_token("C++") != entity_key("C++")


class TestTitleSimilarity:
    def test_identical_after_normalization_scores_one(self) -> None:
        assert title_similarity("Full Stack Developer", "full stack developer") == 1.0
        assert title_similarity("Front-End Developer", "Front End Developer") == 1.0

    def test_close_but_not_identical_scores_high(self) -> None:
        score = title_similarity("Full Stack Developer", "Fullstack Developer")
        assert 0.85 < score < 1.0

    def test_dissimilar_titles_score_low(self) -> None:
        assert title_similarity("Full Stack Developer", "Marketing Intern") < 0.5

    def test_blank_or_none_is_zero(self) -> None:
        assert title_similarity("", "Anything") == 0.0
        assert title_similarity(None, "Anything") == 0.0
        assert title_similarity("Anything", None) == 0.0


class TestMatchExperienceEntries:
    def test_matches_by_company_and_start_case_accent_insensitive(self) -> None:
        base = [{"company": "SmartHow", "title": "Dev", "start": "2025"}]
        candidates = [
            {"company": "smarthow", "title": "Desenvolvedor", "start": "2025", "highlights": ["x"]}
        ]
        assert match_experience_entries(base, candidates) == [candidates[0]]

    def test_same_company_two_roles_each_claim_the_matching_start(self) -> None:
        # Regression coverage for the bug the original anchor code fixed: two roles at the
        # same company must not collapse onto the same candidate.
        base = [
            {"company": "Savvi", "start": "2021-06"},
            {"company": "Savvi", "start": "2021-01"},
        ]
        candidates = [
            {"company": "Savvi", "start": "2021-01", "highlights": ["intern"]},
            {"company": "Savvi", "start": "2021-06", "highlights": ["senior"]},
        ]
        result = match_experience_entries(base, candidates)
        assert result[0]["highlights"] == ["senior"]
        assert result[1]["highlights"] == ["intern"]

    def test_company_only_fallback_when_start_format_differs(self) -> None:
        base = [{"company": "Acme", "start": "2020-01"}]
        candidates = [{"company": "Acme", "start": "2020-jan", "highlights": ["x"]}]
        assert match_experience_entries(base, candidates) == [candidates[0]]

    def test_fallback_claims_each_candidate_at_most_once(self) -> None:
        base = [
            {"company": "Acme", "start": "2020-01"},
            {"company": "Acme", "start": "2021-01"},
        ]
        candidates = [{"company": "Acme", "start": "unrelated-format", "highlights": ["only one"]}]
        result = match_experience_entries(base, candidates)
        assert result[0] is candidates[0]
        assert result[1] is None

    def test_no_match_when_company_absent(self) -> None:
        base = [{"company": "Acme", "start": "2020"}]
        candidates = [{"company": "Other", "start": "2020"}]
        assert match_experience_entries(base, candidates) == [None]

    def test_ignores_non_dict_candidates(self) -> None:
        base = [{"company": "Acme", "start": "2020"}]
        candidates = ["not-a-dict", {"company": "Acme", "start": "2020", "highlights": ["ok"]}]
        result = match_experience_entries(base, candidates)
        assert result[0]["highlights"] == ["ok"]

    def test_empty_base_returns_empty_list(self) -> None:
        assert match_experience_entries([], [{"company": "Acme", "start": "2020"}]) == []


class TestMatchEducationEntries:
    def test_matches_by_institution_case_accent_insensitive(self) -> None:
        base = [{"institution": "Universidade de São Paulo"}]
        candidates = [{"institution": "universidade de sao paulo", "degree": "B.S."}]
        assert match_education_entries(base, candidates) == [candidates[0]]

    def test_claims_each_candidate_at_most_once(self) -> None:
        base = [{"institution": "USP"}, {"institution": "USP"}]
        candidates = [{"institution": "USP", "degree": "only one"}]
        result = match_education_entries(base, candidates)
        assert result[0] is candidates[0]
        assert result[1] is None

    def test_no_match_when_institution_missing(self) -> None:
        base = [{"institution": "USP"}]
        assert match_education_entries(base, [{"degree": "no institution key"}]) == [None]


class TestMatchProjectsByName:
    def test_lookup_is_keyed_by_normalized_name(self) -> None:
        candidates = [{"name": "Projeto Alpha", "description": "x"}]
        by_name = match_projects_by_name(candidates)
        assert by_name[entity_key("projeto alpha")] == candidates[0]

    def test_first_occurrence_wins_for_duplicate_normalized_names(self) -> None:
        candidates = [
            {"name": "Alpha", "description": "first"},
            {"name": "alpha", "description": "second"},
        ]
        by_name = match_projects_by_name(candidates)
        assert by_name[entity_key("Alpha")]["description"] == "first"

    def test_skips_candidates_without_a_name(self) -> None:
        by_name = match_projects_by_name([{"description": "no name"}])
        assert by_name == {}


class TestBuildSkillLookup:
    def test_keys_by_skill_token_not_entity_key(self) -> None:
        lookup = build_skill_lookup(["C++", "C", "Node.js"])
        assert lookup[skill_token("C++")] == "C++"
        assert lookup[skill_token("C")] == "C"
        assert skill_token("C++") != skill_token("C")

    def test_first_occurrence_wins(self) -> None:
        lookup = build_skill_lookup(["React", "react"])
        assert lookup[skill_token("react")] == "React"
