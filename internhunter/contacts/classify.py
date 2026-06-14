from __future__ import annotations

from typing import TYPE_CHECKING

from internhunter.contacts.types import ROLE_PRIORITY

if TYPE_CHECKING:
    from internhunter.llm.client import LlmBackend, LlmCache

_CLASSIFY_SYSTEM = (
    "Classify a job title into exactly one role category. Return ONLY JSON "
    '{"role_category":"..."} where role_category is one of: university_recruiter, '
    "technical_recruiter, recruiter, hiring_manager, eng_manager, ic_engineer, hr, other."
)

# Keyword heuristic — used as a fallback when no LLM backend is available, and to
# avoid an LLM call for obvious titles. Order matters (most specific first).
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("university recruit", "campus", "early career", "early talent", "student program"),
     "university_recruiter"),
    (("technical recruit", "tech recruit", "sourcer", "technical sourcer"),
     "technical_recruiter"),
    (("recruit", "talent acquisition", "talent partner", "talent advisor"), "recruiter"),
    (("engineering manager", "eng manager", "em,", "head of engineering"), "eng_manager"),
    (("hiring manager", "director", "vp ", "head of", "lead "), "hiring_manager"),
    (("people ops", "people operations", "hr ", "human resources", "people partner"), "hr"),
    (("engineer", "developer", "swe", "software", "programmer", "intern"), "ic_engineer"),
]


def classify_title_heuristic(title: str | None) -> str:
    if not title:
        return "other"
    low = f" {title.lower()} "
    for needles, category in _RULES:
        if any(n in low for n in needles):
            return category
    return "other"


def classify_title(
    title: str | None,
    backend: LlmBackend | None = None,
    cache: LlmCache | None = None,
    model: str = "local",
) -> str:
    """Map a raw title to a role category. Falls back to the heuristic on any failure."""
    heuristic = classify_title_heuristic(title)
    if backend is None or not title or heuristic != "other":
        return heuristic
    try:
        from internhunter.llm.client import complete, extract_json

        raw = complete(
            f"Title: {title}", backend, system=_CLASSIFY_SYSTEM, cache=cache, model=model
        )
        category = str(extract_json(raw).get("role_category", "")).strip()
    except Exception:
        return heuristic
    return category if category in ROLE_PRIORITY else heuristic


def role_priority(role_category: str | None) -> float:
    return ROLE_PRIORITY.get(role_category or "other", 0.2)
