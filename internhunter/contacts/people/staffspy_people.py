from __future__ import annotations

from pathlib import Path

from internhunter.contacts.types import DiscoveredPerson

# Search terms run per company; keeps the recruiter list tight and the volume low.
_SEARCH_TERMS = ["recruiter", "university recruiter", "talent acquisition"]


def discover_people_staffspy(
    company: str,
    session_file: Path,
    max_results: int = 25,
    search_terms: list[str] | None = None,
) -> list[DiscoveredPerson]:
    """Aggressive LinkedIn staff scrape via StaffSpy. Inert without a session cookie.

    Synchronous; the runner calls it via ``asyncio.to_thread``. Returns ``[]`` if the
    dependency or session file is missing, or on any rate-limit/ban response.
    """
    if not Path(session_file).exists():
        return []
    try:
        from staffspy import LinkedInAccount
    except Exception:
        return []
    try:
        account = LinkedInAccount(session_file=str(session_file), log_level=0)
    except Exception:
        return []

    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    terms = search_terms if search_terms is not None else _SEARCH_TERMS
    per_term = max(1, max_results // len(terms))
    for term in terms:
        try:
            staff = account.scrape_staff(
                company_name=company, search_term=term, max_results=per_term
            )
        except Exception:
            break  # hard-stop on Challenge / rate-limit
        rows = staff.to_dict("records") if hasattr(staff, "to_dict") else list(staff)
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            people.append(
                DiscoveredPerson(
                    full_name=name,
                    title=(row.get("position") or row.get("headline") or "").strip() or None,
                    linkedin_url=row.get("profile_link") or row.get("profile_id"),
                    known_email=(row.get("estimated_email") or "").strip() or None,
                    person_source="staffspy",
                    raw={"search_term": term},
                )
            )
    return people
