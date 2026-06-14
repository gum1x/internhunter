from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from internhunter.core.db import Job, get_session, init_db
from internhunter.notify.select import select_notifiable
from internhunter.web.app import create_app


def _job(uid: str, verdict: str | None = None, conf: float | None = None) -> Job:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company="Acme",
        company_slug="acme",
        title=f"{uid.capitalize()} Intern",
        title_normalized=f"{uid} intern",
        is_internship=True,
        discovery_score=0.9,
        quality_verdict=verdict,
        quality_confidence=conf,
        first_seen_at=now,
        last_seen_at=now,
        posted_at=now,
    )


# --- notification gate ---
def test_notify_excludes_clear_slop_keeps_rest() -> None:
    jobs = [
        _job("spam", "spam", 95.0),
        _job("ghostlow", "ghost", 40.0),  # low confidence -> kept
        _job("clean", None, None),
        _job("unclear", "unclear", 90.0),  # unclear is not "bad" -> kept
    ]
    out = {j.job_uid for j in select_notifiable(jobs, min_fit=0.5)}
    assert "spam" not in out
    assert {"ghostlow", "clean", "unclear"} <= out


# --- dashboard toggle (never deletes; just filters the view) ---
@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    init_db(db_path=tmp_path / "q.db")
    session = get_session()
    session.add(_job("goodone"))  # clean
    session.add(_job("spamone", "spam", 95.0))  # clear slop
    session.commit()
    session.close()
    with TestClient(create_app()) as c:
        yield c


def test_dashboard_hides_slop_by_default(client: TestClient) -> None:
    body = client.get("/jobs").text
    assert "Goodone Intern" in body
    assert "Spamone Intern" not in body  # hidden by default-on toggle


def test_dashboard_shows_slop_when_toggle_off(client: TestClient) -> None:
    body = client.get("/jobs", params={"hide_low_quality": "false"}).text
    assert "Spamone Intern" in body  # still in the store, just was filtered from the view
