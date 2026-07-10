"""Factories for valid ``ProfileMaster``/``ResumeDocument`` payloads.

The shape here is deliberately a "strong" resume (long summary, 3+ substantial highlights on
the first role, 6+ skills, 2+ links including GitHub) so that it produces zero
``app.main._quality_issues`` by default — see ``test_generate_endpoints_compat.py`` for the
happy-path vs. auto-refine-triggering scenarios that build on top of it.
"""

from __future__ import annotations

from typing import Any


def make_profile(**overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "fullName": "Ana Costa",
        "headline": "Senior Backend Engineer",
        "location": "Sao Paulo, Brazil",
        "email": "ana.costa@example.com",
        "phone": None,
        "links": [
            {"label": "LinkedIn", "url": "https://linkedin.com/in/anacosta"},
            {"label": "GitHub", "url": "https://github.com/anacosta"},
        ],
        "summary": (
            "Senior backend engineer with over seven years building reliable, scalable "
            "services in Python and Node.js, focused on clean architecture, observability, "
            "and shipping features that hold up under real production load."
        ),
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Senior Backend Engineer",
                "location": "Remote",
                "start": "2021",
                "end": None,
                "highlights": [
                    "Led the migration of the billing service to a Python and FastAPI stack",
                    "Designed a PostgreSQL schema and caching layer that cut p95 latency by 40 percent",
                    "Mentored three engineers and ran the on-call rotation for the payments team",
                ],
            }
        ],
        "projects": [
            {
                "name": "metrics-dashboard",
                "description": (
                    "Built and shipped an internal analytics dashboard in React and Node.js "
                    "used daily by fifty engineers."
                ),
            }
        ],
        "skills": [
            "Python",
            "FastAPI",
            "Node.js",
            "PostgreSQL",
            "Docker",
            "AWS",
            "Redis",
            "Kubernetes",
        ],
        "education": [
            {
                "institution": "Universidade de Sao Paulo",
                "degree": "B.Sc. in Computer Science",
                "end": "2016",
                "details": None,
            }
        ],
        "locale": "en",
        "githubUsername": None,
    }
    profile.update(overrides)
    return profile


def make_resume_payload(**overrides: Any) -> dict[str, Any]:
    """Same shape as ``make_profile`` but without ``githubUsername`` (``ResumeDocument``, not
    ``ProfileMaster``) — used for ``/api/refine`` bodies and for scripting LLM JSON replies."""
    payload = make_profile(**overrides)
    payload.pop("githubUsername", None)
    return payload
