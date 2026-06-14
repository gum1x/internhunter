from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text

import internhunter.core.db as db


def _make_old_db(path: Path) -> None:
    """A pre-existing DB whose jobs/companies tables predate the quality columns."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY, job_uid TEXT, url_hash TEXT, "
        "title TEXT, company_slug TEXT, ats TEXT)"
    )
    con.execute(
        "INSERT INTO jobs (job_uid, url_hash, title, company_slug, ats) "
        "VALUES ('u1','h1','Old Intern','acme','greenhouse')"
    )
    con.execute(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, company_slug TEXT, status TEXT)"
    )
    con.execute("INSERT INTO companies (company_slug, status) VALUES ('acme','done')")
    con.commit()
    con.close()


def test_migration_adds_columns_and_preserves_rows(tmp_path: Any) -> None:
    path = tmp_path / "old.db"
    _make_old_db(path)

    db.init_db(path)  # runs _migrate then create_all

    engine = create_engine(f"sqlite:///{path}")
    insp = inspect(engine)
    job_cols = {c["name"] for c in insp.get_columns("jobs")}
    assert {
        "quality_score",
        "quality_verdict",
        "quality_flags",
        "quality_confidence",
        "quality_model",
        "quality_checked_at",
    } <= job_cols
    assert "domain_confidence" in {c["name"] for c in insp.get_columns("companies")}
    # new tables created for free
    assert "sightings" in insp.get_table_names()
    assert "contact_channels" in insp.get_table_names()

    # existing rows intact, new columns NULL-backfilled
    with engine.connect() as conn:
        row = conn.execute(text("SELECT title, quality_score FROM jobs WHERE job_uid='u1'")).one()
        assert row[0] == "Old Intern"
        assert row[1] is None
    engine.dispose()


def test_migration_is_idempotent(tmp_path: Any) -> None:
    path = tmp_path / "old.db"
    _make_old_db(path)
    db.init_db(path)
    db.init_db(path)  # second run must not raise (columns already present)
    engine = create_engine(f"sqlite:///{path}")
    assert "quality_score" in {c["name"] for c in inspect(engine).get_columns("jobs")}
    engine.dispose()
