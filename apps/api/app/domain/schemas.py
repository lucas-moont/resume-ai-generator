from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class RevertProfileRequest(BaseModel):
    toVersion: int
