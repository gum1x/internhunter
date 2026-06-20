from __future__ import annotations

from sqlalchemy import select

from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.db import DisclosureLead, get_session

# Reads people surfaced from public government filings (DOL OFLC LCA/PERM, SBIR/STTR) that
# were bulk-ingested into DisclosureLead — each already carries a REAL email, so the funnel
# treats it as a known address (no guessing). Zero new HTTP fetches per company.


def discover_people_gov_disclosure(
    company_slug: str, slugs: list[str] | None = None
) -> list[DiscoveredPerson]:
    keys = [s for s in (slugs or [company_slug]) if s]
    if not keys:
        return []
    session = get_session()
    try:
        rows = list(
            session.scalars(
                select(DisclosureLead).where(DisclosureLead.company_slug.in_(keys))
            )
        )
    finally:
        session.close()

    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for row in rows:
        key = (row.email or "").lower() or f"name:{(row.full_name or '').lower()}"
        if not key or key in seen:
            continue
        seen.add(key)
        people.append(
            DiscoveredPerson(
                full_name=row.full_name,
                title=row.title,
                role_category=row.role_hint or "other",
                person_source=row.source,
                known_email=row.email,
            )
        )
    return people
