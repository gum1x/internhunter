from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Role categories the classifier assigns, ranked best-first for internship outreach.
ROLE_CATEGORIES = [
    "university_recruiter",
    "technical_recruiter",
    "recruiter",
    "hiring_manager",
    "eng_manager",
    "ic_engineer",
    "hr",
    "other",
]

# Outreach priority by role (higher = contact first for an internship).
ROLE_PRIORITY: dict[str, float] = {
    "university_recruiter": 1.0,
    "technical_recruiter": 0.85,
    "recruiter": 0.8,
    "hiring_manager": 0.65,
    "eng_manager": 0.6,
    "ic_engineer": 0.45,
    "hr": 0.4,
    "other": 0.2,
}


@dataclass
class DiscoveredPerson:
    """A person found at a company, before email finding / scoring."""

    full_name: str | None = None
    title: str | None = None
    role_category: str | None = None
    linkedin_url: str | None = None
    github_login: str | None = None
    person_source: str | None = None  # searxng|github|staffspy|team_page
    # A real, already-known email tied to this person (e.g. a GitHub commit email).
    known_email: str | None = None
    # Extra reach channels: each {kind, value, source, confidence, status}.
    channels: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def add_channel(
        self,
        kind: str,
        value: str,
        source: str | None = None,
        confidence: float | None = None,
        status: str = "guessed",
    ) -> None:
        if not value:
            return
        norm = value.strip().lower().rstrip("/")
        if any(c["kind"] == kind and c["value"].strip().lower().rstrip("/") == norm
               for c in self.channels):
            return
        self.channels.append(
            {"kind": kind, "value": value.strip(), "source": source,
             "confidence": confidence, "status": status}
        )

    def dedup_key(self) -> str:
        if self.linkedin_url:
            return self.linkedin_url.lower().rstrip("/")
        if self.github_login:
            return f"gh:{self.github_login.lower()}"
        return f"name:{(self.full_name or '').strip().lower()}"


@dataclass
class EmailResult:
    """Outcome of email finding + verification + scoring for one person."""

    email: str | None = None
    email_status: str = "guessed"  # scraped|github|guessed|holehe_confirmed|smtp_valid|invalid
    email_source: str | None = None
    confidence: float = 0.0
    label: str = "guessed"  # verified|probable|guessed|invalid
    evidence: dict[str, Any] = field(default_factory=dict)
