from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from internhunter.core.db import Application, Contact, Job, get_session, init_db
from internhunter.web.app import _best_contact, create_app


def _job(uid: str, title: str, slug: str = "acme") -> Job:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://example.com/{uid}",
        url_hash=uid,
        company="Acme Corp",
        company_slug=slug,
        title=title,
        title_normalized=title.lower(),
        is_internship=True,
        internship_kind="intern",
        location_normalized="Remote",
        is_remote=True,
        posted_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )


def _contact(slug: str, name: str, email: str, status: str, priority: float) -> Contact:
    return Contact(
        company_slug=slug,
        full_name=name,
        email=email,
        email_status=status,
        priority=priority,
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    init_db(db_path=tmp_path / "t.db")
    s = get_session()
    s.add(_job("i1", "Data Intern"))
    s.add(_contact("acme", "Lo Priority", "lo@acme.com", "guessed", 9.0))
    s.add(_contact("acme", "Jane Hiring", "jane@acme.com", "verified", 1.0))
    s.commit()
    s.close()
    with TestClient(create_app()) as c:
        yield c


def test_track_creates_row_and_shows_live_contact(client: TestClient) -> None:
    r = client.post("/jobs/i1/track")
    assert r.status_code == 200
    assert "Tracked" in r.text
    s = get_session()
    a = s.scalar(select(Application).where(Application.job_uid == "i1"))
    assert a is not None
    assert a.status == "To Apply"
    assert a.company == "Acme Corp"
    assert a.company_slug == "acme"
    assert a.role == "Data Intern"
    assert a.link == "https://example.com/i1"
    # contact is NOT snapshotted — fetched live from the contacts table
    assert a.contact_email is None
    s.close()
    # the tracker page renders the live best saved contact (verified beats guessed)
    body = client.get("/tracker").text
    assert "jane@acme.com" in body
    assert "Jane Hiring" in body


def test_track_is_idempotent(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    client.post("/jobs/i1/track")
    s = get_session()
    rows = list(s.scalars(select(Application).where(Application.job_uid == "i1")))
    assert len(rows) == 1
    s.close()


def test_track_unknown_job_404(client: TestClient) -> None:
    assert client.post("/jobs/nope/track").status_code == 404


def test_application_job_uid_is_unique(client: TestClient) -> None:
    """DB-level guard backs the idempotency check against the concurrent-add race."""
    from sqlalchemy.exc import IntegrityError

    s = get_session()
    s.add(Application(job_uid="i1", status="To Apply"))
    s.commit()
    s.add(Application(job_uid="i1", status="To Apply"))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
    s.close()


def test_update_status_stamps_applied_and_emailed(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    s = get_session()
    aid = s.scalar(select(Application.id))
    s.close()
    assert client.post(f"/tracker/{aid}/update", data={"status": "Applied"}).status_code == 200
    assert client.post(f"/tracker/{aid}/update", data={"emailed": "yes"}).status_code == 200
    s = get_session()
    a = s.get(Application, aid)
    assert a is not None
    assert a.status == "Applied"
    assert a.applied_at is not None  # auto-stamped on first Applied
    assert a.emailed is True
    s.close()


def test_update_due_date_set_and_clear(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    s = get_session()
    aid = s.scalar(select(Application.id))
    s.close()
    client.post(f"/tracker/{aid}/update", data={"due_date": "2026-07-15"})
    s = get_session()
    a = s.get(Application, aid)
    assert a is not None and a.due_date is not None
    assert a.due_date.strftime("%Y-%m-%d") == "2026-07-15"
    s.close()
    # Clearing: the browser/HTMX sends `due_date=` (present-but-empty). httpx's data={} drops
    # empty values, so send the raw wire body to exercise the real clear path.
    _form = {"content-type": "application/x-www-form-urlencoded"}
    client.post(f"/tracker/{aid}/update", content="due_date=", headers=_form)
    s = get_session()
    a = s.get(Application, aid)
    assert a is not None and a.due_date is None
    s.close()


def test_delete_removes_row(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    s = get_session()
    aid = s.scalar(select(Application.id))
    s.close()
    assert client.post(f"/tracker/{aid}/delete").status_code == 200
    s = get_session()
    assert s.scalar(select(Application).where(Application.id == aid)) is None
    s.close()


def test_export_csv_contains_row(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    r = client.get("/tracker/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "Acme Corp" in r.text
    assert "jane@acme.com" in r.text


def test_jobs_badge_and_tracker_page(client: TestClient) -> None:
    assert "+ Track" in client.get("/jobs").text
    client.post("/jobs/i1/track")
    assert "✓ Tracked" in client.get("/jobs").text
    assert "Data Intern" in client.get("/tracker").text


def test_best_contact_prefers_verified(client: TestClient) -> None:
    name, email = _best_contact("acme")
    assert (name, email) == ("Jane Hiring", "jane@acme.com")
    assert _best_contact("unknown-co") == (None, None)


def test_tracker_sort_options_ok(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    for srt in ("due", "status", "company", "applied", "added"):
        r = client.get("/tracker", params={"sort": srt})
        assert r.status_code == 200
        assert f"sorted by {srt}" in r.text


def test_status_color_class_rendered(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    s = get_session()
    aid = s.scalar(select(Application.id))
    s.close()
    client.post(f"/tracker/{aid}/update", data={"status": "Applied"})
    body = client.get("/tracker").text
    assert "st-applied" in body  # colored status badge


def test_manual_contact_overrides_live(client: TestClient) -> None:
    client.post("/jobs/i1/track")
    s = get_session()
    aid = s.scalar(select(Application.id))
    s.close()
    # live contact is jane@acme.com; a manual override should win
    client.post(f"/tracker/{aid}/update", data={"contact_email": "me@picked.com"})
    body = client.get("/tracker").text
    assert "me@picked.com" in body
    assert "jane@acme.com" not in body
