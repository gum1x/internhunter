from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from internhunter.contacts.people.ats_raw import (
    discover_people_ats_raw,
    extract_domain_emails,
    extract_named_people,
    harvest_ats_emails,
)
from internhunter.core.db import Job, OfficerLead


def test_extract_creator_recruiter() -> None:
    people = extract_named_people({"creator": {"name": "Jane Doe"}}, "")
    assert len(people) == 1
    assert people[0].full_name == "Jane Doe"
    assert people[0].role_category == "recruiter"
    assert people[0].person_source == "ats_creator"


def test_extract_creator_ignores_empty_and_headings() -> None:
    assert extract_named_people({"creator": {"name": ""}}, "") == []
    assert extract_named_people({"creator": {"name": "ACME CORP"}}, "") == []


def test_extract_hiring_manager_from_description() -> None:
    text = "You will be reporting to Sarah Connor, our Director of Engineering."
    people = extract_named_people({}, text)
    managers = [p.full_name for p in people if p.role_category == "hiring_manager"]
    assert "Sarah Connor" in managers


def test_extract_domain_emails() -> None:
    text = "Questions? Email jane.doe@acme.com or recruiting@acme.com. Not bob@other.com."
    found = extract_domain_emails(text, "acme.com")
    assert "jane.doe@acme.com" in found
    assert "recruiting@acme.com" in found
    assert "bob@other.com" not in found


def _job(slug: str, raw: dict[str, Any], desc: str) -> Job:
    now = datetime.now(UTC)
    return Job(
        job_uid=f"{slug}-1", ats="smartrecruiters", board_token=slug,
        canonical_url=f"https://x/{slug}", url_hash=f"h{slug}", company=slug,
        company_slug=slug, title="Intern", title_normalized="intern", is_internship=True,
        description_text=desc, raw=raw, first_seen_at=now, last_seen_at=now,
    )


def test_discover_people_ats_raw_reads_db(db_session: Any, monkeypatch: Any) -> None:
    db_session.add(_job("acme", {"creator": {"name": "Jane Doe"}}, "Contact Mark Smith to apply."))
    db_session.add(OfficerLead(company_slug="acme", full_name="Bob Officer", source="edgar"))
    db_session.commit()
    monkeypatch.setattr("internhunter.contacts.people.ats_raw.get_session", lambda: db_session)
    # prevent the helper from closing the shared fixture session
    monkeypatch.setattr(db_session, "close", lambda: None)
    people = discover_people_ats_raw("acme", "acme.com")
    names = {p.full_name for p in people}
    assert "Jane Doe" in names  # creator
    assert "Mark Smith" in names  # description manager pattern
    assert "Bob Officer" in names  # EDGAR officer lead


def test_harvest_ats_emails_reads_db(db_session: Any, monkeypatch: Any) -> None:
    db_session.add(_job("acme", {}, "Reach us at careers@acme.com."))
    db_session.commit()
    monkeypatch.setattr("internhunter.contacts.people.ats_raw.get_session", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    assert "careers@acme.com" in harvest_ats_emails("acme", "acme.com")
