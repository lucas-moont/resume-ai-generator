from pydantic import BaseModel, ConfigDict, Field


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


class GitHubRepoInfo(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    private: bool = False
