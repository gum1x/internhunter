from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from internhunter.core import db as dbmod
from internhunter.core.db import Contact, ContactChannel, Job, Score, get_session, init_db
from internhunter.mcp_server import (
    get_company,
    get_contacts,
    get_job,
    search_jobs,
    stats,
    top_internships,
)


def _seed(tmp_path: Path) -> None:
    dbmod._engine = None
    dbmod._session_factory = None
    init_db(tmp_path / "mcp.db")
    s = get_session()
    now = datetime.now(UTC)
    s.add(
        Job(
            job_uid="u1", ats="greenhouse", board_token="acme", canonical_url="https://acme.io/j/1",
            url_hash="h1", company="Acme", company_slug="acme", company_domain="acme.io",
            title="Software Engineering Intern", title_normalized="software engineering intern",
            is_internship=True, internship_kind="intern", location_raw="Berlin",
            location_normalized="Berlin, DE", city="Berlin", is_remote=False,
            description_text="Build features in Python.", discovery_score=0.8,
            first_seen_at=now, last_seen_at=now,
        )
    )
    s.add(
        Job(
            job_uid="u2", ats="lever", board_token="globex", canonical_url="https://globex.io/j/2",
            url_hash="h2", company="Globex", company_slug="globex",
            title="Senior Backend Engineer", title_normalized="senior backend engineer",
            is_internship=False, is_remote=True, description_text="Lead the platform.",
            first_seen_at=now, last_seen_at=now,
        )
    )
    s.add(Score(
        job_uid="u1", fit_score=87.0, matched=["python"], missing=[],
        rationale="Strong fit", model="llm:haiku:v2-prestige", input_hash="x",
    ))
    c = Contact(
        company_slug="acme", company_domain="acme.io", full_name="Jane Doe", title="Recruiter",
        role_category="recruiter", priority=0.9, email="jane@acme.io", email_status="probable",
        confidence=72.0, label="probable", linkedin_url="https://linkedin.com/in/jane",
        person_source="searxng",
    )
    s.add(c)
    s.flush()
    s.add(ContactChannel(
        contact_id=c.id, kind="github", value="https://github.com/jane",
        value_norm="github.com/jane", label="probable", confidence=60.0,
    ))
    s.commit()
    s.close()


def test_search_and_top_internships(tmp_path: Any) -> None:
    _seed(tmp_path)
    res = search_jobs(query="intern")
    assert res["count"] == 1
    job = res["jobs"][0]
    assert job["title"] == "Software Engineering Intern"
    assert job["url"] == "https://acme.io/j/1"
    assert job["fit_score"] == 87.0
    assert job["fit_rationale"] == "Strong fit"

    # internships_only filters out the senior role
    assert all(j["is_internship"] for j in search_jobs(internships_only=True, query=None)["jobs"])
    assert top_internships(limit=5)["jobs"][0]["job_uid"] == "u1"

    # non-internship search
    assert search_jobs(internships_only=False, remote=True)["count"] == 1


def test_get_job_includes_contacts(tmp_path: Any) -> None:
    _seed(tmp_path)
    job = get_job(job_uid="u1")
    assert job["company"] == "Acme"
    assert job["description"].startswith("Build features")
    assert job["contacts"][0]["name"] == "Jane Doe"
    assert job["contacts"][0]["email"] == "jane@acme.io"
    # lookup by url works too
    assert get_job(url="https://acme.io/j/1")["job_uid"] == "u1"
    assert "error" in get_job(job_uid="nope")


def test_get_contacts_and_company(tmp_path: Any) -> None:
    _seed(tmp_path)
    contacts = get_contacts("acme")
    assert contacts["count"] == 1
    person = contacts["contacts"][0]
    assert person["email_label"] == "probable"
    assert person["linkedin"] == "https://linkedin.com/in/jane"
    assert any(ch["kind"] == "github" for ch in person["other_channels"])

    comp = get_company("Acme")
    assert comp["jobs"][0]["job_uid"] == "u1"
    assert comp["contacts"][0]["name"] == "Jane Doe"


def test_stats(tmp_path: Any) -> None:
    _seed(tmp_path)
    st = stats()
    assert st["internships"] == 1
    assert st["internships_rated"] == 1
    assert st["jobs"] == 2
    assert st["contacts"] == 1
