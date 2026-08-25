"""Unit tests for app/domain/listing_identity.py (v7 ticket 03).

The Job Listing identity is what dedup, Repost detection and the Listing Memory are all keyed
by, so these cases are the specification of "same job" -- and of its opposite, which matters
more: an assertion here that two DIFFERENT jobs keep different keys is protecting a real
posting from disappearing into another one's Listing Sources.

Pure functions, no I/O -- same shape as tests/unit/test_entity_identity.py.
"""

from __future__ import annotations

import pytest

from app.domain.listing_identity import identity_key, normalize_company, normalize_title


class TestNormalizeCompany:
    def test_case_and_whitespace_insensitive(self) -> None:
        assert normalize_company("Acme Tech") == normalize_company("ACME   tech") == "acmetech"

    def test_spacing_variants_of_the_same_employer_merge(self) -> None:
        # One board prints "Acme Tech", another "AcmeTech" -- one employer.
        assert normalize_company("Acme Tech") == normalize_company("AcmeTech")

    def test_accent_insensitive(self) -> None:
        assert normalize_company("Açaí Soluções") == normalize_company("Acai Solucoes")

    def test_punctuation_stripped(self) -> None:
        assert normalize_company("Ben & Jerry's") == "benjerrys"
        assert normalize_company("Booking.com") == "bookingcom"

    @pytest.mark.parametrize(
        "printed",
        [
            "Acme Ltda",
            "Acme Ltda.",
            "Acme, Inc.",
            "Acme Inc",
            "Acme S.A.",
            "Acme S/A",
            "Acme LLC",
            "Acme GmbH",
            "ACME HOLDINGS INC",
        ],
    )
    def test_corporate_suffixes_stripped(self, printed: str) -> None:
        assert normalize_company(printed) == "acme"

    def test_suffix_only_name_keeps_its_single_token(self) -> None:
        # Stripping down to an empty company would merge every such employer into one.
        assert normalize_company("Ltda") == "ltda"

    def test_suffix_word_inside_the_name_is_kept(self) -> None:
        # Only a TRAILING suffix is a legal form; "Inc" here is part of the name.
        assert normalize_company("Inc Digital") == "incdigital"

    def test_empty_and_none(self) -> None:
        assert normalize_company("") == ""
        assert normalize_company(None) == ""
        assert normalize_company("   ") == ""


class TestNormalizeTitleSeniority:
    def test_abbreviated_seniority_matches_the_written_form(self) -> None:
        assert normalize_title("Sr. Software Engineer") == normalize_title("Senior Software Engineer")
        assert normalize_title("Jr Developer") == normalize_title("Junior Developer")

    def test_accented_seniority(self) -> None:
        assert normalize_title("Desenvolvedor Sênior") == normalize_title("Desenvolvedor Senior")

    def test_repeated_seniority_collapses(self) -> None:
        assert normalize_title("Sr. Senior Software Engineer") == "seniorsoftwareengineer"
        assert normalize_title("Senior Software Engineer Sr") == "seniorsoftwareengineer"

    def test_mid_level_synonyms(self) -> None:
        assert normalize_title("Mid-Level Backend Engineer") == normalize_title("Pleno Backend Engineer")
        assert normalize_title("Middle Backend Engineer") == "midbackendengineer"

    def test_different_seniorities_stay_different(self) -> None:
        # The whole point of keeping the canonical token: these are two openings.
        assert normalize_title("Senior Developer") != normalize_title("Junior Developer")


class TestNormalizeTitleNoise:
    @pytest.mark.parametrize(
        "printed",
        [
            "Backend Engineer (Remote)",
            "Backend Engineer (remoto)",
            "Backend Engineer (m/f/d)",
            "Backend Engineer [Remote]",
            "Backend Engineer | Remote",
            "Backend Engineer - Remote",
            "Backend Engineer — Home Office",
            "Backend Engineer (PJ)",
            "Backend Engineer (Full Time)",
        ],
    )
    def test_work_arrangement_noise_dropped(self, printed: str) -> None:
        assert normalize_title(printed) == normalize_title("Backend Engineer")

    def test_meaningful_parenthetical_is_kept(self) -> None:
        assert normalize_title("Engineer (Backend)") != normalize_title("Engineer (Frontend)")

    def test_location_in_the_title_is_kept(self) -> None:
        # Deliberate: the set of place names is open, and these are two openings.
        assert normalize_title("Engineer (Berlin)") != normalize_title("Engineer (Munich)")

    def test_a_title_made_only_of_noise_is_not_emptied(self) -> None:
        assert normalize_title("Remote") == "remote"

    def test_hyphen_inside_a_word_is_not_a_separator(self) -> None:
        assert normalize_title("Front-end Developer") == normalize_title("Front End Developer")
        assert normalize_title("Front-end Developer") == normalize_title("Frontend Developer")


class TestNormalizeTitleTechnology:
    def test_technology_punctuation_survives(self) -> None:
        # entity_key would collapse both to "cdeveloper"; skill_token is used here precisely
        # so two different jobs at one employer stay two Job Listings.
        assert normalize_title("C# Developer") != normalize_title("C++ Developer")

    def test_dot_prefixed_and_dotted_names(self) -> None:
        assert normalize_title(".NET Developer") == "netdeveloper"
        assert normalize_title("Node.js Engineer") == normalize_title("node.js engineer")

    def test_empty_and_none(self) -> None:
        assert normalize_title("") == ""
        assert normalize_title(None) == ""


class TestIdentityKey:
    def test_shape_is_company_pipe_title(self) -> None:
        key = identity_key("Acme Tech", "Backend Engineer")
        assert key == "acmetech|backendengineer"
        assert key.count("|") == 1

    def test_same_job_printed_by_two_boards(self) -> None:
        linkedin = identity_key("Acme Tech Ltda.", "Sr. Backend Engineer (Remote)")
        indeed = identity_key("ACME TECH", "Senior Backend Engineer")
        assert linkedin == indeed

    def test_same_title_at_different_employers_differs(self) -> None:
        assert identity_key("Acme", "Backend Engineer") != identity_key("Globex", "Backend Engineer")

    def test_different_titles_at_one_employer_differ(self) -> None:
        assert identity_key("Acme", "Backend Engineer") != identity_key("Acme", "Frontend Engineer")

    def test_is_deterministic(self) -> None:
        assert identity_key("Acme", "Dev") == identity_key("Acme", "Dev")

    def test_garbage_in_yields_one_deterministic_key(self) -> None:
        assert identity_key(None, None) == "|"
        assert identity_key("", "") == "|"
