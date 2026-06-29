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


def test_static_assets_served_and_htmx_local(client: TestClient) -> None:
    css = client.get("/static/app.css")
    assert css.status_code == 200 and "--background" in css.text
    htmx = client.get("/static/htmx.min.js")
    assert htmx.status_code == 200 and "htmx" in htmx.text
    page = client.get("/")
    # htmx is vendored locally, not pulled from a CDN.
    assert "/static/htmx.min.js" in page.text
    assert "unpkg.com" not in page.text
    assert 'id="theme-toggle"' in page.text


def test_empty_db_shows_first_run_cta(tmp_path: Path) -> None:
    init_db(db_path=tmp_path / "empty.db")
    with TestClient(create_app()) as c:
        page = c.get("/")
        assert page.status_code == 200
        assert "No internships yet" in page.text


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


def test_export_csv_sanitizes_leading_newline_formula(tmp_path: Path) -> None:
    init_db(db_path=tmp_path / "nl.db")
    session = get_session()
    job = _make_job(uid="x2", title="\n=cmd|'/c calc'!A1", is_internship=True)
    session.add(job)
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        response = test_client.get("/export.csv")
    assert response.status_code == 200
    assert "\"'\n=cmd" in response.text  # leading newline neutralized with a quote


def test_table_neutralizes_javascript_url(tmp_path: Path) -> None:
    init_db(db_path=tmp_path / "xss.db")
    session = get_session()
    job = _make_job(uid="j1", title="Evil Intern", is_internship=True)
    job.canonical_url = "javascript:alert(1)"
    session.add(job)
    session.commit()
    session.close()
    with TestClient(create_app()) as test_client:
        body = test_client.get("/jobs").text
    assert "javascript:alert(1)" not in body
    assert 'href="#"' in body


def test_csrf_rejects_cross_origin_post(client: TestClient) -> None:
    # Same-origin and Origin-less POSTs pass the guard (reach the handler -> 404 for an
    # unknown uid); a cross-origin Origin is rejected before the handler runs.
    same = client.post("/jobs/nope/track", headers={"Origin": "http://testserver"})
    assert same.status_code == 404
    none = client.post("/jobs/nope/track")
    assert none.status_code == 404
    blocked = client.post("/jobs/nope/track", headers={"Origin": "http://evil.example"})
    assert blocked.status_code == 403


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


def test_search_button_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProc:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        "internhunter.web.app.subprocess.Popen", lambda *a, **k: _FakeProc()
    )
    started = client.post("/search")
    assert started.status_code == 200
    assert "Search complete" in started.text or "Searching" in started.text
    status = client.get("/search-status")
    assert status.status_code == 200


def test_dashboard_basic_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    init_db(db_path=tmp_path / "auth.db")
    monkeypatch.setenv("INTERNHUNTER_AUTH_USER", "testuser")
    monkeypatch.setenv("INTERNHUNTER_AUTH_PASS", "testpass")
    with TestClient(create_app()) as c:
        assert c.get("/").status_code == 401
        good = base64.b64encode(b"testuser:testpass").decode()
        assert c.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200
        bad = base64.b64encode(b"testuser:nope").decode()
        assert c.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
