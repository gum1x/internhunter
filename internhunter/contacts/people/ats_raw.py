from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.db import Job, OfficerLead, get_session

# Mines people from data ALREADY in the DB — zero new HTTP fetches:
#  - SmartRecruiters `creator` (recruiter name) persisted into Job.raw
#  - in-description "Hiring Manager: X" / "report to X" patterns
#  - literal @company-domain emails in the description (corpus fuel)
#  - SEC EDGAR officer names (OfficerLead table)

# Case-insensitive trigger via (?i:...) but a case-SENSITIVE name group so it only
# captures a real "First Last", never a lowercased phrase.
_MANAGER_RE = re.compile(
    r"(?i:hiring manager|reporting to|reports? to|you(?:'ll| will) report to|contact)"
    r"\s*[:\-]?\s*(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
)
# A plausible "First Last" — two/three capitalized tokens, not ALLCAPS headings.
_NAME_OK = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}$")


def _email_re(domain: str) -> re.Pattern[str]:
    return re.compile(r"[A-Za-z0-9._%+-]+@" + re.escape(domain), re.IGNORECASE)


def extract_named_people(raw: dict[str, Any], description_text: str) -> list[DiscoveredPerson]:
    people: list[DiscoveredPerson] = []
    creator = raw.get("creator") if isinstance(raw, dict) else None
    if isinstance(creator, dict):
        name = str(creator.get("name") or "").strip()
        if name and _NAME_OK.match(name):
            people.append(
                DiscoveredPerson(
                    full_name=name, role_category="recruiter", person_source="ats_creator"
                )
            )
    for m in _MANAGER_RE.finditer(description_text or ""):
        name = m.group("name").strip()
        if _NAME_OK.match(name):
            people.append(
                DiscoveredPerson(
                    full_name=name,
                    role_category="hiring_manager",
                    person_source="ats_description",
                )
            )
    return people


def extract_domain_emails(description_text: str, domain: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _email_re(domain).finditer(description_text or "")})


def discover_people_ats_raw(company_slug: str, domain: str | None = None) -> list[DiscoveredPerson]:
    """Named people for a company from stored ATS JSON, descriptions, and EDGAR officers."""
    session = get_session()
    try:
        rows = list(
            session.execute(
                select(Job.raw, Job.description_text).where(Job.company_slug == company_slug)
            )
        )
        officers = list(
            session.scalars(
                select(OfficerLead).where(OfficerLead.company_slug == company_slug)
            )
        )
    finally:
        session.close()

    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for raw, desc in rows:
        for person in extract_named_people(raw or {}, desc or ""):
            key = person.dedup_key()
            if key not in seen:
                seen.add(key)
                people.append(person)
    for officer in officers:
        person = DiscoveredPerson(
            full_name=officer.full_name,
            role_category=officer.role_hint or "other",
            person_source="edgar_officer",
        )
        if person.dedup_key() not in seen:
            seen.add(person.dedup_key())
            people.append(person)
    return people


def harvest_ats_emails(company_slug: str, domain: str) -> list[str]:
    """Literal @domain emails published in stored job descriptions (corpus fuel)."""
    session = get_session()
    try:
        descs = list(
            session.scalars(
                select(Job.description_text).where(Job.company_slug == company_slug)
            )
        )
    finally:
        session.close()
    found: set[str] = set()
    for desc in descs:
        found.update(extract_domain_emails(desc or "", domain))
    return sorted(found)
