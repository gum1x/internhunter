from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from internhunter.config.settings import Settings
from internhunter.core.db import Job
from internhunter.llm.quality import (
    build_quality_prompt,
    judge_quality_jobs,
    parse_quality,
    select_borderline,
)

_REPLY = (
    '{"legit": 20, "substance": 15, "verdict": "spam", '
    '"flags": ["commission-only"], "confidence": 90, "reason": "MLM lead-gen."}'
)


class FakeBackend:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self.reply


def _job(uid: str, score: float, quality_score: float | None, verdict: str | None = None) -> Job:
    now = datetime(2026, 6, 1)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company="Acme",
        company_slug="acme",
        title="Intern",
        title_normalized="intern",
        description_text="Earn big. Commission only.",
        is_internship=True,
        discovery_score=score,
        quality_score=quality_score,
        quality_verdict=verdict,
        first_seen_at=now,
        last_seen_at=now,
        posted_at=now,
    )


def test_parse_quality_validates_verdict_and_clamps() -> None:
    out = parse_quality('{"legit": 150, "substance": 5, "verdict": "weird", "confidence": -3}')
    assert out["legit"] == 100
    assert out["verdict"] == "unclear"  # invalid verdict -> abstain
    assert out["confidence"] == 0


def test_parse_quality_unparseable_is_unclear() -> None:
    try:
        parse_quality("not json at all")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass  # caller treats the exception as skip; verdict stays None (never auto-pass)


def test_select_borderline_only_flagged_unjudged() -> None:
    # clean (score 100, no verdict) -> skipped; borderline (score 50) -> selected;
    # already-judged -> skipped.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from internhunter.core.db import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            _job("clean", 0.9, 100.0),
            _job("borderline", 0.8, 50.0),
            _job("judged", 0.7, 40.0, verdict="spam"),
        ]
    )
    session.commit()
    picked = {j.job_uid for j in select_borderline(session, top_k=10)}
    assert picked == {"borderline"}
    session.close()


def test_judge_quality_jobs_persists_verdict(db_session: Session, tmp_path: Path) -> None:
    db_session.add(_job("b1", 0.8, 50.0))
    db_session.commit()
    backend = FakeBackend(_REPLY)
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    judged = judge_quality_jobs(db_session, backend, settings=settings, top_k=10)
    assert judged == 1
    job = db_session.get(Job, db_session.query(Job).first().id)
    assert job.quality_verdict == "spam"
    assert job.quality_confidence == 90
    assert job.quality_model.startswith("quality:")
    assert job.quality_checked_at is not None


def test_build_quality_prompt_omits_source() -> None:
    prompt = build_quality_prompt(_job("a", 0.9, 50.0))
    assert "greenhouse" not in prompt.lower()  # source hidden to avoid brand bias
    assert "Intern" in prompt
