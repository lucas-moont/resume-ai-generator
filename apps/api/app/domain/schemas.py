from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale

TemplateId = Literal[
    "modern",
    "classic",
    "minimal",
    "compact",
    "ats-plain",
    "two-column-ats",
    "executive",
    "tech",
    "latex-ats",
]
DEFAULT_TEMPLATE: TemplateId = "modern"


class Link(BaseModel):
    label: str
    url: str


class ExperienceItem(BaseModel):
    company: str
    title: str
    location: str | None = None
    start: str = ""
    end: str | None = None
    highlights: list[str] = Field(default_factory=list)
    # Key Technologies (v7): the technologies this role actually used, rendered as one
    # keyword line under the bullets. Plain technology names only -- same content rule as
    # ``skills`` (no HTML, no prose), enforced by ``sanitize_resume_for_display`` and by
    # ``_clean_technology_chip`` in the resume JSON parser. Optional and empty by default:
    # every resume/profile persisted before this field existed keeps loading unchanged, and
    # an empty list simply renders no line (CONTEXT.md: Key Technologies).
    keyTechnologies: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""


class EducationItem(BaseModel):
    institution: str
    degree: str
    end: str | None = None
    details: str | None = None


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fullName: str
    headline: str
    location: str | None = None
    email: str | None = None
    phone: str | None = None
    links: list[Link] = Field(default_factory=list)
    summary: str
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    locale: str = "pt-BR"

    @field_validator("locale", mode="before")
    @classmethod
    def _fold_locale_onto_a_supported_one(cls, value: object) -> object:
        """Coerce, never reject: an unsupported locale label becomes a supported one.

        ``locale`` is typed ``str`` rather than a ``Literal`` on purpose. 8 resume versions
        already persisted carry ``en-US`` (an LLM's own invention -- nothing validated this
        field before v6), and a ``Literal`` would make every one of them unloadable, breaking
        rehydration of real chat sessions to fix a cosmetic drift. Folding on the way IN
        normalizes those rows the next time they are read, and keeps the invariant every
        consumer wants: the value is always exactly ``"pt-BR"`` or ``"en"``.

        A value that is not a recognizable variant of either language falls back to the default
        rather than raising -- the document itself is still fine, and refusing to load it over
        its language tag would lose real work.
        """
        folded = normalize_locale(value)
        if folded is not None:
            return folded
        return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


class ProfileMaster(ResumeDocument):
    githubUsername: str | None = None


class GenerateRequest(BaseModel):
    job_description: str
    model: str | None = None
    locale: str | None = None


class RefineRequest(BaseModel):
    resume: ResumeDocument
    message: str
    model: str | None = None


class PdfExportRequest(BaseModel):
    resume: ResumeDocument
    template: TemplateId = DEFAULT_TEMPLATE


