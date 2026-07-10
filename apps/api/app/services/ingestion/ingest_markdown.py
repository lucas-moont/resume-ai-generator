"""Markdown Source Document ingestion (v2 ticket 03, docs/v2-living-profile.md item 2).

Unlike ingest_json, Markdown has no fixed schema to validate directly -- it always goes
through LLM extraction. `python-frontmatter` (existing dependency) splits the file into
structured frontmatter metadata (e.g. ``name: Bruno Reis``) and a free-text body; both are
folded into one text blob and handed to the same extraction pipeline the PDF path (and the
v1 Profile.pdf flow) already uses, so the LLM sees whatever structure the metadata offers
alongside the prose.
"""

from __future__ import annotations

import frontmatter

from app.domain.schemas import ResumeDocument
from app.services.extraction_service import extract_profile_from_text


def _combine_frontmatter_and_body(text: str) -> str:
    post = frontmatter.loads(text)
    if not post.metadata:
        return post.content
    metadata_lines = "\n".join(f"{key}: {value}" for key, value in post.metadata.items())
    return f"{metadata_lines}\n\n{post.content}"


async def ingest_markdown(raw: bytes, *, model: str | None = None) -> ResumeDocument:
    text = raw.decode("utf-8", errors="replace")
    combined = _combine_frontmatter_and_body(text)
    return await extract_profile_from_text(combined, model=model)
