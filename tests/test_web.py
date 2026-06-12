from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from internhunter.core.db import Job, get_session, init_db
from internhunter.web.app import create_app


def _make_job(*, uid: str, title: str, is_internship: bool) -> Job:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://example.com/{uid}",
        url_hash=uid,
        company="Acme Corp",
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        is_internship=is_internship,
        internship_kind="intern" if is_internship else None,
        location_normalized="Remote",
        is_remote=is_internship,
        posted_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    init_db(db_path=tmp_path / "test.db")
    session = get_session()
    session.add(_make_job(uid="i1", title="Software Engineering Intern", is_internship=True))
    session.add(_make_job(uid="f1", title="Senior Staff Engineer", is_internship=False))
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        yield test_client


def test_index_renders_intern(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Software Engineering Intern" in response.text


def test_jobs_filter_matches_and_excludes(client: TestClient) -> None:
    match = client.get("/jobs", params={"q": "Software Engineering"})
    assert match.status_code == 200
    assert "Software Engineering Intern" in match.text

    miss = client.get("/jobs", params={"q": "zzzznomatch"})
    assert miss.status_code == 200
    assert "Software Engineering Intern" not in miss.text


def test_export_csv(client: TestClient) -> None:
    response = client.get("/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Software Engineering Intern" in response.text


def test_export_csv_sanitizes_formula_injection(tmp_path: Path) -> None:
    init_db(db_path=tmp_path / "inj.db")
    session = get_session()
    job = _make_job(uid="x1", title="=HYPERLINK(\"http://evil\")", is_internship=True)
    session.add(job)
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        response = test_client.get("/export.csv")
    assert response.status_code == 200
    assert "'=HYPERLINK" in response.text
    assert ",=HYPERLINK" not in response.text


def test_export_csv_not_truncated(tmp_path: Path) -> None:
    init_db(db_path=tmp_path / "big.db")
    session = get_session()
    for i in range(250):
        session.add(_make_job(uid=f"b{i}", title=f"Intern {i}", is_internship=True))
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        response = test_client.get("/export.csv")
    assert response.status_code == 200
    data_rows = [line for line in response.text.strip().splitlines() if line]
    assert len(data_rows) == 251


def test_export_csv_link_carries_filters(client: TestClient) -> None:
    response = client.get("/", params={"q": "Software", "remote": "true", "sort": "title"})
    assert response.status_code == 200
    assert "/export.csv?" in response.text
    assert "q=Software" in response.text
    assert "sort=title" in response.text


def test_deadline_sort_soonest_first(tmp_path: Path) -> None:
    from datetime import timedelta

    init_db(db_path=tmp_path / "dl.db")
    session = get_session()
    base = datetime(2026, 6, 1, tzinfo=UTC)
    far = _make_job(uid="far", title="Far Intern", is_internship=True)
    far.deadline_at = base + timedelta(days=60)
    soon = _make_job(uid="soon", title="Soon Intern", is_internship=True)
    soon.deadline_at = base + timedelta(days=3)
    session.add(far)
    session.add(soon)
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        body = test_client.get("/jobs", params={"sort": "deadline_at"}).text
    assert body.index("Soon Intern") < body.index("Far Intern")
