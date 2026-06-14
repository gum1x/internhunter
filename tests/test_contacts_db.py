from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from internhunter.contacts.select import select_companies
from internhunter.core.db import (
    Company,
    Contact,
    ContactChannel,
    Job,
    upsert_channels,
    upsert_company,
    upsert_contact,
    upsert_contacts,
)


def _job(slug: str, score: float, domain: str | None = None) -> Job:
    now = datetime.now(UTC)
    return Job(
        job_uid=f"{slug}-1",
        ats="greenhouse",
        board_token=slug,
        canonical_url=f"https://x/{slug}",
        url_hash=f"h-{slug}",
        company=slug.title(),
        company_slug=slug,
        company_domain=domain,
        title="Intern",
        title_normalized="intern",
        is_internship=True,
        first_seen_at=now,
        last_seen_at=now,
        discovery_score=score,
    )


def test_upsert_contacts_dedupes_by_email(db_session: Any) -> None:
    c1 = Contact(company_slug="acme", email="a@acme.com", full_name="A", confidence=50)
    c2 = Contact(company_slug="acme", email="a@acme.com", full_name="A", confidence=80)
    ins, _ = upsert_contacts(db_session, [c1])
    assert ins == 1
    ins2, upd2 = upsert_contacts(db_session, [c2])
    assert ins2 == 0
    assert upd2 == 1
    row = db_session.scalar(select(Contact).where(Contact.email == "a@acme.com"))
    assert row.confidence == 80


def test_upsert_contacts_distinct_emails(db_session: Any) -> None:
    rows = [
        Contact(company_slug="acme", email="a@acme.com"),
        Contact(company_slug="acme", email="b@acme.com"),
    ]
    ins, _ = upsert_contacts(db_session, rows)
    assert ins == 2


def test_upsert_channels_idempotent_and_best_confidence(db_session: Any) -> None:
    from sqlalchemy import select

    contact = Contact(company_slug="acme", full_name="Jane Doe", email="j@acme.com")
    row, was_new = upsert_contact(db_session, contact)
    assert was_new
    chans = [
        ContactChannel(kind="x", value="https://x.com/jane", confidence=85.0, label="verified"),
        ContactChannel(kind="github", value="https://github.com/jane", confidence=90.0),
        ContactChannel(kind="personal_email", value="jane@gmail.com", confidence=40.0),
    ]
    assert upsert_channels(db_session, row.id, chans) == 3
    db_session.commit()
    # second run: no new rows (idempotent on contact_id/kind/value_norm)
    again = [ContactChannel(kind="x", value="https://x.com/jane/", confidence=50.0)]
    assert upsert_channels(db_session, row.id, again) == 0
    db_session.commit()
    rows = list(db_session.scalars(select(ContactChannel)))
    assert len(rows) == 3
    # lower-confidence re-upsert does NOT downgrade the X channel
    x = next(r for r in rows if r.kind == "x")
    assert x.confidence == 85.0


def test_upsert_company_updates(db_session: Any) -> None:
    upsert_company(db_session, Company(company_slug="acme", status="pending"))
    upsert_company(
        db_session, Company(company_slug="acme", domain="acme.com", status="done")
    )
    row = db_session.scalar(select(Company).where(Company.company_slug == "acme"))
    assert row.domain == "acme.com"
    assert row.status == "done"


def test_select_companies_orders_by_score_and_skips_done(db_session: Any) -> None:
    db_session.add_all([_job("acme", 0.9, "acme.com"), _job("beta", 0.3)])
    db_session.commit()
    targets = select_companies(db_session)
    assert [t.company_slug for t in targets] == ["acme", "beta"]
    assert targets[0].domain == "acme.com"

    upsert_company(db_session, Company(company_slug="acme", status="done"))
    targets2 = select_companies(db_session)
    assert [t.company_slug for t in targets2] == ["beta"]


def test_select_companies_min_score_filter(db_session: Any) -> None:
    db_session.add_all([_job("acme", 0.9), _job("beta", 0.1)])
    db_session.commit()
    targets = select_companies(db_session, min_score=0.5)
    assert [t.company_slug for t in targets] == ["acme"]
