"""Unit tests for the Search Profile service (v7 ticket 06).

Same setup as tests/unit/test_jobs_repo.py: a real in-memory SQLite engine built by the
production path (``create_db_engine`` + ``init_db``), so the get/put round trip goes through
the actual table and its JSON columns rather than an ORM-only stand-in.

Invalid inputs are built with ``SearchProfileIn.model_construct``, which skips Pydantic
validation on purpose: over HTTP those values never reach the service (the ``Literal``s in the
frozen contract 422 first -- see tests/integration/test_jobs_search_profile_api.py), so this is
the only way to exercise the service's OWN gate, the one every non-HTTP caller depends on.

No LLM, no network.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.domain.schemas import ProfileMaster, SearchProfileIn
from app.repositories import jobs_repo
from app.services.jobboards.provider_registry import BOARD_SPECS, known_board_ids
from app.services.jobs import search_profile_service as svc


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _profile(**overrides) -> ProfileMaster:
    defaults = dict(fullName="Ada Lovelace", headline="", summary="", locale="pt-BR")
    defaults.update(overrides)
    return ProfileMaster(**defaults)


def _valid_in(**overrides) -> SearchProfileIn:
    defaults = dict(
        roles=["Backend Engineer"],
        locations=["São Paulo"],
        remote="remote_only",
        languages=["pt"],
        boards=["linkedin"],
        maxApplicantBand="<25",
        intervalHours=6,
    )
    defaults.update(overrides)
    return SearchProfileIn(**defaults)


class TestDefaults:
    def test_a_user_who_never_saved_gets_the_documented_defaults(self, session):
        out = svc.get_search_profile(session)

        assert out.roles == []
        assert out.locations == ["Brasil", "Remote"]
        assert out.remote == "any"
        assert out.languages == ["pt", "en"]
        assert out.boards == list(known_board_ids())
        assert out.maxApplicantBand is None  # "qualquer"
        assert out.intervalHours is None  # off

    def test_the_default_is_not_persisted(self, session):
        """A GET must not invent a saved Search Profile: ``search_profile`` having no row is
        what tells a scheduled Scan there is nothing to search for, and ``updatedAt is None``
        is the contract's word for "never saved"."""
        out = svc.get_search_profile(session)

        assert out.updatedAt is None
        assert jobs_repo.get_search_profile(session) is None

    def test_every_board_starts_enabled(self, session):
        """All-off would make a first Immediate Scan return nothing and read as broken."""
        assert len(svc.get_search_profile(session).boards) == len(BOARD_SPECS)


class TestPutAndGet:
    def test_a_saved_profile_comes_back_field_for_field(self, session):
        saved = svc.put_search_profile(session, _valid_in())

        reread = svc.get_search_profile(session)
        assert reread.roles == ["Backend Engineer"]
        assert reread.locations == ["São Paulo"]
        assert reread.remote == "remote_only"
        assert reread.languages == ["pt"]
        assert reread.boards == ["linkedin"]
        assert reread.maxApplicantBand == "<25"
        assert reread.intervalHours == 6
        assert reread.updatedAt is not None
        assert saved.model_dump() == reread.model_dump()

    def test_saving_twice_updates_the_single_row(self, session):
        svc.put_search_profile(session, _valid_in())
        svc.put_search_profile(session, _valid_in(roles=["Data Engineer"]))

        assert svc.get_search_profile(session).roles == ["Data Engineer"]

    def test_an_empty_list_means_empty_not_unchanged(self, session):
        """PUT, never PATCH: "I unchecked every board" has to be expressible."""
        svc.put_search_profile(session, _valid_in())
        svc.put_search_profile(session, _valid_in(boards=[], roles=[]))

        out = svc.get_search_profile(session)
        assert out.boards == []
        assert out.roles == []

    def test_none_for_band_and_interval_round_trips_as_any_and_off(self, session):
        svc.put_search_profile(session, _valid_in(maxApplicantBand=None, intervalHours=None))

        out = svc.get_search_profile(session)
        assert out.maxApplicantBand is None
        assert out.intervalHours is None

    def test_a_board_retired_after_the_save_is_dropped_on_read(self, session):
        """``search_profile.boards`` is plain text so an old row still loads; filtering the
        unknown id out on the way back keeps a retired board from 500ing every GET."""
        svc.put_search_profile(session, _valid_in(boards=["linkedin", "indeed"]))
        row = jobs_repo.get_search_profile(session)
        row.boards = '["linkedin", "myspacejobs"]'
        session.add(row)
        session.flush()

        assert svc.get_search_profile(session).boards == ["linkedin"]


