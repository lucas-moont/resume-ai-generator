from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TemplateId = Literal[
    "modern",
    "classic",
    "minimal",
    "compact",
    "ats-plain",
    "two-column-ats",
    "executive",
    "tech",
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


class ProposalItem(BaseModel):
    """One improvement inside an Improvement Proposal (CONTEXT.md: Proposal Item) -- the
    unit that makes the proposal detailed: WHAT changes (section + proposed), against WHAT
    (current excerpt), and WHY (rationale anchored in the job description)."""

    id: int
    section: ProposalSection
    current: str | None = None
    proposed: str
    rationale: str


class CreateChatSessionRequest(BaseModel):
    title: str | None = None


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
