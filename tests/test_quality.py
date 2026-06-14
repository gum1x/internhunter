from __future__ import annotations

from datetime import UTC, datetime, timedelta

from internhunter.core.models import NormalizedJob
from internhunter.match.quality import classify_quality, days_open


def _job(**kw: object) -> NormalizedJob:
    now = datetime.now(UTC)
    base = dict(
        job_uid="u",
        ats="greenhouse",
        board_token="acme",
        canonical_url="https://x",
        url_hash="h",
        company="Acme",
        company_slug="acme",
        title="Software Engineering Intern",
        title_normalized="software engineering intern",
        is_internship=True,
        description_text="We are looking for a summer intern to join our team. " * 20,
        first_seen_at=now,
        last_seen_at=now,
    )
    base.update(kw)
    return NormalizedJob(**base)  # type: ignore[arg-type]


def test_clean_job_scores_high_no_flags() -> None:
    r = classify_quality(_job())
    assert r.score >= 95
    assert r.flags == []
    assert r.verdict_hint == "ok"


def test_content_free_flagged() -> None:
    r = classify_quality(_job(description_text="Apply now."))
    assert "content_free" in r.flags
    assert r.score < 100


def test_mlm_scam_flagged_and_suspect() -> None:
    text = "Commission only role. Be your own boss! Message us on WhatsApp to apply. " * 6
    r = classify_quality(_job(description_text=text))
    assert "mlm_scam" in r.flags
    assert r.verdict_hint == "suspect"
    assert r.score < 60


def test_agency_flagged() -> None:
    r = classify_quality(
        _job(description_text="We are recruiting on behalf of our client, a leading firm. " * 10)
    )
    assert "agency" in r.flags


def test_ghost_language_flagged() -> None:
    text = "Join our talent community for future openings. We are always looking. " * 8
    r = classify_quality(_job(description_text=text))
    assert "ghost_language" in r.flags


def test_ghost_duration_flagged() -> None:
    now = datetime.now(UTC)
    job = _job(posted_at=now - timedelta(days=120), last_seen_at=now)
    r = classify_quality(job, now=now)
    assert "ghost_duration" in r.flags


def test_requirement_incoherence() -> None:
    text = "Internship requiring 8 years of experience in distributed systems. " * 8
    r = classify_quality(_job(description_text=text))
    assert "requirement_incoherence" in r.flags


def test_rolling_does_not_make_unclear() -> None:
    # The prime false-drop trap: a legit rolling internship must NOT be downgraded.
    r = classify_quality(_job(is_rolling=True))
    assert "rolling" in r.flags
    assert r.verdict_hint == "ok"
    assert r.score >= 95


def test_days_open_computed() -> None:
    now = datetime.now(UTC)
    job = _job(posted_at=now - timedelta(days=30), last_seen_at=now)
    assert days_open(job, now=now) == 30