class TestNormalization:
    def test_entries_are_trimmed_and_inner_whitespace_collapsed(self):
        clean = svc.normalize_search_profile(_valid_in(roles=["  Backend   Engineer  "]))

        assert clean.roles == ["Backend Engineer"]

    def test_duplicates_are_dropped_case_insensitively_keeping_the_first_spelling(self):
        clean = svc.normalize_search_profile(
            _valid_in(roles=["Backend Engineer", "backend engineer", "QA"])
        )

        assert clean.roles == ["Backend Engineer", "QA"]

    def test_blank_entries_are_dropped_rather_than_rejected(self):
        """A trailing empty chip is the form's leftover, not a request -- it must not block a
        save."""
        clean = svc.normalize_search_profile(_valid_in(locations=["Brasil", "   ", ""]))

        assert clean.locations == ["Brasil"]

    def test_boards_are_stored_in_catalog_order_whatever_order_they_were_clicked(self):
        clean = svc.normalize_search_profile(_valid_in(boards=["remoteok", "indeed", "linkedin"]))

        assert clean.boards == ["linkedin", "indeed", "remoteok"]

    def test_a_board_checked_twice_is_stored_once(self):
        clean = svc.normalize_search_profile(_valid_in(boards=["indeed", "indeed"]))

        assert clean.boards == ["indeed"]

    def test_language_casing_is_the_users_but_duplicates_still_collapse(self):
        clean = svc.normalize_search_profile(_valid_in(languages=["PT", "pt", "Español"]))

        assert clean.languages == ["PT", "Español"]


class TestValidation:
    def test_an_unknown_board_id_is_refused(self, session):
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"boards": ["myspace"]})

        with pytest.raises(svc.SearchProfileValidationError) as excinfo:
            svc.put_search_profile(session, bad)
        assert "myspace" in str(excinfo.value)

    def test_an_unknown_remote_preference_is_refused(self, session):
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"remote": "hybrid"})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)

    def test_a_band_outside_the_contract_is_refused(self, session):
        """``100+`` and ``unknown`` are real Applicant Bands but not offerable as a CAP."""
        for value in ("100+", "unknown", "<7"):
            bad = SearchProfileIn.model_construct(
                **_valid_in().model_dump() | {"maxApplicantBand": value}
            )
            with pytest.raises(svc.SearchProfileValidationError):
                svc.put_search_profile(session, bad)

    def test_an_interval_the_ui_never_offers_is_refused(self, session):
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"intervalHours": 2})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)

    def test_a_boolean_is_not_an_interval_of_one_hour(self, session):
        """``True == 1`` in Python, so a plain membership test would have stored a scan
        interval nobody chose."""
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"intervalHours": True})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)

    def test_nothing_is_written_when_validation_fails(self, session):
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"boards": ["myspace"]})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)
        assert jobs_repo.get_search_profile(session) is None

    def test_too_many_entries_are_refused(self, session):
        many = [f"Role {n}" for n in range(svc.MAX_LIST_ITEMS + 1)]
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"roles": many})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)

    def test_a_pasted_paragraph_is_refused_as_a_role(self, session):
        bad = SearchProfileIn.model_construct(
            **_valid_in().model_dump() | {"roles": ["x" * (svc.MAX_ITEM_LENGTH + 1)]}
        )

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)

    def test_a_non_list_is_refused(self, session):
        bad = SearchProfileIn.model_construct(**_valid_in().model_dump() | {"roles": "Backend"})

        with pytest.raises(svc.SearchProfileValidationError):
            svc.put_search_profile(session, bad)


