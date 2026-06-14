from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from internhunter.core.db import Contact, ContactChannel, get_session, init_db
from internhunter.web.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    init_db(db_path=tmp_path / "c.db")
    session = get_session()
    contact = Contact(
        company_slug="acme", full_name="Jane Doe", title="Recruiter",
        role_category="recruiter", email="jane@acme.com", email_status="guessed",
        confidence=60.0, label="probable", evidence={"identity_confidence": 70.0},
    )
    session.add(contact)
    session.flush()
    session.add_all([
        ContactChannel(contact_id=contact.id, kind="x", value="https://x.com/jane",
                       value_norm="https://x.com/jane", confidence=85.0, label="verified"),
        ContactChannel(contact_id=contact.id, kind="github", value="https://github.com/jane",
                       value_norm="https://github.com/jane", confidence=90.0, label="verified"),
        ContactChannel(contact_id=contact.id, kind="personal_email", value="jane@gmail.com",
                       value_norm="jane@gmail.com", confidence=60.0, label="probable"),
    ])
    session.commit()
    session.close()
    with TestClient(create_app()) as c:
        yield c


def test_contacts_page_shows_channels(client: TestClient) -> None:
    body = client.get("/contacts").text
    assert "Jane Doe" in body
    assert "github" in body  # channel chip
    assert "x" in body


def test_contacts_csv_has_channel_columns(client: TestClient) -> None:
    resp = client.get("/contacts/export.csv")
    assert resp.status_code == 200
    text = resp.text
    assert "personal_email" in text.splitlines()[0]  # header has channel columns
    assert "github" in text.splitlines()[0]
    assert "jane@gmail.com" in text  # personal email surfaced
    assert "https://github.com/jane" in text
