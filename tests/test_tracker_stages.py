from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.core.db import Application, Job, get_session, init_db
from internhunter.tracker import (
    STAGES,
    export_csv,
    list_applications,
    normalize_stage,
    set_stage,
    track_job,
    tracker_summary,
)


def _job(uid: str, title: str = "SWE Intern", company: str = "Acme") -> Job:
    now = datetime(2026, 7, 1, tzinfo=UTC).replace(tzinfo=None)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company=company,
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        is_internship=True,
        posted_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    init_db(db_path=tmp_path / "t.db")
    s = get_session()
    yield s
    s.close()


def test_normalize_stage_accepts_aliases_and_display_forms() -> None:
    assert normalize_stage("found") == "To Apply"
    assert normalize_stage("applied") == "Applied"
    assert normalize_stage("referral-requested") == "Referral Requested"
    assert normalize_stage("Referral Requested") == "Referral Requested"
    assert normalize_stage("interview") == "Interviewing"
    assert normalize_stage("offer") == "Offer"
    assert normalize_stage("REJECTED") == "Rejected"
    assert normalize_stage("bogus") is None


def test_track_job_records_found_stage(session: Session) -> None:
    job = _job("j1")
    session.add(job)
    session.flush()
    app = track_job(session, job, stage="found")
    assert app is not None
    assert app.status == "To Apply"
    assert app.company == "Acme"
    assert app.link == "https://x/j1"
    assert app.warm_intro is False


def test_track_job_idempotent_and_preserves_advanced_stage(session: Session) -> None:
    job = _job("j1")
    session.add(job)
    session.flush()
    track_job(session, job)
    session.commit()
    set_stage(session, "j1", "interview")
    session.commit()
    # a second alert for the same posting must not regress the stage
    assert track_job(session, job) is None
    app = session.scalar(select(Application).where(Application.job_uid == "j1"))
    assert app is not None and app.status == "Interviewing"


def test_track_job_stores_referral_fields(session: Session) -> None:
    job = _job("j1", company="Polymarket")
    session.add(job)
    session.flush()
    app = track_job(
        session, job, warm_intro=True, connection_name="Pat", intro_draft="Hi Pat —"
    )
    assert app is not None
    assert app.warm_intro is True
    assert app.connection_name == "Pat"
    assert app.intro_draft == "Hi Pat —"


def test_set_stage_by_id_and_job_uid(session: Session) -> None:
    job = _job("j1")
    session.add(job)
    session.flush()
    app = track_job(session, job)
    assert app is not None
    session.commit()
    updated = set_stage(session, str(app.id), "applied")
    assert updated is not None and updated.status == "Applied"
    assert updated.applied_at is not None  # auto-stamped like the web tracker
    updated = set_stage(session, "j1", "offer")
    assert updated is not None and updated.status == "Offer"


def test_set_stage_unknown_stage_raises(session: Session) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        set_stage(session, "j1", "vibing")


def test_set_stage_missing_app_returns_none(session: Session) -> None:
    assert set_stage(session, "nope", "applied") is None


def test_summary_counts_every_stage(session: Session) -> None:
    for i, stage in enumerate(["found", "applied", "applied", "offer"]):
        job = _job(f"j{i}")
        session.add(job)
        session.flush()
        track_job(session, job, stage=stage, warm_intro=(i == 0))
    session.commit()
    summary = tracker_summary(session)
    assert summary.total == 4
    assert summary.by_stage["To Apply"] == 1
    assert summary.by_stage["Applied"] == 2
    assert summary.by_stage["Offer"] == 1
    assert summary.warm == 1
    assert set(STAGES) <= set(summary.by_stage)


def test_list_applications_filters_and_orders_by_stage(session: Session) -> None:
    for i, stage in enumerate(["offer", "found", "applied"]):
        job = _job(f"j{i}")
        session.add(job)
        session.flush()
        track_job(session, job, stage=stage)
    session.commit()
    ordered = [a.status for a in list_applications(session)]
    assert ordered == ["To Apply", "Applied", "Offer"]
    only_applied = list_applications(session, stage="applied")
    assert len(only_applied) == 1 and only_applied[0].status == "Applied"


def test_export_csv(session: Session, tmp_path: Path) -> None:
    job = _job("j1", company="Polymarket")
    session.add(job)
    session.flush()
    track_job(session, job, warm_intro=True, connection_name="Pat")
    session.commit()
    out = tmp_path / "pipeline.csv"
    rows = export_csv(session, out)
    assert rows == 1
    content = out.read_text()
    assert "Polymarket" in content
    assert "warm" in content
    assert "Pat" in content
