from __future__ import annotations

from pathlib import Path

from internhunter.core.db import Job
from internhunter.referrals import (
    Connection,
    connection_for_job,
    draft_intro,
    get_connections,
    load_connections,
    match_connection,
)

_YAML = """
connections:
  - name: "Dr. Ada Advisor"
    relationship: "my research advisor at GWU"
    contact: "ada@gwu.edu"
    firms: []
    domains: [gwu.edu]
    tags: [academia]
  - name: "Pat Prediction"
    relationship: "collaborating on Polymarket price-discovery research"
    firms: [Polymarket, Kalshi]
    domains: [polymarket.com]
  - name: "Sam Startup"
    relationship: "working together at Teach Anything AI"
    firms: ["Teach Anything AI"]
"""


def _connections(tmp_path: Path) -> tuple[Connection, ...]:
    path = tmp_path / "connections.yaml"
    path.write_text(_YAML)
    return load_connections(path)


def _job(company: str, slug: str, domain: str | None = None) -> Job:
    return Job(
        job_uid=f"{slug}:intern",
        ats="ashby",
        board_token=slug,
        canonical_url=f"https://jobs.example/{slug}",
        url_hash=f"{slug}:intern",
        company=company,
        company_slug=slug,
        company_domain=domain,
        title="Software Engineer Intern",
        title_normalized="software engineer intern",
    )


def test_load_parses_connections(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    assert [c.name for c in conns] == ["Dr. Ada Advisor", "Pat Prediction", "Sam Startup"]
    assert conns[1].firm_slugs == ("polymarket", "kalshi")


def test_missing_file_yields_no_connections(tmp_path: Path) -> None:
    assert load_connections(tmp_path / "nope.yaml") == ()


def test_match_by_domain(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    conn = match_connection(conns, "Polymarket", "polymarket", "polymarket.com")
    assert conn is not None and conn.name == "Pat Prediction"


def test_match_by_firm_name_survives_corporate_suffix(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    conn = match_connection(conns, "Kalshi Inc.", "kalshi-inc", None)
    assert conn is not None and conn.name == "Pat Prediction"


def test_match_multiword_firm(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    conn = match_connection(conns, "Teach Anything AI", "teach-anything-ai", None)
    assert conn is not None and conn.name == "Sam Startup"


def test_no_match_is_cold_apply(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    assert match_connection(conns, "Unrelated Co", "unrelated-co", "unrelated.io") is None


def test_connection_for_job(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    job = _job("Polymarket", "polymarket", "polymarket.com")
    conn = connection_for_job(conns, job)
    assert conn is not None and conn.name == "Pat Prediction"


def test_draft_intro_mentions_company_role_link_and_relationship(tmp_path: Path) -> None:
    conns = _connections(tmp_path)
    job = _job("Polymarket", "polymarket", "polymarket.com")
    conn = connection_for_job(conns, job)
    assert conn is not None
    draft = draft_intro(conn, job)
    assert "Hi Pat" in draft
    assert "Polymarket" in draft
    assert "Software Engineer Intern" in draft
    assert job.canonical_url in draft
    assert "price-discovery" in draft


def test_get_connections_mtime_cache(tmp_path: Path) -> None:
    import os

    path = tmp_path / "connections.yaml"
    path.write_text(_YAML)
    assert len(get_connections(path)) == 3
    path.write_text("connections:\n  - name: Solo\n")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    assert len(get_connections(path)) == 1


def test_malformed_yaml_degrades(tmp_path: Path) -> None:
    path = tmp_path / "connections.yaml"
    path.write_text("- not\n- a\n- mapping\n")
    assert load_connections(path) == ()
