"""Shared router dependencies -- extracted from app/main.py (B4)."""


def resolve_requested_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    return normalized or None