class TestRolesFromHeadline:
    def test_a_plain_headline_is_one_role_verbatim(self):
        assert svc.roles_from_headline("Backend Engineer") == ["Backend Engineer"]

    @pytest.mark.parametrize(
        "headline",
        [
            "Backend Engineer | Data Engineer",
            "Backend Engineer / Data Engineer",
            "Backend Engineer, Data Engineer",
            "Backend Engineer; Data Engineer",
            "Backend Engineer · Data Engineer",
            "Backend Engineer - Data Engineer",
            "Backend Engineer — Data Engineer",
            "Backend Engineer and Data Engineer",
            "Backend Engineer e Data Engineer",
            "Backend Engineer & Data Engineer",
        ],
    )
    def test_every_documented_separator_splits(self, headline):
        assert svc.roles_from_headline(headline) == ["Backend Engineer", "Data Engineer"]

    def test_an_intra_word_hyphen_is_part_of_the_role(self):
        """"Front-end Developer" is one job. A dash only separates with space on both sides."""
        assert svc.roles_from_headline("Front-end Developer") == ["Front-end Developer"]

    def test_the_letter_e_inside_a_word_is_not_a_conjunction(self):
        assert svc.roles_from_headline("Desenvolvedor Web") == ["Desenvolvedor Web"]

    def test_segments_keep_the_users_own_words(self):
        """Verbatim: no expansion, no translation, no title-casing."""
        assert svc.roles_from_headline("dev backend pleno") == ["dev backend pleno"]

    def test_no_headline_suggests_no_role(self):
        for headline in (None, "", "   "):
            assert svc.roles_from_headline(headline) == []

    def test_a_headline_of_only_separators_suggests_no_role(self):
        assert svc.roles_from_headline(" | / , - ") == []

    def test_duplicate_segments_collapse(self):
        assert svc.roles_from_headline("QA | qa | Tester") == ["QA", "Tester"]

    def test_a_long_list_is_truncated_not_expanded(self):
        headline = " | ".join(f"Role {n}" for n in range(12))

        roles = svc.roles_from_headline(headline)

        assert roles == [f"Role {n}" for n in range(svc.MAX_SUGGESTED_ROLES)]

    def test_a_suggested_role_is_savable_as_is(self, session):
        """The suggestion must survive its own PUT -- a suggestion the form cannot save would
        be a trap."""
        suggestion = svc.suggest_from_profile(_profile(headline="Backend Engineer | SRE"))

        saved = svc.put_search_profile(session, SearchProfileIn(**suggestion.model_dump()))
        assert saved.roles == ["Backend Engineer", "SRE"]


class TestSuggestFromProfile:
    def test_roles_come_from_the_headline_and_the_rest_is_the_default(self):
        out = svc.suggest_from_profile(_profile(headline="Engenheiro de Dados | Analista de BI"))

        assert out.roles == ["Engenheiro de Dados", "Analista de BI"]
        assert out.locations == ["Brasil", "Remote"]
        assert out.languages == ["pt", "en"]
        assert out.remote == "any"
        assert out.boards == list(known_board_ids())
        assert out.maxApplicantBand is None
        assert out.intervalHours is None

    def test_a_profile_without_a_headline_suggests_no_roles(self):
        """Acceptance criterion: never invents a career direction for the candidate."""
        out = svc.suggest_from_profile(_profile(headline="   "))

        assert out.roles == []

    def test_skills_never_become_roles(self):
        """The frozen contract has no skills field, and "Python" is not a job title."""
        out = svc.suggest_from_profile(
            _profile(headline="", skills=["Python", "Docker", "PostgreSQL"])
        )

        assert out.roles == []

    def test_the_profiles_location_is_not_the_search_location(self):
        """Where you live is not where you will accept work."""
        out = svc.suggest_from_profile(_profile(headline="QA", location="Uberlândia, MG"))

        assert out.locations == ["Brasil", "Remote"]

    def test_a_suggestion_is_never_persisted(self, session):
        out = svc.suggest_from_profile(_profile(headline="QA"))

        assert out.updatedAt is None
        assert jobs_repo.get_search_profile(session) is None

    def test_the_same_profile_always_suggests_the_same_thing(self):
        profile = _profile(headline="Tech Lead / Engineering Manager")

        assert svc.suggest_from_profile(profile) == svc.suggest_from_profile(profile)


class TestBoardCatalog:
    def test_every_board_in_the_catalog_is_listed_in_order(self):
        listed = svc.list_boards().boards

        assert [b.id for b in listed] == list(known_board_ids())
        assert [b.displayName for b in listed] == [s.display_name for s in BOARD_SPECS]

    def test_remotive_carries_its_own_minimum_interval(self):
        """Its terms allow four calls a day; the form has to show that a 1h interval does not
        mean 1h for every board."""
        by_id = {b.id: b for b in svc.list_boards().boards}

        assert by_id["remotive"].minIntervalHours == 6
        assert by_id["linkedin"].minIntervalHours == 1

    def test_only_the_boards_whose_terms_require_it_carry_an_attribution_note(self):
        by_id = {b.id: b for b in svc.list_boards().boards}

        assert "Remotive" in (by_id["remotive"].attributionNote or "")
        assert "Remote OK" in (by_id["remoteok"].attributionNote or "")
        assert by_id["linkedin"].attributionNote is None
