from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings
from internhunter.core.db import Job, Score
from internhunter.llm.client import LlmCache
from internhunter.llm.score import build_prompt, llm_score_jobs, parse_score

# prestige 100, fit 81 -> value = round(sqrt(100*81)) = 90
_REPLY = '{"prestige": 100, "fit": 81, "reason": "Strong fit."}'


class FakeBackend:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self.reply


def _job(uid: str, title: str, score: float) -> Job:
    now = datetime(2026, 6, 1)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company="Acme",
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        description_text="Build things in python.",
        is_internship=True,
        discovery_score=score,
        first_seen_at=now,
        last_seen_at=now,
        posted_at=now,
    )


def test_llm_score_jobs_persists_scores(db_session: Session, tmp_path: Path) -> None:
    db_session.add_all([_job("a1", "python intern", 0.9), _job("b1", "data intern", 0.5)])
    db_session.commit()

    backend = FakeBackend(_REPLY)
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    count = llm_score_jobs(
        db_session, backend, profile_text="python developer", settings=settings, top_k=2
    )
    assert count == 2

    rows = list(db_session.scalars(select(Score)))
    assert len(rows) == 2
    for row in rows:
        assert row.model is not None and row.model.startswith("llm:")
        assert row.fit_score == 90
        assert row.matched == ["prestige 100/100", "fit 81/100"]
        assert row.missing == []
        assert row.rationale == "Strong fit."


class FlakyBackend:
    def __init__(self, good_reply: str) -> None:
        self.good_reply = good_reply
        self.calls = 0

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("claude cli returned non-json stdout")
        return self.good_reply


def test_llm_score_jobs_isolates_failing_job(db_session: Session, tmp_path: Path) -> None:
    db_session.add_all([_job("a1", "python intern", 0.9), _job("b1", "data intern", 0.5)])
    db_session.commit()

    backend = FlakyBackend(_REPLY)
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    count = llm_score_jobs(
        db_session, backend, profile_text="python developer", settings=settings, top_k=2
    )
    assert count == 1

    rows = list(db_session.scalars(select(Score)))
    assert len(rows) == 1
    assert rows[0].fit_score == 90


def test_llm_score_jobs_uses_cache(db_session: Session, tmp_path: Path) -> None:
    db_session.add_all([_job("a1", "python intern", 0.9), _job("b1", "data intern", 0.5)])
    db_session.commit()

    backend = FakeBackend(_REPLY)
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    cache = LlmCache(tmp_path / "cache")

    llm_score_jobs(
        db_session,
        backend,
        profile_text="python developer",
        settings=settings,
        top_k=2,
        cache=cache,
    )
    assert backend.calls == 2
    llm_score_jobs(
        db_session,
        backend,
        profile_text="python developer",
        settings=settings,
        top_k=2,
        cache=cache,
    )
    assert backend.calls == 2


def test_build_prompt_contains_title(db_session: Session) -> None:
    job = _job("a1", "python intern", 0.9)
    prompt = build_prompt("a profile", job)
    assert "python intern" in prompt
    assert "Acme" in prompt


def test_parse_score_clamps_and_defaults() -> None:
    high = parse_score('{"prestige": 150, "fit": 150}')  # both clamp to 100 -> value 100
    assert high["fit"] == 100
    assert high["matched"] == ["prestige 100/100", "fit 100/100"]
    assert high["missing"] == []
    assert high["rationale"] == ""

    low = parse_score('{"prestige": -5, "fit": -5}')  # clamp to 0 -> value 0
    assert low["fit"] == 0
