"""Backward-compatible shim.

The schemas used to live here; they now live in ``app.domain.schemas`` (see
docs/v1-chat-experience.md, step B2). Re-exported so existing imports
(``from app.models import ResumeDocument``, etc.) across the codebase and test suite keep
working unchanged.
"""

from app.domain.schemas import (
    DEFAULT_TEMPLATE,
    EducationItem,
    ExperienceItem,
    GenerateRequest,
    GitHubRepoInfo,
    Link,
    PdfExportRequest,
    ProfileMaster,
    ProjectItem,
    RefineRequest,
    ResumeDocument,
    TemplateId,
)

__all__ = [
    "DEFAULT_TEMPLATE",
    "EducationItem",
    "ExperienceItem",
    "GenerateRequest",
    "GitHubRepoInfo",
    "Link",
    "PdfExportRequest",
    "ProfileMaster",
    "ProjectItem",
    "RefineRequest",
    "ResumeDocument",
    "TemplateId",
]