class GitHubRepoInfo(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    private: bool = False


# v4 (ticket 00): the section vocabulary a Proposal Item may target -- the ResumeDocument
# sections an Analysis is allowed to propose changes to. Anything outside this whitelist is
# dropped by proposal_json_parser (never an error).
ProposalSection = Literal[
    "headline",
    "summary",
    "experience",
    "projects",
    "skills",
    "education",
    "links",
    "location",
]


# v6 (Relevance Filter): the OPERATION a Proposal Item performs on its section. Before v6 every
# item was implicitly a rewrite, which is why the agent could never offer to *subtract* profile
# noise -- it could only swap text for other text. The vocabulary is deliberately small:
#
# - ``rewrite``  -- the pre-v6 behavior and the default: replace ``current`` wording with
#                   ``proposed``. Absent/unknown ``op`` on a persisted item decodes to this, so
#                   proposals stored before v6 keep validating unchanged.
# - ``add``      -- surface something real the profile has but the resume was not showing
#                   (already supported downstream by ``_agreed_skills_text``).
# - ``drop``     -- REMOVE the entities named in ``targets`` from the generated resume because
#                   they have no bearing on THIS job. Only honored for ``skills`` and
#                   ``projects``: dropping an employer/role or a degree would open a timeline
#                   gap, which the Relevance Filter never does (it compresses instead).
# - ``compress`` -- keep the entity (employer, dates, title stay untouched) but give it far less
#                   space: an unrelated role drops to one factual bullet instead of four. This op
#                   is instruction-only -- it reaches the LLM through the APPROVED IMPROVEMENT
#                   PLAN block and needs no anchor support, since the anchor already adopts
#                   whatever (non-empty) highlight list the model returns for a matched role.
ProposalOp = Literal["rewrite", "add", "drop", "compress"]


class ProposalItem(BaseModel):
    """One improvement inside an Improvement Proposal (CONTEXT.md: Proposal Item) -- the
    unit that makes the proposal detailed: WHAT changes (section + proposed), against WHAT
    (current excerpt), and WHY (rationale anchored in the job description).

    ``op``/``targets`` (v6, Relevance Filter) are additive with defaults, so every item written
    before v6 -- including the JSON blobs already sitting in ``improvement_proposals.items`` --
    still validates and still means exactly what it meant then (a rewrite with no targets).

    ``targets`` carries the LITERAL profile labels an ``op`` acts on (skill names, project
    names). It exists instead of parsing them back out of ``current``/``proposed`` prose
    because a drop is matched deterministically downstream (``skill_token``/``entity_key``
    equality, never substring): removing the wrong skill is a worse failure than removing
    nothing, so the target set is never inferred from free text.
    """

    id: int
    section: ProposalSection
    op: ProposalOp = "rewrite"
    current: str | None = None
    proposed: str
    rationale: str
    targets: list[str] = Field(default_factory=list)


# v5 (ticket 00): the LinkedIn profile sections an Analysis Item may target. Anything outside
# this whitelist is dropped by analysis_json_parser (never an error) -- mirrors ProposalSection.
AnalysisSection = Literal[
    "headline",
    "about",
    "experience",
    "skills",
    "completeness",
]

AnalysisPriority = Literal["alta", "média", "baixa"]


class AnalysisItem(BaseModel):
    """One recommendation inside a Profile Analysis (CONTEXT.md: Analysis Item): the target
    LinkedIn section, the user's current text (optional), the suggested change, a rationale
    anchored in a LinkedIn best practice / the context given, and a priority."""

    section: AnalysisSection
    current: str | None = None
    suggestion: str
    rationale: str
    priority: AnalysisPriority


class AnalysisResult(BaseModel):
    """The ``analysis`` outcome of an Analysis Turn: one or more Analysis Items plus a short
    prose summary in the user's locale. Read-only advice -- an Analysis never mutates the
    Living Profile nor produces a Resume."""

    type: Literal["analysis"] = "analysis"
    items: list[AnalysisItem] = Field(default_factory=list)
    summary: str = ""


class AnalysisQuestion(BaseModel):
    """The ``question`` outcome of an Analysis Turn (CONTEXT.md: Clarifying Question): the
    motor asks for the missing context (target role, seniority, audience, goal) instead of
    guessing -- same filosofia as refine.md's ask-instead-of-guessing valve."""

    type: Literal["question"] = "question"
    reply: str


# v5 (ticket b1): discriminates the resume chat from the Profile Analysis area.
ChatSessionKind = Literal["resume", "profile_analysis"]


class CreateChatSessionRequest(BaseModel):
    title: str | None = None
    # v5 (ticket b1): create a Profile Analysis conversation instead of a resume chat. Default
    # 'resume' keeps every pre-v5 caller (which never sent this field) byte-identical.
    kind: ChatSessionKind = "resume"


class ChatMessageRequest(BaseModel):
    message: str
    model: str | None = None
    locale: str | None = None
    jobDescription: str | None = None
    # v2 ticket 11: the client's own in-memory resume (post inline-edit), sent whenever it has
    # an active resume -- lets a chat `refine` turn start from what the user is actually looking
    # at instead of the last version the server persisted. Validated by pydantic like any other
    # field (an invalid shape here is a normal 422, before the stream ever starts). Ignored by
    # every intent except `refine` -- see chat_service.handle_chat_turn.
    resume: ResumeDocument | None = None
    # v4 (ticket 00): deterministic shortcut carried by the "Aprovar e gerar" button -- routes
    # the turn straight into the approve branch of the Proposal Turn with ZERO LLM
    # classification spent. Ignored when the session has no Pending Proposal (the message is
    # then routed normally). See docs/v4-improvement-proposal.md #3.1.
    proposalAction: Literal["approve"] | None = None


class RevertProfileRequest(BaseModel):
    toVersion: int


class RenameChatSessionRequest(BaseModel):
    """v4.1-03 (frozen contract): PATCH /api/chat/sessions/{id} body -- ``title`` must be
    1..120 chars AFTER trimming surrounding whitespace, and non-blank. Validated on the
    trimmed value (not the raw one) so surrounding whitespace never counts against the
    120-char limit, and the trimmed, canonical value is what callers get back."""

    title: str

    @field_validator("title")
    @classmethod
    def _trim_and_validate(cls, v: str) -> str:
        trimmed = v.strip()
        if not (1 <= len(trimmed) <= 120):
            raise ValueError("title must be 1..120 characters after trimming")
        return trimmed
